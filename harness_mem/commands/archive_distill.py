"""Explicit, project-detected batch processing for Codex archived sessions."""

from __future__ import annotations

import json
import os
import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.commands.support import DEFAULT_DATA_DIR, workspace_root_from_path
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.governance_status import TRUTH_LAYER_STATUSES
from harness_mem.maintenance_lock import exclusive_maintenance_run
from harness_mem.session_notes import materialize_session_note
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import transcript_bytes_revision


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _detect_project_root(cwd: str) -> Path | None:
    if not cwd:
        return None
    candidate = Path(cwd).expanduser()
    if not candidate.is_dir():
        return None
    return workspace_root_from_path(candidate).resolve()

def _ledger_path(data_dir: Path, day: str) -> Path:
    return data_dir / "archive_distill" / "daily" / f"{day}.json"


def _run_receipt_path(data_dir: Path, run_id: str) -> Path:
    return data_dir / "archive_distill" / "runs" / f"{run_id}.json"


def _terminal_index_path(data_dir: Path) -> Path:
    return data_dir / "archive_distill" / "terminal_index.json"


def _read_ledger(data_dir: Path, day: str) -> dict[str, Any]:
    path = _ledger_path(data_dir, day)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"day": day, "processed_session_ids": [], "runs": []}
    return payload if isinstance(payload, dict) else {"day": day, "processed_session_ids": [], "runs": []}


def _read_terminal_index(data_dir: Path) -> dict[str, Any]:
    path = _terminal_index_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"version": 1, "sessions": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), dict):
        return {"version": 1, "sessions": {}}
    return payload


def _source_revision(path: Path) -> str:
    """Return the exact native revision used by transcript snapshot persistence."""

    return transcript_bytes_revision(path.read_bytes())


def _terminal_entry_matches(row: dict[str, Any], entry: Any) -> bool:
    return bool(
        isinstance(entry, dict)
        and entry.get("source_revision") == row.get("source_revision")
        and entry.get("project_name") == row.get("project_name")
    )


def _partial_run_receipts(data_dir: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    runs_dir = data_dir / "archive_distill" / "runs"
    try:
        paths = sorted(runs_dir.glob("*.json"))
    except OSError:
        return []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and (payload.get("verification") or {}).get("status") != "passed"
        ):
            receipts.append(payload)
    return receipts


async def _repair_partial_completed_receipts(
    backend: LocalMemoryBackend,
    *,
    data_dir: Path,
    terminal_sessions: dict[str, Any],
    notes_dir: Path,
) -> dict[str, Any]:
    """Reverify completed jobs whose partial receipt was never admitted.

    A prior verifier bug can leave a completed job in a ``quarantined``
    terminal entry even though the job, Note, and current truth are all
    durable.  Those entries are eligible for repair only when the receipt
    proves that it is the same job and immutable source revision.  This keeps
    a real semantic failure quarantined instead of turning ``repair-only``
    into an unbounded retry path.
    """

    repaired: list[dict[str, Any]] = []
    repaired_session_ids: set[str] = set()

    def _admit(
        outcome: dict[str, Any],
        verified: dict[str, Any],
        *,
        source_run_id: str | None,
        repair_kind: str,
    ) -> None:
        if verified["status"] != "passed":
            return
        session_id = str(outcome.get("session_id") or "")
        terminal_sessions[session_id] = {
            "session_id": session_id,
            "source_revision": outcome.get("source_revision"),
            "project_name": outcome.get("project_name"),
            "project_root": outcome.get("project_root"),
            "distill_job_id": outcome.get("distill_job_id"),
            "disposition": "verified_completed",
            "verified_at": verification["verified_at"],
            "run_id": source_run_id,
            "repaired_from_partial_receipt": True,
            "repair_kind": repair_kind,
        }
        repaired_session_ids.add(session_id)
        repaired.append(
            {
                "session_id": session_id,
                "distill_job_id": outcome.get("distill_job_id"),
                "source_run_id": source_run_id,
                "repair_kind": repair_kind,
            }
        )

    for receipt in _partial_run_receipts(data_dir):
        pending_outcomes: list[dict[str, Any]] = []
        for outcome in receipt.get("outcomes", []):
            if not isinstance(outcome, dict) or outcome.get("status") != "completed":
                continue
            session_id = str(outcome.get("session_id") or "")
            prior = terminal_sessions.get(session_id)
            if prior is None:
                pending_outcomes.append(outcome)
                continue
            if not isinstance(prior, dict) or prior.get("disposition") != "quarantined":
                continue
            if (
                prior.get("distill_job_id") == outcome.get("distill_job_id")
                and prior.get("source_revision") == outcome.get("source_revision")
            ):
                pending_outcomes.append(outcome)
        if not pending_outcomes:
            continue
        repair_result = {**receipt, "outcomes": pending_outcomes}
        verification = await _verify_archive_distill_run(
            backend,
            result=repair_result,
        )
        for outcome, verified in zip(
            pending_outcomes,
            verification["outcomes"],
            strict=True,
        ):
            _admit(
                outcome,
                verified,
                source_run_id=receipt.get("run_id"),
                repair_kind="completed_receipt_reverification",
            )

    # A previous archive pass can record ``deferred`` before an Agent finishes
    # the semantic review through the normal MCP path.  Once that exact job is
    # completed, its persisted Job/Note/Packet are a stronger authority than
    # the stale batch outcome. Re-admit only the same quarantined job and
    # immutable revision; this never retries a genuinely failed job.
    completed_after_deferred: list[dict[str, Any]] = []
    for session_id, entry in terminal_sessions.items():
        if session_id in repaired_session_ids:
            continue
        if not isinstance(entry, dict) or entry.get("disposition") != "quarantined":
            continue
        if entry.get("reason") != "deferred":
            continue
        job_id = str(entry.get("distill_job_id") or "")
        job = backend.transcript_store.get_distill_job(job_id) if job_id else None
        if (
            job is None
            or job.status != "completed"
            or job.session_id != session_id
            or job.source_revision != entry.get("source_revision")
            or job.project_name != entry.get("project_name")
            or job.project_root != entry.get("project_root")
        ):
            continue
        packet = dict((job.promotion_summary or {}).get("answer_packet") or {})
        completed_after_deferred.append(
            {
                "session_id": session_id,
                "project_name": job.project_name,
                "project_root": job.project_root,
                "distill_job_id": job.id,
                "status": "completed",
                "source_revision": job.source_revision,
                "answer_packet": packet,
                "note": materialize_session_note(job, notes_dir=notes_dir),
            }
        )
    if completed_after_deferred:
        verification = await _verify_archive_distill_run(
            backend,
            result={
                "policy": {"require_answer_packet": True},
                "outcomes": completed_after_deferred,
            },
        )
        for outcome, verified in zip(
            completed_after_deferred,
            verification["outcomes"],
            strict=True,
        ):
            _admit(
                outcome,
                verified,
                source_run_id=None,
                repair_kind="completed_job_after_deferred_receipt",
            )
    return {"count": len(repaired), "outcomes": repaired}


def _write_ledger(data_dir: Path, day: str, payload: dict[str, Any]) -> Path:
    path = _ledger_path(data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


_TRIVIAL_ARCHIVE_REQUEST = re.compile(
    r"^\s*(?:return|reply|respond|output)\s+exactly\s*:\s*[^\r\n]{1,240}"
    r"(?:\s*,?\s*(?:without|and do not)\b[^\r\n]{0,240})?\s*$",
    re.IGNORECASE,
)


def _trivial_archive_request(adapter: CodexArchiveAdapter, source_path: Path) -> str | None:
    """Recognize narrow echo-only smoke sessions without semantic inference."""

    _meta, turns = adapter.parse_jsonl_session(source_path)
    # Archive parsers also create turns for host hook/tool events. Those turns
    # have no user intent and must not turn one exact-output request into a
    # semantic session merely because background maintenance was recorded.
    user_messages = [
        text
        for turn in turns
        if (text := str(turn.get("user") or "").strip())
    ]
    if (
        len(user_messages) == 1
        and _TRIVIAL_ARCHIVE_REQUEST.fullmatch(user_messages[0])
    ):
        return user_messages[0]
    return None


def _active_distill_worker_jobs(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Return only jobs with a live chunk or semantic-review lease."""

    current = now or _now()
    active: list[dict[str, str]] = []
    for job in backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        limit=100_000,
    ):
        live_review = bool(
            job.status == "reviewing"
            and job.review_lease_owner
            and job.review_lease_until
            and job.review_lease_until > current
        )
        live_chunks = bool(
            job.status == "processing"
            and any(
                checkpoint.status == "processing"
                and checkpoint.lease_owner
                and checkpoint.lease_until
                and checkpoint.lease_until > current
                for checkpoint in backend.transcript_store.list_distill_checkpoints(
                    job.id
                )
            )
        )
        if live_review or live_chunks:
            active.append(
                {
                    "job_id": job.id,
                    "project_name": job.project_name,
                    "status": job.status,
                }
            )
    return active


class _TrivialArchiveProvider:
    """Deterministic zero-token decision for exact-output smoke sessions."""

    name = "archive_trivial_classifier"

    def __init__(self, request: str):
        self.request = request

    def decide(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        started = time.monotonic()
        if heartbeat is not None:
            heartbeat()
        refs = list(manifest.get("zero_candidate_exchange_refs") or [])
        inspected = [
            {
                "exchange_index": int(item["exchange_index"]),
                "content_sha256": str(item["content_sha256"]),
            }
            for item in refs
        ]
        decision = AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "Exact-output smoke session with no reusable project knowledge.",
                    "final_user_request": self.request,
                    "final_outcome": "The requested exact-output smoke response was produced.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "not_applicable",
                    "promotion_decision": "no_promotion",
                    "zero_candidate_challenge": {
                        "version": "v1",
                        "source_revision": str(manifest["source_revision"]),
                        "evidence_fidelity": "complete",
                        "future_utility": "none",
                        "checks": {
                            "user_correction": "absent",
                            "explicit_decision": "absent",
                            "successful_solution": "absent",
                            "repeated_failure": "absent",
                            "rule_or_preference": "absent",
                            "reusable_workflow_or_fact": "absent",
                            "version_or_migration": "absent",
                            "unfinished_handoff": "absent",
                        },
                        "inspected_exchange_refs": inspected,
                        "conclusion": "no_durable_candidate",
                        "rationale": (
                            "The single exact-output smoke exchange contains no "
                            "durable decision, preference, reusable fact, or unfinished work."
                        ),
                    },
                },
                "candidates": [],
            }
        )
        digest = hashlib.sha256(self.request.encode("utf-8")).hexdigest()
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model="deterministic",
            duration_seconds=time.monotonic() - started,
            input_sha256=digest,
            response_sha256=digest,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            event_count=1,
            sandbox="no-tools",
        )

    def assimilate(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat=None,
    ) -> ProviderResult:
        """Fail closed: the exact-output fixture must never create candidates."""

        del manifest, runtime_dir, heartbeat
        raise ProviderError(
            "trivial archive provider cannot perform semantic assimilation",
            kind="unrecoverable",
        )

    def verify(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat=None,
    ) -> ProviderResult:
        """Fail closed: zero-candidate smoke sessions have nothing to verify."""

        del manifest, runtime_dir, heartbeat
        raise ProviderError(
            "trivial archive provider cannot verify semantic candidates",
            kind="unrecoverable",
        )


def inventory_codex_archives(
    *,
    control_root: Path,
    config: MergedConfig,
    archive_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a content-free inventory grouped by detected source project."""

    adapter = CodexArchiveAdapter(None, archive_dir=archive_dir)
    issues: list[dict[str, str]] = []
    sessions = adapter.list_sessions(scope="all", issues=issues)
    current_root = control_root.resolve()
    rows: list[dict[str, Any]] = []
    for session in sessions:
        detected = _detect_project_root(str(session.get("cwd") or ""))
        status = "eligible"
        if detected is None:
            status = "unresolved_project"
        elif config.archive_distill_project_scope == "current" and detected != current_root:
            status = "outside_current_project"
        rows.append(
            {
                "session_id": str(session["session_id"]),
                "source_path": str(session["path"]),
                "cwd": str(session.get("cwd") or ""),
                "project_root": str(detected) if detected is not None else None,
                "project_name": detected.name if detected is not None else None,
                "updated_at": session["mtime"].isoformat(),
                "mtime_ns": int(session.get("mtime_ns") or 0),
                "size_bytes": int(session.get("size_bytes") or 0),
                "status": status,
            }
        )
    eligible = [row for row in rows if row["status"] == "eligible"]
    eligible.sort(
        key=lambda row: (row["updated_at"], row["session_id"]),
        reverse=config.archive_distill_order == "recent_first",
    )
    by_project: dict[str, int] = {}
    for row in eligible:
        key = str(row["project_root"])
        by_project[key] = by_project.get(key, 0) + 1
    return {
        "archive_dir": str(adapter.archive_dir),
        "sessions_found": len(rows),
        "eligible": len(eligible),
        "unresolved": sum(row["status"] == "unresolved_project" for row in rows),
        "excluded": sum(row["status"] not in {"eligible", "unresolved_project"} for row in rows),
        "by_project": by_project,
        "issues": issues,
        "sessions": rows,
        "eligible_sessions": eligible,
    }


async def run_archive_distill_batch(
    *,
    control_root: Path,
    apply: bool,
    archive_dir: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    provider: Any | None = None,
    notes_dir: Path | None = None,
    now: datetime | None = None,
    verify: bool = False,
    batch_size: int | None = None,
    daily_limit: int | None = None,
    repair_only: bool = False,
) -> dict[str, Any]:
    """Inventory or process one configured batch through the canonical distill chain."""

    root = control_root.expanduser().resolve()
    config = load_merged_config(root)
    inventory = inventory_codex_archives(
        control_root=root,
        config=config,
        archive_dir=archive_dir,
    )
    current = now or _now()
    effective_batch_size = batch_size or config.archive_distill_batch_size
    effective_daily_limit = daily_limit or config.archive_distill_daily_limit
    if effective_batch_size < 1 or effective_daily_limit < 1:
        raise ValueError("archive distill limits must be positive")
    run_id = f"{current.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:12]}"
    day = current.date().isoformat()
    ledger = _read_ledger(data_dir, day)
    terminal_index = _read_terminal_index(data_dir)
    terminal_sessions = dict(terminal_index.get("sessions") or {})
    durable_attempts = dict(terminal_index.get("attempts") or {})
    inventory_dispositions = {
        str(row["session_id"]): {
            "session_id": str(row["session_id"]),
            "disposition": (
                "deferred_unresolved"
                if row["status"] == "unresolved_project"
                else "excluded"
            ),
            "reason": str(row["status"]),
            "cwd": str(row.get("cwd") or ""),
            "source_path": str(row.get("source_path") or ""),
            "observed_at": current.isoformat(),
        }
        for row in inventory["sessions"]
        if row["status"] != "eligible"
    }
    processed_today = set(str(item) for item in ledger.get("processed_session_ids", []))
    attempted_today = set(str(item) for item in ledger.get("attempted_session_ids", []))
    raw_attempt_counts = dict(ledger.get("attempt_counts") or {})
    attempt_counts = {
        session_id: max(1, int(raw_attempt_counts.get(session_id) or 1))
        for session_id in attempted_today
    }
    remaining_daily = max(0, effective_daily_limit - sum(attempt_counts.values()))
    eligible: list[dict[str, Any]] = []
    verified_terminal = 0
    quarantined_terminal = 0
    for row in inventory["eligible_sessions"]:
        session_id = str(row["session_id"])
        source_revision: str | None = None
        try:
            source_revision = _source_revision(Path(str(row["source_path"])))
        except OSError:
            pass
        entry = terminal_sessions.get(session_id)
        if entry is not None:
            candidate = {**row, "source_revision": source_revision}
            if _terminal_entry_matches(candidate, entry):
                if entry.get("disposition") == "verified_completed":
                    verified_terminal += 1
                else:
                    quarantined_terminal += 1
                continue
        durable_attempt = durable_attempts.get(session_id)
        if (
            isinstance(durable_attempt, dict)
            and durable_attempt.get("source_revision") == source_revision
        ):
            attempt_counts[session_id] = max(
                attempt_counts.get(session_id, 0),
                int(durable_attempt.get("count") or 0),
            )
        elif isinstance(durable_attempt, dict):
            attempt_counts[session_id] = 0
        if attempt_counts.get(session_id, 0) < 2:
            eligible.append(row)
    unresolved_count = int(inventory["unresolved"])
    excluded_count = int(inventory["excluded"])
    terminal_counts = {
        "verified_completed": verified_terminal,
        "quarantined": quarantined_terminal,
        "pending_eligible": len(eligible),
        "deferred_unresolved": unresolved_count,
        "excluded": excluded_count,
    }
    terminal_counts["total"] = sum(terminal_counts.values())
    terminal_counts["inventory_total"] = int(inventory["sessions_found"])
    terminal_counts["conserved"] = (
        terminal_counts["total"] == terminal_counts["inventory_total"]
    )
    lifecycle_counts = {
        "verified_completed": sum(
            entry.get("disposition") == "verified_completed"
            for entry in terminal_sessions.values()
            if isinstance(entry, dict)
        ),
        "quarantined": sum(
            entry.get("disposition") == "quarantined"
            for entry in terminal_sessions.values()
            if isinstance(entry, dict)
        ),
        "pending_eligible": len(eligible),
        "deferred_unresolved": unresolved_count,
        "excluded": excluded_count,
    }
    lifecycle_counts["source_deleted_after_verified"] = sum(
        session_id not in {str(row["session_id"]) for row in inventory["sessions"]}
        for session_id in terminal_sessions
    )
    lifecycle_counts["total"] = sum(
        lifecycle_counts[key]
        for key in (
            "verified_completed",
            "quarantined",
            "pending_eligible",
            "deferred_unresolved",
            "excluded",
        )
    )
    lifecycle_counts["conserved"] = (
        lifecycle_counts["total"]
        == len(terminal_sessions) + len(eligible) + unresolved_count + excluded_count
    )
    selected = eligible[: min(effective_batch_size, remaining_daily)]
    if repair_only:
        selected = []
    unresolved_resolution = {
        "count": inventory["unresolved"],
        "action": config.archive_distill_unresolved_project,
    }
    base = {
        "success": True,
        "run_id": run_id,
        "mode": "apply" if apply else "dry_run",
        "repair_only": repair_only,
        "enabled": config.archive_distill_enabled,
        "policy": {
            "batch_size": effective_batch_size,
            "daily_limit": effective_daily_limit,
            "remaining_daily": remaining_daily,
            "order": config.archive_distill_order,
            "project_scope": config.archive_distill_project_scope,
            "unresolved_project": config.archive_distill_unresolved_project,
            "require_answer_packet": config.archive_distill_require_answer_packet,
            "report_promotions": config.archive_distill_report_promotions,
            "warn_tokens": config.archive_distill_warn_tokens,
            "warn_seconds": config.archive_distill_warn_seconds,
        },
        "inventory": {
            key: inventory[key]
            for key in ("archive_dir", "sessions_found", "eligible", "unresolved", "excluded", "by_project", "issues")
        },
        "terminal": {
            **terminal_counts,
            "index": str(_terminal_index_path(data_dir)),
        },
        "lifecycle_terminal": lifecycle_counts,
        "selected": selected,
        "unresolved_resolution": unresolved_resolution,
        "outcomes": [],
    }
    if not apply:
        return base
    if not config.archive_distill_enabled:
        return {**base, "success": False, "error": "archive_distill is disabled"}
    if inventory["unresolved"] and config.archive_distill_unresolved_project == "error":
        return {
            **base,
            "success": False,
            "error": "unresolved archived sessions require project attribution",
        }

    lock = exclusive_maintenance_run(
        data_dir,
        run_id=run_id,
        operation="archive-distill",
    )
    try:
        lock.__enter__()
    except FileExistsError:
        return {
            **base,
            "success": False,
            "error": "another exclusive maintenance run is active",
        }
    backend = LocalMemoryBackend(data_dir)
    try:
        await backend.init()
        adapter = CodexArchiveAdapter(backend, archive_dir=archive_dir)
        resolved_notes_dir = notes_dir or Path.home() / ".codex" / "hm-distill" / "sessions"
        partial_repair = await _repair_partial_completed_receipts(
            backend,
            data_dir=data_dir,
            terminal_sessions=terminal_sessions,
            notes_dir=resolved_notes_dir,
        )
        selected_projects = sorted(
            {str(row.get("project_name") or "") for row in selected}
        )
        active_jobs: list[dict[str, str]] = []
        for project_name in selected_projects:
            backend.transcript_store.reconcile_distill_jobs(
                project_name=project_name
            )
            active_jobs.extend(
                _active_distill_worker_jobs(
                    backend,
                    project_name=project_name,
                )
            )
        if active_jobs:
            blocked = {
                **base,
                "success": False,
                "error": "active distill worker conflicts with exclusive archive batch",
                "concurrent_activity": active_jobs,
                "verification": {
                    "status": "blocked",
                    "reason": "active_distill_worker",
                },
                "finished_at": _now().isoformat(),
            }
            receipt_path = _write_json_atomic(
                _run_receipt_path(data_dir, run_id),
                blocked,
            )
            blocked["run_receipt"] = str(receipt_path)
            _write_json_atomic(receipt_path, blocked)
            return blocked
        outcomes: list[dict[str, Any]] = []
        attempted_ids: list[str] = []
        for row in selected:
            project_root = Path(str(row["project_root"])).resolve()
            project_name = str(row["project_name"])
            project_config = load_merged_config(project_root)
            outcome: dict[str, Any] = {
                "session_id": row["session_id"],
                "project_name": project_name,
                "project_root": str(project_root),
            }
            if not project_config.distill_autonomous_enabled:
                outcome.update(status="deferred", reason="project_autonomous_distill_not_authorized")
                outcomes.append(outcome)
                continue
            try:
                trivial_request = (
                    _trivial_archive_request(
                        adapter,
                        Path(str(row["source_path"])),
                    )
                    if provider is None
                    else None
                )
                synced = await adapter.sync_session(
                    Path(str(row["source_path"])),
                    str(row["session_id"]),
                    project_name,
                    project_root=project_root,
                )
                if synced.distill_job_id is None:
                    outcome.update(status="deferred", reason=synced.reason or "distill_job_not_created")
                    outcomes.append(outcome)
                    continue
                job = backend.transcript_store.get_distill_job(synced.distill_job_id)
                # Selecting an archive and actually attempting its semantic
                # job are deliberately different events.  A worker that has
                # asked for retry backoff must not consume the archive's
                # bounded attempt budget before it can be claimed again.
                if (
                    job is not None
                    and job.status == "retryable"
                    and job.retry_after is not None
                    and job.retry_after > current
                ):
                    outcome.update(
                        status="deferred",
                        reason="retry_backoff",
                        retry_after=job.retry_after.isoformat(),
                        distill_job_id=synced.distill_job_id,
                        source_revision=job.source_revision,
                    )
                    outcomes.append(outcome)
                    continue
                attempted_ids.append(str(row["session_id"]))
                if job is not None and job.status == "completed":
                    batch: dict[str, Any] = {"state": "succeeded", "outcomes": []}
                    job_outcome = {
                        "job_id": job.id,
                        "session_id": row["session_id"],
                        "status": "completed",
                        "note": materialize_session_note(
                            job,
                            notes_dir=resolved_notes_dir,
                        ),
                        "provider": {"total_tokens": 0, "duration_seconds": 0.0},
                    }
                    replay = "completed_job_reverified"
                else:
                    batch = await asyncio.to_thread(
                        run_autonomous_distill_batch,
                        backend,
                        project_name=project_name,
                        project_root=project_root,
                        config=project_config,
                        trigger_id=str(row["session_id"]),
                        client="codex-archive",
                        provider=(
                            _TrivialArchiveProvider(trivial_request)
                            if trivial_request is not None
                            else provider
                        ),
                        notes_dir=notes_dir,
                        max_jobs=1,
                        preferred_job_id=synced.distill_job_id,
                        launch_source="archive_batch",
                    )
                    job = backend.transcript_store.get_distill_job(synced.distill_job_id)
                    batch_outcomes: Any = batch.get("outcomes", [])
                    job_outcome = next(
                        (
                            item
                            for item in batch_outcomes
                            if isinstance(item, dict)
                            and item.get("job_id") == synced.distill_job_id
                        ),
                        {},
                    )
                    replay = "provider_executed"
                packet = dict((job.promotion_summary if job else {}).get("answer_packet") or {})
                tokens = int((job_outcome.get("provider") or {}).get("total_tokens") or 0)
                seconds = float((job_outcome.get("provider") or {}).get("duration_seconds") or 0.0)
                status = str(job_outcome.get("status") or batch.get("state") or "deferred")
                outcome.update(
                    status=status,
                    distill_job_id=synced.distill_job_id,
                    note=job_outcome.get("note"),
                    answer_packet=packet if config.archive_distill_require_answer_packet else None,
                    promoted_items=(packet.get("promoted_items", []) if config.archive_distill_report_promotions else []),
                    provider={"total_tokens": tokens, "duration_seconds": seconds},
                    warnings=[
                        code for code, hit in (
                            ("token_regression", tokens > config.archive_distill_warn_tokens),
                            ("latency_regression", seconds > config.archive_distill_warn_seconds),
                            ("answer_packet_missing", config.archive_distill_require_answer_packet and not packet),
                        ) if hit
                    ],
                    classification=(
                        "trivial_smoke" if trivial_request is not None else "semantic"
                    ),
                    execution=replay,
                    source_revision=(job.source_revision if job else synced.source.source_revision if synced.source else None),
                )
            except Exception as exc:  # noqa: BLE001 - one archive must not block later sessions.
                outcome.update(status="deferred", reason=f"{type(exc).__name__}: {exc}"[:512])
            outcomes.append(outcome)
        result = {
            **base,
            "success": all(item.get("status") == "completed" for item in outcomes) if outcomes else True,
            "outcomes": outcomes,
            "completed": sum(item.get("status") == "completed" for item in outcomes),
            "deferred": sum(item.get("status") != "completed" for item in outcomes),
        }
        verification = await _verify_archive_distill_run(backend, result=result)
        verified_ids = {
            str(item["session_id"])
            for item in verification["outcomes"]
            if item["status"] == "passed"
        }
        retryable_ids = {
            str(outcome.get("session_id") or "")
            for outcome, verified in zip(outcomes, verification["outcomes"], strict=True)
            if verified["status"] != "passed"
        }
        for session_id in attempted_ids:
            attempt_counts[session_id] = attempt_counts.get(session_id, 0) + 1
        ledger["day"] = day
        ledger["attempted_session_ids"] = sorted(attempted_today.union(attempted_ids))
        ledger["attempt_counts"] = dict(sorted(attempt_counts.items()))
        ledger["processed_session_ids"] = sorted(processed_today.union(verified_ids))
        ledger["retryable_session_ids"] = sorted(
            session_id
            for session_id in retryable_ids
            if attempt_counts.get(session_id, 0) < 2
        )
        ledger.setdefault("runs", []).append(
            {
                "run_id": run_id,
                "at": current.isoformat(),
                "selected": [row["session_id"] for row in selected],
                "verified": sorted(verified_ids),
            }
        )
        ledger_path = _write_ledger(data_dir, day, ledger)
        for outcome in outcomes:
            session_id = str(outcome.get("session_id") or "")
            if session_id not in verified_ids:
                continue
            terminal_sessions[session_id] = {
                "session_id": session_id,
                "source_revision": outcome.get("source_revision"),
                "project_name": outcome.get("project_name"),
                "project_root": outcome.get("project_root"),
                "distill_job_id": outcome.get("distill_job_id"),
                "disposition": "verified_completed",
                "verified_at": verification["verified_at"],
                "run_id": run_id,
            }
        verification_by_session = {
            str(item.get("session_id") or ""): item
            for item in verification["outcomes"]
        }
        outcomes_by_session = {
            str(item.get("session_id") or ""): item for item in outcomes
        }
        quarantined_ids = {
            session_id
            for session_id in retryable_ids
            if attempt_counts.get(session_id, 0) >= 2
        }
        selected_by_session = {
            str(item["session_id"]): item for item in selected
        }
        for session_id in attempted_ids:
            outcome = outcomes_by_session[session_id]
            row = selected_by_session[session_id]
            durable_attempts[session_id] = {
                "session_id": session_id,
                "source_revision": outcome.get("source_revision")
                or _source_revision(Path(str(row["source_path"]))),
                "count": attempt_counts[session_id],
                "last_status": outcome.get("status"),
                "last_reason": outcome.get("reason"),
                "last_run_id": run_id,
                "updated_at": verification["verified_at"],
            }
        for session_id in quarantined_ids:
            outcome = outcomes_by_session[session_id]
            row = next(
                item for item in selected if str(item["session_id"]) == session_id
            )
            terminal_sessions[session_id] = {
                "session_id": session_id,
                "source_revision": outcome.get("source_revision")
                or _source_revision(Path(str(row["source_path"]))),
                "project_name": outcome.get("project_name"),
                "project_root": outcome.get("project_root"),
                "distill_job_id": outcome.get("distill_job_id"),
                "disposition": "quarantined",
                "reason": outcome.get("reason") or outcome.get("status"),
                "failed_checks": verification_by_session[session_id].get(
                    "failed_checks", []
                ),
                "attempt_count": attempt_counts[session_id],
                "verified_at": verification["verified_at"],
                "run_id": run_id,
            }
        terminal_index = {
            "version": 1,
            "updated_at": _now().isoformat(),
            "sessions": terminal_sessions,
            "attempts": durable_attempts,
            "inventory_dispositions": inventory_dispositions,
        }
        terminal_path = _write_json_atomic(_terminal_index_path(data_dir), terminal_index)
        result["ledger"] = str(ledger_path)
        result["terminal_index"] = str(terminal_path)
        result["partial_receipt_repair"] = partial_repair
        result["verified_completed"] = len(verified_ids)
        result["quarantined"] = len(quarantined_ids)
        result["verification"] = verification if verify else {
            "status": verification["status"],
            "verified_at": verification["verified_at"],
            "reason": "automatic terminal admission verification",
        }
        result["success"] = bool(result["success"] and verification["status"] == "passed")
        result["finished_at"] = _now().isoformat()
        receipt_path = _write_json_atomic(
            _run_receipt_path(data_dir, run_id),
            result,
        )
        result["run_receipt"] = str(receipt_path)
        _write_json_atomic(receipt_path, result)
        return result
    finally:
        await backend.close()
        lock.__exit__(None, None, None)


async def _verify_archive_distill_run(
    backend: LocalMemoryBackend,
    *,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Read back one real run without reopening stores or loading embeddings."""

    receipts = {
        str(item.get("id")): item
        for item in backend.transcript_store.list_deletion_audit()
        if item.get("id")
    }
    policy = dict(result.get("policy") or {})
    require_answer_packet = bool(policy.get("require_answer_packet", True))
    verified_outcomes: list[dict[str, Any]] = []
    for outcome in result.get("outcomes", []):
        session_id = str(outcome.get("session_id") or "")
        project_name = str(outcome.get("project_name") or "")
        job_id = str(outcome.get("distill_job_id") or "")
        job = backend.transcript_store.get_distill_job(job_id) if job_id else None
        persisted_packet = dict(
            ((job.promotion_summary if job else {}).get("answer_packet") or {})
        )
        outcome_packet = dict(outcome.get("answer_packet") or {})
        cleanup = receipts.get(str(job.source_cleanup_receipt_id or "")) if job else None
        scope = dict((cleanup or {}).get("scope") or {})
        session_digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        source_path = Path(str(
            next(
                (
                    row.get("source_path")
                    for row in result.get("selected", [])
                    if row.get("session_id") == session_id
                ),
                "",
            )
        ))
        note_payload = dict(outcome.get("note") or {})
        note_path = Path(str(note_payload.get("path") or ""))
        note_text = ""
        try:
            note_text = note_path.read_text(encoding="utf-8")
        except OSError:
            pass
        promoted = list(persisted_packet.get("promoted_items") or [])
        cleanup_status = str(job.source_cleanup_status or "") if job else "missing"
        cleanup_verified = bool(
            cleanup_status == "deleted"
            and cleanup
            and (cleanup.get("verification") or {}).get("passed") is True
        )
        retrieval = await _verify_promoted_items(
            backend,
            project_name=project_name,
            job_id=job_id,
            promoted_items=promoted,
            allow_sanitized_project_retrieval=cleanup_verified,
        )
        identity_binding_valid = bool(
            job
            and (
                (
                    cleanup_status == "deleted"
                    and cleanup
                    and scope.get("session_id_sha256") == session_digest
                )
                or (
                    cleanup_status != "deleted"
                    and job.session_id == session_id
                    and job.project_root == str(outcome.get("project_root") or "")
                )
            )
        )
        cleanup_passed = bool(
            cleanup_status != "deleted"
            or (
                cleanup
                and (cleanup.get("verification") or {}).get("passed") is True
                and not source_path.exists()
                and scope.get("session_id_sha256") == session_digest
            )
        )
        checks = {
            "job_persisted": job is not None and job.status == "completed",
            "answer_packet_persisted": (
                (not require_answer_packet and not outcome_packet)
                or (
                    bool(persisted_packet)
                    and persisted_packet == outcome_packet
                )
            ),
            "project_binding_valid": bool(job and job.project_name == project_name),
            "privacy_identity_state_valid": bool(
                job
                and (
                    (
                        cleanup_status == "deleted"
                        and not job.session_id
                        and not job.project_root
                    )
                    or (
                        cleanup_status != "deleted"
                        and job.session_id == session_id
                        and job.project_root == str(outcome.get("project_root") or "")
                    )
                )
            ),
            "session_binding_valid": identity_binding_valid,
            "note_exists": note_path.is_file(),
            "note_meaningful": len(note_text.strip()) >= 200,
            "note_session_binding_valid": session_id in note_text,
            "note_job_binding_valid": job_id in note_text,
            "source_cleanup_verified": cleanup_passed,
            "retrieval_verified": retrieval["status"] in {"passed", "not_applicable"},
        }
        failed = [name for name, passed in checks.items() if not passed]
        verified_outcomes.append(
            {
                "session_id": session_id,
                "project_name": project_name,
                "status": "passed" if not failed else "partial",
                "checks": checks,
                "failed_checks": failed,
                "persisted_answer_packet": persisted_packet,
                "retrieval": retrieval,
                "source_cleanup": {
                    "status": cleanup_status,
                    "receipt_id": job.source_cleanup_receipt_id if job else None,
                    "receipt_status": (cleanup or {}).get("status"),
                    "native_source_exists_after": source_path.exists(),
                    "verification": (cleanup or {}).get("verification"),
                },
            }
        )
    status = (
        "passed"
        if all(item["status"] == "passed" for item in verified_outcomes)
        else "partial"
    )
    return {
        "status": status,
        "verified_at": _now().isoformat(),
        "outcomes": verified_outcomes,
    }


async def _verify_promoted_items(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    job_id: str,
    promoted_items: list[dict[str, Any]],
    allow_sanitized_project_retrieval: bool = False,
) -> dict[str, Any]:
    if not promoted_items:
        return {
            "status": "not_applicable",
            "reason": "no_promoted_items",
            "items": [],
        }
    job = backend.transcript_store.get_distill_job(job_id) if job_id else None
    candidate_ids = set(job.output_candidate_ids if job else [])
    knowledge_store = backend.structured_store.knowledge_store
    # Current ``knowledge_entries`` are the post-job authority. Candidate,
    # evidence, and proposed-decision workspaces are deliberately cleaned after
    # the SQLite commit, Note, Packet, and receipt become durable, so a terminal
    # verifier must not require those temporary files to remain. The job-bound
    # Answer Packet supplies the exact claims; normal current-knowledge readback
    # proves that each claim is now usable.
    separated_truth = await knowledge_store.list_entries(project_name)
    truth_candidates: list[Any] = []
    if not separated_truth:
        for candidate_id in candidate_ids:
            legacy_candidate: Any = await backend.structured_store.get_memory_entry(
                candidate_id
            )
            if legacy_candidate is None:
                legacy_candidate = await backend.structured_store.get_rule_candidate(
                    candidate_id
                )
            if legacy_candidate is None:
                legacy_candidate = await backend.structured_store.get_relation_fact(
                    candidate_id
                )
            if (
                legacy_candidate is not None
                and legacy_candidate.project_name == project_name
                and legacy_candidate.distill_job_id == job_id
                and legacy_candidate.status in TRUTH_LAYER_STATUSES
            ):
                truth_candidates.append(legacy_candidate)
    checks: list[dict[str, Any]] = []
    for item in promoted_items:
        fact = str(item.get("fact") or "").strip()
        kind = str(item.get("kind") or "")
        if separated_truth:
            hit = any(entry.statement.strip() == fact for entry in separated_truth)
        elif kind == "rule":
            hit = any(
                hasattr(candidate, "pattern") and candidate.pattern.strip() == fact
                for candidate in truth_candidates
            )
        elif kind == "relation":
            hit = any(
                hasattr(candidate, "source_entity")
                and f"{candidate.source_entity} {candidate.relation_type} "
                f"{candidate.target_entity}".strip() == fact
                for candidate in truth_candidates
            )
        else:
            hit = any(
                hasattr(candidate, "content") and candidate.content.strip() == fact
                for candidate in truth_candidates
            )
        retrieval_mode = "current_project_knowledge"
        if not hit and allow_sanitized_project_retrieval:
            retrieval_mode = "legacy_project_truth"
            knowledge_entries = await knowledge_store.list_entries(project_name)
            if any(entry.statement.strip() == fact for entry in knowledge_entries):
                hit = True
            elif kind == "rule":
                candidates = await backend.structured_store.list_rule_candidates(
                    project_name
                )
                hit = any(
                    candidate.status in TRUTH_LAYER_STATUSES
                    and candidate.pattern.strip() == fact
                    for candidate in candidates
                )
            elif kind == "relation":
                relations = await backend.structured_store.list_relation_facts(
                    project_name,
                    limit=10_000,
                    include_provisional=True,
                )
                hit = any(
                    relation.status in TRUTH_LAYER_STATUSES
                    and f"{relation.source_entity} {relation.relation_type} "
                    f"{relation.target_entity}".strip() == fact
                    for relation in relations
                )
            else:
                matches = await backend.structured_store.search_memory_entries(
                    fact,
                    project_name=project_name,
                    mode="fts",
                    limit=20,
                    include_provisional=True,
                    deep_recall=True,
                )
                hit = any(entry.content.strip() == fact for entry in matches)
        checks.append(
            {
                "title": item.get("title"),
                "fact": fact,
                "kind": kind,
                "category": item.get("category"),
                "retrieved": hit,
                "retrieval_mode": retrieval_mode,
            }
        )
    return {
        "status": "passed" if all(item["retrieved"] for item in checks) else "partial",
        "reason": None,
        "items": checks,
    }


def print_archive_distill_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    inventory = result["inventory"]
    print(f"Archive distill: {result['mode']} ({'enabled' if result['enabled'] else 'disabled'})")
    print(
        f"Found {inventory['sessions_found']} | eligible {inventory['eligible']} | "
        f"unresolved {inventory['unresolved']} | selected {len(result['selected'])}"
    )
    unresolved = result.get("unresolved_resolution") or {}
    if unresolved.get("count"):
        print(
            "Unresolved project policy: "
            f"{unresolved['action']} ({unresolved['count']} session(s))"
        )
    for item in result.get("outcomes", []):
        print(f"\nSession: {item['session_id']} ({item['project_name']})")
        print(f"Status: {item['status']}")
        packet = item.get("answer_packet") or {}
        if packet:
            answer_status = {
                "ANSWERED": "verified",
                "PARTIAL": "evidence incomplete",
                "UNANSWERED": "insufficient evidence",
                "CONTRADICTED": "evidence contradicted",
                "STALE": "evidence stale",
                "NOT_APPLICABLE": "no durable memory needed",
            }.get(str(packet.get("answer_status") or ""), "insufficient evidence")
            memory_status = {
                "promoted": "saved",
                "partial": "partially saved",
                "not_promoted": "not saved",
            }.get(str(packet.get("promotion_status") or ""), "not saved")
            print("Memory verification")
            print(f"Evidence: {answer_status}")
            print(f"Conclusion: {packet.get('core_conclusion')}")
            print(f"Memory: {memory_status}")
            for promoted in item.get("promoted_items", []):
                print(f"- {promoted.get('title')}: {promoted.get('fact')}")
        note = item.get("note") or {}
        if note.get("path"):
            print(f"Note: {note['path']}")
        if item.get("warnings"):
            print("Warnings: " + ", ".join(item["warnings"]))
    if result.get("error"):
        print(f"Error: {result['error']}")


__all__ = ["inventory_codex_archives", "print_archive_distill_result", "run_archive_distill_batch"]
