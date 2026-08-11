"""Read-only, user-outcome probes for the project verification contract."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from harness_mem.commands.support import DEFAULT_DATA_DIR
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.hook_receipts import (
    inspect_hook_execution_receipt,
    read_hook_execution_receipt,
)
from harness_mem.hook_runtime import collect_hook_file_statuses


DEFAULT_RECENT_DAYS = 7
MIN_NOTE_CHARS = 200


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
        "session_pair_status": pair_status,
        "lifecycle_verified": both_fresh
        and pair_status in {"matched", "not_required"},
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
        current = latest_by_session.get(job.session_id)
        if current is None or (_parse_datetime(job.completed_at) or since) > (
            _parse_datetime(current.completed_at) or since
        ):
            latest_by_session[job.session_id] = job

    note_records: list[dict[str, Any]] = []
    summaries_meaningful = 0
    for session_id, job in sorted(latest_by_session.items()):
        path = notes_dir / f"{session_id}.md"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        summary = str((job.semantic_review or {}).get("session_summary") or "").strip()
        lowered = content.lower()
        topic_present = any(
            marker in lowered
            for marker in ("会话主题", "## scope", "# session ")
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
            and session_id in content
            and topic_present
            and outcome_present
        )
        summaries_meaningful += int(len(summary) >= 12)
        note_records.append(
            {
                "session_id": session_id,
                "job_id": job.id,
                "completed_at": _iso(_parse_datetime(job.completed_at)),
                "path": str(path),
                "exists": path.is_file(),
                "chars": len(content),
                "meaningful": meaningful,
                "topic_present": topic_present,
                "outcome_present": outcome_present,
                "semantic_summary_present": len(summary) >= 12,
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
        "note_coverage": meaningful_count / expected if expected else 0.0,
        "note_coverage_complete": expected > 0 and meaningful_count == expected,
        "semantic_summaries_meaningful": summaries_meaningful,
        "semantic_summary_coverage_complete": expected > 0
        and summaries_meaningful == expected,
        "notes": note_records,
    }


def _query_candidates(content: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{4,}", content)
    candidates = [word for word in words if word.lower() not in {"about", "which", "their", "there", "current"}]
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
    successful = [row for row in rows if row["status"] == "completed" and row["completed_at"]]
    last_success = successful[0] if successful else None
    last = rows[0] if rows else None
    return {
        "run_count": len(rows),
        "successful_run_count": len(successful),
        "last_status": last["status"] if last else None,
        "last_run_at": (last["completed_at"] or last["started_at"]) if last else None,
        "last_successful_run_at": last_success["completed_at"] if last_success else None,
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
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    hooks = inspect_hook_outcome(
        data_dir,
        project_root=project_root,
        client=client,
    )
    recent_cutoff = now - timedelta(days=recent_days)
    dream = inspect_dream_outcome(
        data_dir,
        project_name,
        recent_cutoff=recent_cutoff,
    )
    jobs = _read_distill_jobs(data_dir, project_name)
    distill = inspect_distill_notes(
        jobs,
        notes_dir=notes_dir,
        since=recent_cutoff,
    )
    retrieval = inspect_retrieval_outcome(data_dir, project_name)
    return {
        "schema_version": 1,
        "project": project_name,
        "project_root": str(project_root),
        "observed_at": now.isoformat(),
        "window_days": recent_days,
        "hooks": hooks,
        "dream": dream,
        "distill": distill,
        "retrieval": retrieval,
    }


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
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
