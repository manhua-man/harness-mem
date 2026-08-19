"""Read-only, user-outcome probes for the project verification contract."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from harness_mem.commands.support import DEFAULT_DATA_DIR
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.hook_receipts import (
    hook_configuration_fingerprint,
    inspect_hook_execution_receipt,
    read_hook_execution_receipt,
)
from harness_mem.hook_runtime import collect_hook_file_statuses
from harness_mem.autonomous.worker import (
    autonomous_config_fingerprint,
    autonomous_runtime_fingerprint,
    read_autonomous_receipt,
)
from harness_mem.config.merge import load_merged_config
from harness_mem.session_notes import (
    existing_session_note_path,
    is_meaningful_session_summary,
)


DEFAULT_RECENT_DAYS = 7
MIN_NOTE_CHARS = 200
OUTCOME_SECTIONS = ("hooks", "dream", "distill", "autonomous", "retrieval")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _identity_digest(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def inspect_hook_outcome(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
) -> dict[str, Any]:
    """Prove current native hook configuration has fresh paired receipts."""

    files = collect_hook_file_statuses(project_root, client=client)
    actions: dict[str, dict[str, Any]] = {}
    for label, action in (
        ("wake_start", "wake-start"),
        ("post_turn_maintenance", "post-turn-maintenance"),
    ):
        health = inspect_hook_execution_receipt(
            data_dir,
            project_root=project_root,
            client=client,
            action=action,
        )
        receipt = read_hook_execution_receipt(
            data_dir,
            project_root=project_root,
            client=client,
            action=action,
        )
        actions[label] = {
            **health,
            "trigger_id": receipt.get("trigger_id") if receipt else None,
            "source": receipt.get("source") if receipt else None,
        }
    installed = sum(1 for item in files if item.exists and item.configured)
    both_fresh = bool(actions) and all(
        item["freshness"] == "fresh" for item in actions.values()
    )
    actions_verified = bool(actions) and all(
        item["freshness"] == "fresh" and item.get("config_match") is True
        for item in actions.values()
    )
    wake_trigger = actions["wake_start"].get("trigger_id")
    maintenance_trigger = actions["post_turn_maintenance"].get("trigger_id")
    if client == "codex":
        pair_status = (
            "matched"
            if both_fresh and wake_trigger and wake_trigger == maintenance_trigger
            else "mismatched"
            if both_fresh and wake_trigger and maintenance_trigger
            else "incomplete"
        )
    else:
        pair_status = "not_required"
    return {
        "client": client,
        "installed": installed,
        "expected": len(files),
        "configuration_complete": bool(files) and installed == len(files),
        "actions": actions,
        "wake_verified": actions["wake_start"]["freshness"] == "fresh",
        "maintenance_verified": actions["post_turn_maintenance"]["freshness"]
        == "fresh",
        "actions_verified": actions_verified,
        "session_pair_status": pair_status,
        "lifecycle_verified": both_fresh and pair_status in {"matched", "not_required"},
    }


def inspect_distill_notes(
    jobs: Iterable[Any],
    *,
    notes_dir: Path,
    since: datetime,
) -> dict[str, Any]:
    """Match each recently completed source session to a meaningful Note."""

    recent_jobs = [
        job
        for job in jobs
        if job.status == "completed"
        and (completed := _parse_datetime(job.completed_at)) is not None
        and completed >= since
    ]
    latest_by_session: dict[str, Any] = {}
    for job in recent_jobs:
        note_path, recovered_session_id = existing_session_note_path(notes_dir, job)
        session_key = str(job.session_id or recovered_session_id or f"job:{job.id}")
        current = latest_by_session.get(session_key)
        if current is None or (_parse_datetime(job.completed_at) or since) > (
            _parse_datetime(current.completed_at) or since
        ):
            latest_by_session[session_key] = job

    note_records: list[dict[str, Any]] = []
    summaries_meaningful = 0
    summaries_unavailable = 0
    notes_unavailable = 0
    for session_id, job in sorted(latest_by_session.items()):
        immutable_path, recovered_session_id = existing_session_note_path(notes_dir, job)
        resolved_session_id = str(job.session_id or recovered_session_id or "")
        legacy_path = notes_dir / f"{resolved_session_id}.md"
        path = immutable_path or legacy_path
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        summary = str((job.semantic_review or {}).get("session_summary") or "").strip()
        summary_meaningful = is_meaningful_session_summary(summary)
        summary_unavailable = bool(
            not summary_meaningful
            and (job.semantic_review or {}).get("historical_summary_status")
            == "unavailable"
            and (job.semantic_review or {}).get("historical_summary_reason")
        )
        lowered = content.lower()
        topic_present = any(
            marker in lowered for marker in ("会话主题", "## scope", "# session ")
        )
        outcome_present = any(
            marker in lowered
            for marker in (
                "最终结果",
                "final outcome",
                "记忆治理结果",
                "review disposition",
            )
        )
        meaningful = (
            path.is_file()
            and len(content.strip()) >= MIN_NOTE_CHARS
            and bool(resolved_session_id)
            and resolved_session_id in content
            and topic_present
            and outcome_present
        )
        note_unavailable = bool(
            not meaningful
            and not resolved_session_id
            and (job.semantic_review or {}).get("evidence_state") == "source_pruned"
        )
        summaries_meaningful += int(summary_meaningful)
        summaries_unavailable += int(summary_unavailable)
        notes_unavailable += int(note_unavailable)
        note_records.append(
            {
                "session_id": resolved_session_id,
                "job_id": job.id,
                "completed_at": _iso(_parse_datetime(job.completed_at)),
                "path": str(path),
                "exists": path.is_file(),
                "chars": len(content),
                "meaningful": meaningful,
                "note_unavailable": note_unavailable,
                "note_unavailable_reason": (
                    "session_identity_and_immutable_note_missing_after_source_pruned"
                    if note_unavailable
                    else None
                ),
                "topic_present": topic_present,
                "outcome_present": outcome_present,
                "semantic_summary_present": summary_meaningful,
                "semantic_summary_unavailable": summary_unavailable,
                "semantic_summary_unavailable_reason": (
                    (job.semantic_review or {}).get("historical_summary_reason")
                    if summary_unavailable
                    else None
                ),
            }
        )
    expected = len(note_records)
    meaningful_count = sum(int(item["meaningful"]) for item in note_records)
    return {
        "since": since.isoformat(),
        "recent_completed_count": len(recent_jobs),
        "unique_completed_sessions": expected,
        "notes_expected": expected,
        "notes_meaningful": meaningful_count,
        "notes_unavailable": notes_unavailable,
        "note_audit_covered": meaningful_count + notes_unavailable,
        "note_coverage": meaningful_count / expected if expected else 0.0,
        "note_coverage_complete": expected > 0
        and meaningful_count + notes_unavailable == expected,
        "semantic_summaries_meaningful": summaries_meaningful,
        "semantic_summaries_unavailable": summaries_unavailable,
        "semantic_summary_audit_covered": summaries_meaningful + summaries_unavailable,
        "semantic_summary_coverage_complete": expected > 0
        and summaries_meaningful + summaries_unavailable == expected,
        "notes": note_records,
    }


def inspect_autonomous_outcome(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    jobs: Iterable[Any],
) -> dict[str, Any]:
    """Verify a background semantic completion against its job and Note."""

    receipt = read_autonomous_receipt(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    if receipt is None:
        return {
            "receipt_exists": False,
            "lifecycle_verified": False,
            "provider_isolated": False,
            "note_verified": False,
            "last_semantic_success_at": None,
        }
    try:
        merged_config = load_merged_config(project_root)
        authorized = merged_config.distill_autonomous_enabled
        current_config_fingerprint = autonomous_config_fingerprint(merged_config)
    except Exception:  # noqa: BLE001 - outcome remains inspectable on bad config.
        authorized = False
        current_config_fingerprint = None
    current_runtime_fingerprint = autonomous_runtime_fingerprint()
    raw_verified = receipt.get("last_verified_completion")
    verified_completion: dict[str, Any] | None = (
        raw_verified if isinstance(raw_verified, dict) else None
    )
    evidence = verified_completion or receipt
    evidence_client = str(evidence.get("client") or "codex")
    hook_receipt = read_hook_execution_receipt(
        data_dir,
        project_root=project_root,
        client=evidence_client,
        action="post-turn-maintenance",
    )
    latest_trigger_matches_hook = bool(
        hook_receipt
        and evidence.get("trigger_id")
        and evidence.get("trigger_id") == hook_receipt.get("trigger_id")
    )
    durable_hook_binding = bool(
        evidence.get("hook_launch_verified") is True
        and evidence.get("trigger_id")
        and evidence.get("hook_config_fingerprint")
        == hook_configuration_fingerprint(
            project_root,
            client=evidence_client,
        )
    )
    trigger_matches_hook = durable_hook_binding or latest_trigger_matches_hook
    dispatch_generation_bound = bool(evidence.get("dispatch_generation"))
    job_list = list(jobs)
    trigger_id = str(evidence.get("trigger_id") or "")
    if verified_completion is not None:
        trigger_record: dict[str, Any] | None = verified_completion
    else:
        raw_batch = receipt.get("batch")
        batch: dict[str, Any] = raw_batch if isinstance(raw_batch, dict) else {}
        batch_jobs = [
            item for item in batch.get("jobs", []) if isinstance(item, dict)
        ]
        trigger_record = next(
            (
                item
                for item in batch_jobs
                if str(item.get("session_id") or "") == trigger_id
                and item.get("status") == "completed"
            ),
            None,
        )
    trigger_job_id = str((trigger_record or {}).get("job_id") or "")
    trigger_job = next(
        (
            item
            for item in job_list
            if item.id == trigger_job_id
        ),
        None,
    )
    record = trigger_record or {}
    raw_note = record.get("note")
    note: dict[str, Any] = raw_note if isinstance(raw_note, dict) else {}
    note_path = Path(str(note.get("path") or "")) if note.get("path") else None
    try:
        note_content = note_path.read_text(encoding="utf-8") if note_path else ""
    except OSError:
        note_content = ""
    note_hash = (
        hashlib.sha256(note_content.encode("utf-8")).hexdigest()
        if note_content
        else None
    )
    note_verified = bool(
        note_path
        and note_path.is_file()
        and len(note_content.strip()) >= MIN_NOTE_CHARS
        and trigger_job is not None
        and note_path.name == f"{trigger_id}.md"
        and trigger_id in note_content
        and trigger_job.id in note_content
        and note_hash == note.get("sha256")
        and note.get("job_binding_valid") is True
        and note.get("meaningful") is True
    )
    raw_provider = record.get("provider")
    provider: dict[str, Any] = (
        raw_provider if isinstance(raw_provider, dict) else {}
    )
    input_tokens = provider.get("input_tokens")
    output_tokens = provider.get("output_tokens")
    total_tokens = provider.get("total_tokens")
    duration_seconds = provider.get("duration_seconds")
    provider_isolated = bool(
        provider.get("name") in {"codex_exec", "responses_api"}
        and provider.get("schema_valid") is True
        and provider.get("sandbox") in {"read-only", "no-tools"}
        and provider.get("ephemeral") is True
        and provider.get("cwd_isolated") is True
        and provider.get("hooks_disabled") is True
        and provider.get("plugins_disabled") is True
        and provider.get("mcp_disabled") is True
        and provider.get("rules_ignored") is True
        and provider.get("config_isolated") is True
        and int(evidence.get("hook_reentry_count") or 0) == 0
    )
    provider_metrics_bound = bool(
        isinstance(input_tokens, int)
        and input_tokens > 0
        and isinstance(output_tokens, int)
        and output_tokens > 0
        and isinstance(total_tokens, int)
        and total_tokens > 0
        and isinstance(duration_seconds, (int, float))
        and duration_seconds > 0
        and provider.get("job_id") == trigger_job_id
        and provider.get("session_id_sha256") == _identity_digest(trigger_id)
        and provider.get("trigger_id_sha256") == _identity_digest(trigger_id)
        and bool(provider.get("source_revision"))
        and bool(provider.get("project_root_sha256"))
    )
    job_completed = bool(
        trigger_job is not None
        and trigger_job.status == "completed"
        and trigger_job.review_execution_source == "autonomous_worker"
        and trigger_job.completed_at is not None
    )
    success_at = record.get("last_semantic_success_at")
    completed_at = record.get("last_job_completed_at")
    job_time = _parse_datetime(trigger_job.completed_at) if trigger_job else None
    recorded_job_time = _parse_datetime(completed_at)
    batch_binding_valid = bool(
        int(receipt.get("schema_version") or 0) >= 2
        and trigger_record is not None
        and trigger_job is not None
        and trigger_job_id == trigger_job.id
        and str(trigger_record.get("session_id") or "") == trigger_id
        and job_time is not None
        and recorded_job_time == job_time
    )
    evidence_runtime = str(evidence.get("runtime_fingerprint") or "")
    receipt_runtime = str(receipt.get("runtime_fingerprint") or "")
    runtime_current = bool(
        current_runtime_fingerprint
        and (
            evidence_runtime == current_runtime_fingerprint
            or receipt_runtime == current_runtime_fingerprint
        )
    )
    config_current = bool(
        current_config_fingerprint
        and evidence.get("config_fingerprint") == current_config_fingerprint
    )
    return {
        "receipt_exists": True,
        "authorized": authorized,
        "state": receipt.get("state"),
        "execution_source": evidence.get("execution_source"),
        "trigger_id": evidence.get("trigger_id"),
        "latest_attempt_trigger_id": receipt.get("trigger_id"),
        "verified_completion_preserved": verified_completion is not None,
        "trigger_matches_hook": trigger_matches_hook,
        "dispatch_generation_bound": dispatch_generation_bound,
        "durable_hook_binding": durable_hook_binding,
        "latest_trigger_matches_hook": latest_trigger_matches_hook,
        "job_id": trigger_job_id or None,
        "session_id": trigger_id or None,
        "batch_binding_valid": batch_binding_valid,
        "trigger_session_completed": trigger_job is not None,
        "job_completed": job_completed,
        "last_semantic_success_at": success_at,
        "last_job_completed_at": completed_at,
        "last_note_materialized_at": record.get("last_note_materialized_at"),
        "runtime_current": runtime_current,
        "config_current": config_current,
        "provider": provider,
        "provider_isolated": provider_isolated,
        "provider_metrics_bound": provider_metrics_bound,
        "note": {
            **note,
            "path": str(note_path) if note_path is not None else None,
            "receipt_sha256": note.get("sha256"),
            "sha256": note_hash,
            "actual_sha256": note_hash,
            "verified": note_verified,
        },
        "note_verified": note_verified,
        "lifecycle_verified": bool(
            success_at
            and evidence.get("execution_source") == "autonomous_worker"
            and trigger_matches_hook
            and dispatch_generation_bound
            and job_completed
            and trigger_job is not None
            and batch_binding_valid
            and runtime_current
            and config_current
            and provider_isolated
            and provider_metrics_bound
            and note_verified
        ),
    }


def _query_candidates(content: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{4,}", content)
    candidates = [
        word
        for word in words
        if word.lower() not in {"about", "which", "their", "there", "current"}
    ]
    if candidates:
        return candidates[:5]
    compact = re.sub(r"\s+", "", content)
    return [compact[:8]] if len(compact) >= 4 else []


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _read_distill_jobs(data_dir: Path, project_name: str) -> list[SessionDistillJob]:
    with closing(
        _read_only_connection(data_dir / "transcript_ledger.sqlite")
    ) as connection:
        rows = connection.execute(
            """
            SELECT data FROM distill_jobs
            WHERE project_name = ? ORDER BY updated_at DESC LIMIT 10000
            """,
            (project_name,),
        ).fetchall()
    return [SessionDistillJob.from_dict(json.loads(row["data"])) for row in rows]


def inspect_dream_outcome(
    data_dir: Path,
    project_name: str,
    *,
    recent_cutoff: datetime,
) -> dict[str, Any]:
    with closing(
        _read_only_connection(data_dir / "structured_index.sqlite")
    ) as connection:
        rows = connection.execute(
            """
            SELECT id, status, started_at, completed_at, trigger_source
            FROM dream_runs WHERE project_name = ?
            ORDER BY started_at DESC LIMIT 50
            """,
            (project_name,),
        ).fetchall()
    successful = [
        row for row in rows if row["status"] == "completed" and row["completed_at"]
    ]
    last_success = successful[0] if successful else None
    last = rows[0] if rows else None
    return {
        "run_count": len(rows),
        "successful_run_count": len(successful),
        "last_status": last["status"] if last else None,
        "last_run_at": (last["completed_at"] or last["started_at"]) if last else None,
        "last_successful_run_at": last_success["completed_at"]
        if last_success
        else None,
        "success_within_window": bool(
            last_success
            and (_parse_datetime(last_success["completed_at"]) or recent_cutoff)
            >= recent_cutoff
        ),
    }


def inspect_retrieval_outcome(data_dir: Path, project_name: str) -> dict[str, Any]:
    """Search a readable truth through the persisted FTS consumer read model."""

    now = datetime.now(timezone.utc).isoformat()
    with closing(
        _read_only_connection(data_dir / "structured_index.sqlite")
    ) as connection:
        entries = connection.execute(
            """
            SELECT id, content FROM memory_entries
            WHERE project_name = ?
              AND COALESCE(compacted, 0) = 0
              AND status IN ('auto_confirmed', 'user_confirmed')
              AND (valid_to IS NULL OR valid_to = '' OR valid_to > ?)
              AND (superseded_by IS NULL OR superseded_by = '' OR superseded_by = '[]')
            ORDER BY created_at DESC LIMIT 20
            """,
            (project_name, now),
        ).fetchall()
        attempts: list[dict[str, Any]] = []
        for entry in entries:
            for query in _query_candidates(str(entry["content"])):
                fts_query = '"' + query.replace('"', '""') + '"'
                try:
                    matches = connection.execute(
                        """
                        SELECT memory_entries.id
                        FROM memory_entries_fts
                        JOIN memory_entries
                          ON memory_entries.rowid = memory_entries_fts.rowid
                        WHERE memory_entries_fts MATCH ?
                          AND memory_entries.project_name = ?
                          AND COALESCE(memory_entries.compacted, 0) = 0
                          AND memory_entries.status IN ('auto_confirmed', 'user_confirmed')
                        LIMIT 20
                        """,
                        (fts_query, project_name),
                    ).fetchall()
                except sqlite3.Error as exc:
                    attempts.append(
                        {"entry_id": entry["id"], "query": query, "error": str(exc)}
                    )
                    continue
                ids = [row["id"] for row in matches]
                hit = entry["id"] in ids
                attempts.append(
                    {
                        "entry_id": entry["id"],
                        "query": query,
                        "result_count": len(ids),
                        "target_returned": hit,
                    }
                )
                if hit:
                    return {
                        "readable_truth_count": len(entries),
                        "probe_attempted": True,
                        "probe_hit": True,
                        "target_id": entry["id"],
                        "query": query,
                        "attempts": attempts,
                    }
    return {
        "readable_truth_count": len(entries),
        "probe_attempted": bool(attempts),
        "probe_hit": False,
        "target_id": None,
        "query": None,
        "attempts": attempts,
    }


def collect_outcomes(
    *,
    project_name: str,
    project_root: Path,
    client: str,
    data_dir: Path,
    notes_dir: Path,
    recent_days: int,
    sections: Iterable[str] | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    requested = set(sections or OUTCOME_SECTIONS)
    recent_cutoff = now - timedelta(days=recent_days)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "project": project_name,
        "project_root": str(project_root),
        "observed_at": now.isoformat(),
        "window_days": recent_days,
    }
    jobs: list[SessionDistillJob] | None = None

    if "hooks" in requested:
        payload["hooks"] = inspect_hook_outcome(
            data_dir,
            project_root=project_root,
            client=client,
        )
    if "dream" in requested:
        payload["dream"] = inspect_dream_outcome(
            data_dir,
            project_name,
            recent_cutoff=recent_cutoff,
        )
    if requested & {"distill", "autonomous"}:
        jobs = _read_distill_jobs(data_dir, project_name)
    if "distill" in requested:
        distill = inspect_distill_notes(
            jobs or [],
            notes_dir=notes_dir,
            since=recent_cutoff,
        )
        if compact:
            distill = {key: value for key, value in distill.items() if key != "notes"}
        payload["distill"] = distill
    if "autonomous" in requested:
        payload["autonomous"] = inspect_autonomous_outcome(
            data_dir,
            project_name=project_name,
            project_root=project_root,
            jobs=jobs or [],
        )
    if "retrieval" in requested:
        retrieval = inspect_retrieval_outcome(data_dir, project_name)
        if compact:
            retrieval = {
                key: value for key, value in retrieval.items() if key != "attempts"
            }
        payload["retrieval"] = retrieval
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--client", default="codex")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--notes-dir",
        type=Path,
        default=Path.home() / ".codex" / "hm-distill" / "sessions",
    )
    parser.add_argument("--recent-days", type=int, default=DEFAULT_RECENT_DAYS)
    parser.add_argument(
        "--section",
        action="append",
        choices=OUTCOME_SECTIONS,
        help="Emit and evaluate only this outcome section; repeat to select several.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Omit verbose per-Note and retrieval-attempt detail arrays.",
    )
    args = parser.parse_args(argv)
    if args.recent_days < 1:
        parser.error("--recent-days must be positive")
    project_root = args.project_root.expanduser().resolve()
    payload = collect_outcomes(
        project_name=args.project,
        project_root=project_root,
        client=args.client,
        data_dir=args.data_dir.expanduser().resolve(),
        notes_dir=args.notes_dir.expanduser().resolve(),
        recent_days=args.recent_days,
        sections=args.section,
        compact=args.compact,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
