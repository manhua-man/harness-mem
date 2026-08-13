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
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.commands.support import DEFAULT_DATA_DIR, workspace_root_from_path
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.maintenance_lock import exclusive_maintenance_run
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve(strict=False)))


def _detect_project_root(cwd: str) -> Path | None:
    if not cwd:
        return None
    candidate = Path(cwd).expanduser()
    if not candidate.is_dir():
        return None
    return workspace_root_from_path(candidate).resolve()


def _allowed(root: Path, allowed_roots: tuple[str, ...]) -> bool:
    if not allowed_roots:
        return True
    normalized = _normalized_path(root)
    return any(normalized == _normalized_path(Path(item)) for item in allowed_roots)


def _ledger_path(data_dir: Path, day: str) -> Path:
    return data_dir / "archive_distill" / "daily" / f"{day}.json"


def _run_receipt_path(data_dir: Path, run_id: str) -> Path:
    return data_dir / "archive_distill" / "runs" / f"{run_id}.json"


def _read_ledger(data_dir: Path, day: str) -> dict[str, Any]:
    path = _ledger_path(data_dir, day)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"day": day, "processed_session_ids": [], "runs": []}
    return payload if isinstance(payload, dict) else {"day": day, "processed_session_ids": [], "runs": []}


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
        elif not _allowed(detected, config.archive_distill_allowed_project_roots):
            status = "project_not_allowed"
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
    run_id = f"{current.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:12]}"
    day = current.date().isoformat()
    ledger = _read_ledger(data_dir, day)
    processed_today = set(str(item) for item in ledger.get("processed_session_ids", []))
    remaining_daily = max(0, config.archive_distill_daily_limit - len(processed_today))
    eligible = [
        row for row in inventory["eligible_sessions"]
        if row["session_id"] not in processed_today
    ]
    selected = eligible[: min(config.archive_distill_batch_size, remaining_daily)]
    unresolved_resolution = {
        "count": inventory["unresolved"],
        "action": config.archive_distill_unresolved_project,
    }
    base = {
        "success": True,
        "run_id": run_id,
        "mode": "apply" if apply else "dry_run",
        "enabled": config.archive_distill_enabled,
        "policy": {
            "batch_size": config.archive_distill_batch_size,
            "daily_limit": config.archive_distill_daily_limit,
            "remaining_daily": remaining_daily,
            "order": config.archive_distill_order,
            "project_scope": config.archive_distill_project_scope,
            "unresolved_project": config.archive_distill_unresolved_project,
            "allowed_project_roots": list(config.archive_distill_allowed_project_roots),
            "require_answer_packet": config.archive_distill_require_answer_packet,
            "report_promotions": config.archive_distill_report_promotions,
            "warn_tokens": config.archive_distill_warn_tokens,
            "warn_seconds": config.archive_distill_warn_seconds,
        },
        "inventory": {
            key: inventory[key]
            for key in ("archive_dir", "sessions_found", "eligible", "unresolved", "excluded", "by_project", "issues")
        },
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
        completed_ids: list[str] = []
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
                job_outcome: dict[str, Any] = next(
                    (item for item in batch.get("outcomes", []) if item.get("job_id") == synced.distill_job_id),
                    {},
                )
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
                )
                if status == "completed" and (packet or not config.archive_distill_require_answer_packet):
                    completed_ids.append(str(row["session_id"]))
            except Exception as exc:  # noqa: BLE001 - one archive must not block later sessions.
                outcome.update(status="deferred", reason=f"{type(exc).__name__}: {exc}"[:512])
            outcomes.append(outcome)
        ledger["day"] = day
        ledger["processed_session_ids"] = sorted(processed_today.union(completed_ids))
        ledger.setdefault("runs", []).append(
            {
                "run_id": run_id,
                "at": current.isoformat(),
                "selected": [row["session_id"] for row in selected],
                "completed": completed_ids,
            }
        )
        ledger_path = _write_ledger(data_dir, day, ledger)
        result = {
            **base,
            "success": all(item.get("status") == "completed" for item in outcomes) if outcomes else True,
            "outcomes": outcomes,
            "ledger": str(ledger_path),
            "completed": len(completed_ids),
            "deferred": sum(item.get("status") != "completed" for item in outcomes),
        }
        if verify:
            result["verification"] = await _verify_archive_distill_run(
                backend,
                result=result,
                ledger=ledger,
            )
            result["success"] = bool(
                result["success"]
                and result["verification"]["status"] == "passed"
            )
        else:
            result["verification"] = {
                "status": "not_run",
                "reason": "--verify was not requested",
            }
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
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Read back one real run without reopening stores or loading embeddings."""

    processed = set(map(str, ledger.get("processed_session_ids") or []))
    receipts = {
        str(item.get("id")): item
        for item in backend.transcript_store.list_deletion_audit()
        if item.get("id")
    }
    verified_outcomes: list[dict[str, Any]] = []
    for outcome in result.get("outcomes", []):
        session_id = str(outcome.get("session_id") or "")
        project_name = str(outcome.get("project_name") or "")
        job_id = str(outcome.get("distill_job_id") or "")
        job = backend.transcript_store.get_distill_job(job_id) if job_id else None
        persisted_packet = dict(
            ((job.promotion_summary if job else {}).get("answer_packet") or {})
        )
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
        retrieval = await _verify_promoted_items(
            backend,
            project_name=project_name,
            promoted_items=promoted,
        )
        cleanup_status = str(job.source_cleanup_status or "") if job else "missing"
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
            "answer_packet_persisted": bool(persisted_packet)
            and persisted_packet == dict(outcome.get("answer_packet") or {}),
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
            "ledger_recorded": session_id in processed,
            "replay_skipped": session_id in processed,
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
    promoted_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not promoted_items:
        return {
            "status": "not_applicable",
            "reason": "no_promoted_items",
            "items": [],
        }
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    relations = await backend.structured_store.list_relation_facts(
        project_name,
        limit=10_000,
    )
    checks: list[dict[str, Any]] = []
    for item in promoted_items:
        fact = str(item.get("fact") or "").strip()
        kind = str(item.get("kind") or "")
        if kind == "rule":
            hit = any(rule.pattern.strip() == fact for rule in rules)
        elif kind == "relation":
            hit = any(
                f"{relation.source_entity} {relation.relation_type} "
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
            print("Answer Packet")
            print(f"Verification: {packet.get('answer_status')}")
            print(f"Conclusion: {packet.get('core_conclusion')}")
            print(f"Promotion: {packet.get('promotion_status')}")
            for promoted in item.get("promoted_items", []):
                print(f"- {promoted.get('title')}: {promoted.get('fact')} ({promoted.get('kind')} / {promoted.get('category')})")
        note = item.get("note") or {}
        if note.get("path"):
            print(f"Note: {note['path']}")
        if item.get("warnings"):
            print("Warnings: " + ", ".join(item["warnings"]))
    if result.get("error"):
        print(f"Error: {result['error']}")


__all__ = ["inventory_codex_archives", "print_archive_distill_result", "run_archive_distill_batch"]
