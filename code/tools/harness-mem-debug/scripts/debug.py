"""Read-only developer debugger for harness-mem runtime evidence.

This tool is intentionally outside the ``hm`` and MCP product surfaces.  It
reads the diagnostic NDJSON ledger and existing receipts/stores without
initializing any runtime backend or writing to memory data.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Iterable, Mapping


_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness_mem.diagnostic_events import (  # noqa: E402
    FAILURE_EVENT_STATUSES,
    RUN_EVENT_SCHEMA_VERSION,
    TERMINAL_EVENT_STATUSES,
    load_run_events,
    project_root_sha256,
    safe_error,
)


DEFAULT_DATA_DIR = Path(
    os.environ.get("HARNESS_MEM_DATA_DIR") or Path.home() / ".harness-mem" / "data"
)
DEBUG_REPORT_SCHEMA_VERSION = "harness_mem.debug_report.v1"
TERMINAL_REPORT_STATUSES = frozenset({"completed", "failed", "blocked"})


class DebugToolError(RuntimeError):
    """A user-correctable or evidence-reading debugger error."""


def _utc(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return None


def _safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _event_refs(events: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for event in events:
        values = event.get("references")
        if not isinstance(values, Mapping):
            continue
        for key, value in values.items():
            if value is not None and str(value):
                refs[str(key)] = str(value)
    return refs


def _summarize_receipt(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    error_summary = safe_error(payload.get("error"))
    return {
        "path": _safe_path(path),
        "sha256": _sha256_file(path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status") or payload.get("state"),
        "state": payload.get("state"),
        "project_name": payload.get("project_name"),
        "client": payload.get("client"),
        "action": payload.get("action"),
        "trigger_id": payload.get("trigger_id"),
        "job_id": payload.get("job_id"),
        "session_id": payload.get("session_id"),
        "run_id": payload.get("run_id"),
        "error": error_summary,
    }


def _receipt_matches(payload: Mapping[str, Any], refs: Mapping[str, str]) -> bool:
    identifiers = {
        str(payload.get("trigger_id") or ""),
        str(payload.get("job_id") or ""),
        str(payload.get("session_id") or ""),
        str(payload.get("run_id") or ""),
    }
    wanted = {
        str(refs.get(key) or "")
        for key in ("trigger_id", "job_id", "session_id", "run_id")
    }
    wanted.discard("")
    return bool(wanted & identifiers)


def _linked_receipts(data_dir: Path, refs: Mapping[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for directory in (
        data_dir / "hook_runtime",
        data_dir / "autonomous" / "receipts",
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            payload = _read_json(path)
            if payload is None or not _receipt_matches(payload, refs):
                continue
            results.append(_summarize_receipt(path, payload))
    return results


def _job_snapshot(data_dir: Path, job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    path = data_dir / "transcript_ledger.sqlite"
    try:
        with closing(_read_only_connection(path)) as connection:
            row = connection.execute(
                "SELECT data FROM distill_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
    except (OSError, sqlite3.DatabaseError):
        return {"status": "unavailable", "path": _safe_path(path)}
    if row is None:
        return {"status": "missing", "path": _safe_path(path), "job_id": job_id}
    try:
        payload = json.loads(row["data"])
    except (TypeError, json.JSONDecodeError):
        return {"status": "invalid", "path": _safe_path(path), "job_id": job_id}
    if not isinstance(payload, dict):
        return {"status": "invalid", "path": _safe_path(path), "job_id": job_id}
    return {
        "status": "found",
        "path": _safe_path(path),
        "job_id": payload.get("id") or job_id,
        "project_name": payload.get("project_name"),
        "session_id": payload.get("session_id"),
        "source_id": payload.get("source_id"),
        "source_revision": payload.get("source_revision"),
        "job_status": payload.get("status"),
        "phase": payload.get("phase"),
        "completion_disposition": payload.get("completion_disposition"),
        "error": safe_error(payload.get("error")),
        "attempt_count": payload.get("attempt_count"),
        "updated_at": payload.get("updated_at"),
        "completed_at": payload.get("completed_at"),
    }


def _sqlite_snapshots(
    data_dir: Path,
    *,
    project_name: str | None,
    job_id: str | None,
    include_source: bool = False,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    gaps: list[str] = []
    sources: list[dict[str, Any]] = []

    transcript_path = data_dir / "transcript_ledger.sqlite"
    if transcript_path.is_file():
        item: dict[str, Any] = {
            "kind": "transcript_ledger",
            "path": _safe_path(transcript_path),
            "sha256": _sha256_file(transcript_path),
        }
        try:
            with closing(_read_only_connection(transcript_path)) as connection:
                if job_id:
                    row = connection.execute(
                        "SELECT data FROM distill_jobs WHERE id = ?",
                        (job_id,),
                    ).fetchone()
                    item["job_present"] = row is not None
                    if include_source and row is not None:
                        payload = json.loads(row["data"])
                        source_id = payload.get("source_id")
                        source_revision = payload.get("source_revision")
                        if source_id and source_revision:
                            rows = connection.execute(
                                """
                                SELECT data FROM transcript_chunks
                                WHERE source_id = ? AND source_revision = ?
                                ORDER BY chunk_index ASC
                                """,
                                (source_id, source_revision),
                            ).fetchall()
                            for chunk_row in rows:
                                chunk = json.loads(chunk_row["data"])
                                if isinstance(chunk, dict):
                                    sources.append(
                                        {
                                            "chunk_index": chunk.get("chunk_index"),
                                            "content_sha256": chunk.get("content_sha256"),
                                            "raw_content": chunk.get("raw_content", ""),
                                        }
                                    )
                if project_name:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM distill_jobs WHERE project_name = ?",
                        (project_name,),
                    ).fetchone()
                    item["project_job_count"] = int(row["count"]) if row else 0
        except (sqlite3.DatabaseError, OSError, TypeError, ValueError) as exc:
            item["read_error"] = type(exc).__name__
            gaps.append("transcript_ledger_unreadable")
        evidence.append(item)
    else:
        gaps.append("transcript_ledger_missing")

    canonical_path = data_dir / "store_v2" / "canonical.sqlite"
    if canonical_path.is_file():
        item = {
            "kind": "canonical_sqlite",
            "path": _safe_path(canonical_path),
            "sha256": _sha256_file(canonical_path),
        }
        try:
            with closing(_read_only_connection(canonical_path)) as connection:
                if project_name:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM knowledge_entries WHERE project_id = ?",
                        (project_name,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM knowledge_entries"
                    ).fetchone()
                item["knowledge_entry_count"] = int(row["count"]) if row else 0
        except (sqlite3.DatabaseError, OSError) as exc:
            item["read_error"] = type(exc).__name__
            gaps.append("canonical_sqlite_unreadable")
        evidence.append(item)
    else:
        gaps.append("canonical_sqlite_missing")

    structured_path = data_dir / "structured_index.sqlite"
    if structured_path.is_file():
        item = {
            "kind": "structured_index",
            "path": _safe_path(structured_path),
            "sha256": _sha256_file(structured_path),
        }
        try:
            with closing(_read_only_connection(structured_path)) as connection:
                if project_name:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM dream_runs WHERE project_name = ?",
                        (project_name,),
                    ).fetchone()
                    item["dream_run_count"] = int(row["count"]) if row else 0
        except (sqlite3.DatabaseError, OSError) as exc:
            item["read_error"] = type(exc).__name__
            gaps.append("structured_index_unreadable")
        evidence.append(item)

    return evidence, gaps, sources


def _child_runs(data_dir: Path, run_id: str) -> list[dict[str, Any]]:
    try:
        events, _malformed = load_run_events(data_dir)
    except OSError:
        return []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("parent_run_id") == run_id and event.get("run_id"):
            grouped[str(event["run_id"])].append(event)
    children: list[dict[str, Any]] = []
    for child_id, child_events in grouped.items():
        terminal = next(
            (
                event
                for event in reversed(sorted(child_events, key=lambda item: _utc(item.get("timestamp"))))
                if event.get("status") in TERMINAL_EVENT_STATUSES
            ),
            None,
        )
        children.append(
            {
                "run_id": child_id,
                "operation": child_events[0].get("operation"),
                "status": terminal.get("status") if terminal else "incomplete",
                "event_count": len(child_events),
            }
        )
    return sorted(children, key=lambda item: item["run_id"])


def _event_report(
    data_dir: Path,
    *,
    run_id: str,
    events: list[dict[str, Any]],
    malformed: int,
    project_name: str | None,
    include_source: bool = False,
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda item: _utc(item.get("timestamp")))
    terminal = [
        event for event in ordered if event.get("status") in TERMINAL_EVENT_STATUSES
    ]
    last_terminal = terminal[-1] if terminal else None
    terminal_status = str(last_terminal.get("status")) if last_terminal else None
    status = {
        "completed": "completed",
        "failed": "failed",
        "blocked": "blocked",
        "deferred": "blocked",
        "skipped": "blocked",
    }.get(terminal_status, "incomplete")
    failures = [
        event for event in ordered if event.get("status") in FAILURE_EVENT_STATUSES
    ]
    root = failures[0] if failures else None
    refs = _event_refs(ordered)
    job = _job_snapshot(data_dir, refs.get("job_id"))
    receipts = _linked_receipts(data_dir, {**refs, "run_id": run_id})
    sqlite_evidence, gaps, sources = _sqlite_snapshots(
        data_dir,
        project_name=project_name or (ordered[0].get("project_name") if ordered else None),
        job_id=refs.get("job_id"),
        include_source=include_source,
    )
    if malformed:
        gaps.append(f"malformed_event_lines:{malformed}")
    if not ordered:
        gaps.append("run_events_not_found")
    if ordered and not any(event.get("stage") == "started" for event in ordered):
        gaps.append("run_started_event_missing")
    if ordered and not terminal:
        gaps.append("terminal_event_missing")
    operation = ordered[0].get("operation") if ordered else None
    if (
        status == "completed"
        and operation in {"autonomous", "dream", "distill"}
        and not any(
            event.get("stage") == "readback_verified" for event in ordered
        )
    ):
        gaps.append("readback_verified_event_missing")
    report: dict[str, Any] = {
        "schema_version": DEBUG_REPORT_SCHEMA_VERSION,
        "event_schema_version": RUN_EVENT_SCHEMA_VERSION,
        "evidence_mode": "event_timeline",
        "run": {
            "run_id": run_id,
            "operation": operation,
            "project_name": project_name or (ordered[0].get("project_name") if ordered else None),
            "started_at": ordered[0].get("timestamp") if ordered else None,
            "finished_at": last_terminal.get("timestamp") if last_terminal else None,
            "terminal_status": terminal_status,
        },
        "status": status,
        "root_cause": (
            {
                "event_id": root.get("event_id"),
                "stage": root.get("stage"),
                "status": root.get("status"),
                "timestamp": root.get("timestamp"),
                "error": root.get("error"),
            }
            if root
            else None
        ),
        "timeline": ordered,
        "linked_evidence": [
            *receipts,
            *([{"kind": "distill_job", **job}] if job else []),
            *sqlite_evidence,
        ],
        "evidence_gaps": sorted(set(gaps)),
        "children": _child_runs(data_dir, run_id),
    }
    if sources:
        report["sources"] = sources
    return report


def _legacy_report(
    data_dir: Path,
    *,
    selector: str,
    project_name: str | None,
    job_id: str | None = None,
    trigger_id: str | None = None,
    include_source: bool = False,
) -> dict[str, Any]:
    refs = {
        key: value
        for key, value in {
            "job_id": job_id,
            "trigger_id": trigger_id,
        }.items()
        if value
    }
    job = _job_snapshot(data_dir, job_id)
    if job and job.get("project_name") and project_name is None:
        project_name = str(job["project_name"])
    if job:
        refs.update(
            {
                key: str(job[key])
                for key in ("session_id", "source_revision")
                if job.get(key)
            }
        )
    receipts = _linked_receipts(data_dir, refs)
    sqlite_evidence, gaps, sources = _sqlite_snapshots(
        data_dir,
        project_name=project_name,
        job_id=job_id,
        include_source=include_source,
    )
    receipt_errors = [
        item.get("error")
        for item in receipts
        if isinstance(item.get("error"), Mapping)
    ]
    job_status = job.get("job_status") if job else None
    status = "completed" if job_status == "completed" else "incomplete"
    if any(item.get("state") == "failed" for item in receipts) or job_status == "failed":
        status = "failed"
    if not receipts and not job:
        raise DebugToolError(f"no legacy evidence found for {selector}")
    gaps.extend(["no_diagnostic_run_events", "legacy_snapshot_is_not_a_full_timeline"])
    report: dict[str, Any] = {
        "schema_version": DEBUG_REPORT_SCHEMA_VERSION,
        "event_schema_version": RUN_EVENT_SCHEMA_VERSION,
        "evidence_mode": "legacy_snapshot",
        "run": {
            "run_id": None,
            "selector": selector,
            "project_name": project_name,
            "job_id": job_id,
            "trigger_id": trigger_id,
        },
        "status": status,
        "root_cause": (
            {"error": receipt_errors[0]} if receipt_errors else {"reason": "legacy_evidence_only"}
        ),
        "timeline": [],
        "linked_evidence": [
            *receipts,
            *([{"kind": "distill_job", **job}] if job else []),
            *sqlite_evidence,
        ],
        "evidence_gaps": sorted(set(gaps)),
        "children": [],
    }
    if sources:
        report["sources"] = sources
    return report


def _latest_selector(
    data_dir: Path,
    project_name: str | None,
    project_root: Path | None,
) -> tuple[str, str | None, str | None]:
    try:
        events, _malformed = load_run_events(data_dir)
    except OSError:
        events = []
    if project_root is not None:
        root_digest = project_root_sha256(project_root)
        events = [
            event
            for event in events
            if root_digest is not None
            and event.get("project_root_sha256") == root_digest
        ]
    elif project_name is not None:
        events = [event for event in events if event.get("project_name") == project_name]
    if events:
        latest = max(events, key=lambda item: _utc(item.get("timestamp")))
        return "run", str(latest.get("run_id")), None
    candidates = [
        path
        for directory in (
            data_dir / "autonomous" / "receipts",
            data_dir / "hook_runtime",
        )
        if directory.is_dir()
        for path in directory.glob("*.json")
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        payload = _read_json(candidates[0]) or {}
        return "trigger", None, str(payload.get("trigger_id") or "") or None
    raise DebugToolError("no latest diagnostic or receipt evidence found")


def _resolve_report(args: argparse.Namespace, *, include_source: bool = False) -> dict[str, Any]:
    data_dir = Path(args.data_dir).expanduser().resolve()
    project_name = args.project_name

    if args.latest:
        kind, resolved_run, resolved_trigger = _latest_selector(
            data_dir,
            project_name,
            args.project_root,
        )
        if kind == "run" and resolved_run:
            args.run_id = resolved_run
        else:
            args.trigger_id = resolved_trigger

    if args.run_id:
        try:
            events, malformed = load_run_events(data_dir, run_id=args.run_id)
        except OSError as exc:
            raise DebugToolError(f"could not read diagnostic ledger: {exc}") from exc
        if not events:
            raise DebugToolError(f"run id not found: {args.run_id}")
        return _event_report(
            data_dir,
            run_id=args.run_id,
            events=events,
            malformed=malformed,
            project_name=project_name,
            include_source=include_source,
        )
    if args.job_id or args.trigger_id:
        return _legacy_report(
            data_dir,
            selector=(f"job:{args.job_id}" if args.job_id else f"trigger:{args.trigger_id}"),
            project_name=project_name,
            job_id=args.job_id,
            trigger_id=args.trigger_id,
            include_source=include_source,
        )
    raise DebugToolError("one selector is required: --run-id, --job-id, --trigger-id, or --latest")


def _print_report(report: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(_json(report), end="")
        return
    run = report.get("run") or {}
    print(f"Status: {report.get('status')}")
    print(f"Evidence: {report.get('evidence_mode')}")
    print(f"Run: {run.get('run_id') or run.get('selector') or 'unknown'}")
    if report.get("root_cause"):
        print("Root cause:")
        print(f"  {_json(report['root_cause']).strip()}")
    timeline = report.get("timeline") or []
    if timeline:
        print("Timeline:")
        for event in timeline:
            print(
                f"  {event.get('timestamp', '?')} "
                f"{event.get('operation', '?')}/{event.get('stage', '?')} "
                f"[{event.get('status', '?')}]"
            )
    gaps = report.get("evidence_gaps") or []
    if gaps:
        print("Evidence gaps:")
        for gap in gaps:
            print(f"  - {gap}")


def _selector_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--job-id")
    group.add_argument("--trigger-id")
    group.add_argument("--latest", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--project-name")
    parser.add_argument("--project-root", type=Path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Inspect one run or legacy evidence snapshot")
    _selector_args(inspect)
    inspect.add_argument("--json", action="store_true", help="Emit one JSON report")

    events = sub.add_parser("events", help="Stream one run's diagnostic events")
    events.add_argument("--run-id", required=True)
    events.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    events.add_argument("--json", action="store_true", help="Emit JSONL events")
    events.add_argument("--follow", action="store_true", help="Wait until a terminal event")

    bundle = sub.add_parser("bundle", help="Write a redacted diagnostic bundle")
    _selector_args(bundle)
    bundle.add_argument("--output", type=Path, required=True)
    bundle.add_argument("--include-source", action="store_true")

    cursor_schema = sub.add_parser("cursor-schema", help="Read an explicitly selected Cursor SQLite schema (no values)")
    cursor_schema.add_argument("--database", type=Path, required=True)

    return parser


def _run_events(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve()
    seen: set[str] = set()
    observed = False
    try:
        while True:
            events, malformed = load_run_events(data_dir, run_id=args.run_id)
            for event in sorted(events, key=lambda item: _utc(item.get("timestamp"))):
                event_id = str(event.get("event_id") or "")
                if event_id and event_id in seen:
                    continue
                if event_id:
                    seen.add(event_id)
                observed = True
                if args.json:
                    print(json.dumps(event, ensure_ascii=False, sort_keys=True), flush=True)
                else:
                    print(
                        f"{event.get('timestamp', '?')} "
                        f"{event.get('operation', '?')}/{event.get('stage', '?')} "
                        f"[{event.get('status', '?')}]",
                        flush=True,
                    )
                if event.get("status") in TERMINAL_EVENT_STATUSES:
                    return 0
            if not args.follow:
                if not observed:
                    raise DebugToolError(f"run id not found: {args.run_id}")
                return 0
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise DebugToolError(f"could not read diagnostic ledger: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "cursor-schema":
            from harness_mem.adapters.cursor.sqlite_history import inspect_sqlite_schema

            report = inspect_sqlite_schema(args.database)
            print(_json(report), end="")
            return 0 if report.get("status") == "readable" else 3
        if args.command == "events":
            return _run_events(args)
        if args.command == "inspect":
            report = _resolve_report(args)
            _print_report(report, as_json=args.json)
            return 0
        if args.command == "bundle":
            report = _resolve_report(args, include_source=args.include_source)
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(f".{output.name}.{time.time_ns()}.tmp")
            temporary.write_text(_json(report), encoding="utf-8")
            temporary.replace(output)
            print(f"Bundle: {output}")
            return 0
        raise DebugToolError(f"unknown command: {args.command}")
    except DebugToolError as exc:
        print(f"debug error: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.DatabaseError) as exc:
        print(f"debug evidence error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
