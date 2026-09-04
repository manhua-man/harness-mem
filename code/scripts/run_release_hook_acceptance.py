#!/usr/bin/env python3
"""Stage a release session and run a real Cursor-style Hook through the worker."""

# ruff: noqa: E402 -- the worktree must precede any installed harness_mem package.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import __version__
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.executors.registry import (
    build_semantic_executor,
    resolve_semantic_executor_client,
)
from harness_mem.autonomous.worker import autonomous_runtime_fingerprint, read_autonomous_receipt
from harness_mem.autonomous.executors.constants import host_cli_provider_name
from harness_mem.autonomous.provider import ProviderError
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.observation import Observation
from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.outcome_probe import collect_outcomes
from harness_mem.qualification.distill_acceptance import run_model_samples
from harness_mem.storage.local_memory_backend import (
    DEFAULT_DATA_DIR as REAL_DATA_DIR,
    LocalMemoryBackend,
)

def _release_session_text(session_id: str) -> str:
    del session_id
    return (
        "User: Remember this permanent project rule for future work: every release "
        "verification record must include a unique run identifier. This is a durable "
        "rule, not a one-time request.\n\n"
        "Assistant: Confirmed. Every release verification record must include a "
        "unique run identifier.\n"
    )


async def _stage_session(
    *,
    data_dir: Path,
    project_root: Path,
    project_name: str,
    hook_client: str,
    session_id: str,
    source_text: str,
) -> str:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        with temporarily_disable_embeddings():
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id=session_id,
                    client=hook_client,
                    raw_content=source_text,
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"release_acceptance": __version__},
                ),
                project_name=project_name,
                project_root=str(project_root),
                client=hook_client,
                session_id=session_id,
                source_kind="jsonl",
                source_uri=f"file:///{session_id}.jsonl",
                source_text=source_text,
            )
        assert snapshot.distill_job_id is not None
        return snapshot.distill_job_id
    finally:
        await backend.close()


def _run_hook(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_root: Path,
    hook_client: str,
    session_id: str,
    wait_timeout: int,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "harness_mem.host_entry.__main__",
        "--action",
        "post-turn-maintenance",
        "--project-root",
        str(project_root),
        "--source",
        "ide_hook",
        "--client",
        hook_client,
        "--trigger-id",
        session_id,
        "--wait",
        "--wait-timeout",
        str(wait_timeout),
    ]
    env = os.environ.copy()
    env["HARNESS_MEM_DATA_DIR"] = str(data_dir)
    env["HARNESS_MEM_SESSION_NOTES_DIR"] = str(notes_dir)
    env["HARNESS_MEM_DISABLE_EMBEDDINGS"] = "1"
    return subprocess.run(
        command,
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_timeout + 120,
    )


async def _read_job_truth(
    *,
    data_dir: Path,
    project_name: str,
    job_id: str,
) -> dict:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        job = backend.transcript_store.get_distill_job(job_id)
        points = list((job.promotion_summary if job else {}).get("points") or [])
        truth_ids = list(
            dict.fromkeys(
                str(entry_id)
                for point in points
                for entry_id in point.get("canonical_truth_ids") or []
                if str(entry_id).strip()
            )
        )
        entries = []
        for entry_id in truth_ids:
            entry = await backend.structured_store.knowledge_store.get_entry(
                entry_id,
                project_name=project_name,
            )
            if entry is not None:
                entries.append({"title": entry.title, "statement": entry.statement})
        return {
            "job_status": job.status if job else None,
            "bound_truth_count": len(truth_ids),
            "sqlite_truth_count": len(entries),
            "entries": entries,
        }
    finally:
        await backend.close()


def _real_notes_dir() -> Path:
    override = str(os.environ.get("HARNESS_MEM_SESSION_NOTES_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".codex" / "hm-distill" / "sessions").resolve()


def _run_absent_from_real_ledger(
    *,
    data_dir: Path,
    project_name: str,
    client: str,
    session_id: str,
    job_id: str,
) -> bool:
    """Check this synthetic run through SQLite's read-only connection mode."""

    ledger = data_dir.expanduser().resolve() / "transcript_ledger.sqlite"
    if not ledger.is_file():
        return True
    connection = sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        job_exists = connection.execute(
            "SELECT 1 FROM distill_jobs WHERE id = ? LIMIT 1",
            (job_id,),
        ).fetchone()
        session_exists = connection.execute(
            """
            SELECT 1 FROM transcript_sources
            WHERE project_name = ? AND client = ? AND session_id = ?
            LIMIT 1
            """,
            (project_name, client, session_id),
        ).fetchone()
        return job_exists is None and session_exists is None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return True
        raise
    finally:
        connection.close()


def _search_via_mcp(
    *,
    data_dir: Path,
    notes_dir: Path,
    project_root: Path,
    project_name: str,
    query: str,
) -> dict:
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "release-hook-acceptance"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_memory",
                "arguments": {
                    "query": query,
                    "project_name": project_name,
                    "scope": "project",
                },
            },
        },
    ]
    env = os.environ.copy()
    env["HARNESS_MEM_DATA_DIR"] = str(data_dir)
    env["HARNESS_MEM_SESSION_NOTES_DIR"] = str(notes_dir)
    env["HARNESS_MEM_DISABLE_EMBEDDINGS"] = "1"
    process = subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server"],
        cwd=project_root,
        env=env,
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        return {"process_ok": False, "status": "failed", "memories": []}
    responses = [
        json.loads(line) for line in process.stdout.splitlines() if line.strip()
    ]
    if len(responses) != 2 or "error" in responses[1]:
        return {"process_ok": False, "status": "failed", "memories": []}
    content = list((responses[1].get("result") or {}).get("content") or [])
    if not content:
        return {"process_ok": False, "status": "failed", "memories": []}
    payload = json.loads(str(content[0].get("text") or "{}"))
    return {
        "process_ok": True,
        "status": payload.get("status"),
        "memories": list(payload.get("memories") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--project-name", default="harness-mem")
    parser.add_argument("--hook-client", default="cursor")
    parser.add_argument("--wait-timeout", type=int, default=600)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / ".tmp" / "release-hook-acceptance.json",
    )
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    release_id = __version__.replace(".", "")
    session_id = f"release-{release_id}-{uuid.uuid4().hex[:8]}"
    runtime_root = output_path.parent / "release-hook-acceptance-runs" / session_id
    data_dir = runtime_root / "data"
    notes_dir = runtime_root / "notes"
    real_data_dir = REAL_DATA_DIR.expanduser().resolve()
    real_notes_dir = _real_notes_dir()
    if data_dir.resolve().is_relative_to(real_data_dir):
        raise RuntimeError("Isolated data directory overlaps the real data directory")
    if notes_dir.resolve().is_relative_to(real_notes_dir):
        raise RuntimeError("Isolated Note directory overlaps the real Note directory")
    source_text = _release_session_text(session_id)
    merged = load_merged_config(project_root)
    selected_cli = resolve_semantic_executor_client(merged, args.hook_client)
    expected_provider = host_cli_provider_name(selected_cli)

    model_check_path = runtime_root / "model-check.json"
    try:
        provider = build_semantic_executor(merged, args.hook_client)
        model_check = run_model_samples(
            output_path=model_check_path,
            provider=provider,
            fixture_ids=("F2",),
            stop_on_failure=True,
        )
    except ProviderError as exc:
        model_check = {
            "status": "failed",
            "passed": 0,
            "failed": 1,
            "total": 1,
            "planned_total": 1,
            "stopped_early": False,
            "error": {"kind": exc.kind, "message": str(exc)[:1000]},
        }
        model_check_path.parent.mkdir(parents=True, exist_ok=True)
        model_check_path.write_text(
            json.dumps(model_check, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if model_check.get("status") != "passed":
        report = {
            "status": "failed",
            "reason": "model_check_failed",
            "hook_client": args.hook_client,
            "selected_cli": selected_cli,
            "model_check": model_check,
            "model_check_path": str(model_check_path),
            "full_hook_started": False,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    runtime_before = autonomous_runtime_fingerprint()
    job_id = asyncio.run(
        _stage_session(
            data_dir=data_dir,
            project_root=project_root,
            project_name=args.project_name,
            hook_client=args.hook_client,
            session_id=session_id,
            source_text=source_text,
        )
    )
    started = time.monotonic()
    proc = _run_hook(
        data_dir=data_dir,
        notes_dir=notes_dir,
        project_root=project_root,
        hook_client=args.hook_client,
        session_id=session_id,
        wait_timeout=args.wait_timeout,
    )
    elapsed = time.monotonic() - started
    receipt = read_autonomous_receipt(
        data_dir,
        project_name=args.project_name,
        project_root=project_root,
    ) or {}
    outcomes = collect_outcomes(
        project_name=args.project_name,
        project_root=project_root,
        client=args.hook_client,
        data_dir=data_dir,
        notes_dir=notes_dir,
        recent_days=7,
        sections=["autonomous"],
        compact=True,
    )
    autonomous = outcomes.get("autonomous") or {}
    job_truth = asyncio.run(
        _read_job_truth(
            data_dir=data_dir,
            project_name=args.project_name,
            job_id=job_id,
        )
    )
    raw_entries = job_truth.pop("entries", [])
    entries = raw_entries if isinstance(raw_entries, list) else []
    target_entry = entries[0] if entries else None
    search = (
        _search_via_mcp(
            data_dir=data_dir,
            notes_dir=notes_dir,
            project_root=project_root,
            project_name=args.project_name,
            query=str(target_entry["title"]),
        )
        if target_entry is not None
        else {"process_ok": False, "status": "not_run", "memories": []}
    )
    raw_memories = search.pop("memories", [])
    memories = raw_memories if isinstance(raw_memories, list) else []
    normal_search_hit = bool(
        target_entry is not None
        and any(
            item.get("title") == target_entry["title"]
            and item.get("statement") == target_entry["statement"]
            for item in memories
        )
    )
    real_note_absent = not (real_notes_dir / f"{session_id}.md").exists()
    real_ledger_run_absent = _run_absent_from_real_ledger(
        data_dir=real_data_dir,
        project_name=args.project_name,
        client=args.hook_client,
        session_id=session_id,
        job_id=job_id,
    )
    persistence = {
        **job_truth,
        **search,
        "normal_search_hit": normal_search_hit,
        "returned_memory_count": len(memories),
    }
    isolation = {
        "data_dir_isolated": not data_dir.resolve().is_relative_to(real_data_dir),
        "notes_dir_isolated": not notes_dir.resolve().is_relative_to(real_notes_dir),
        "real_ledger_run_absent": real_ledger_run_absent,
        "real_note_absent": real_note_absent,
    }
    provider_matches_selected_cli = (
        (receipt.get("provider") or {}).get("name") == expected_provider
    )
    report = {
        "session_id": session_id,
        "distill_job_id": job_id,
        "hook_client": args.hook_client,
        "selected_cli": selected_cli,
        "model_check": model_check,
        "model_check_path": str(model_check_path),
        "full_hook_started": True,
        "elapsed_seconds": round(elapsed, 2),
        "hook_exit_code": proc.returncode,
        "hook_stdout": proc.stdout.strip()[:2000],
        "hook_stderr": proc.stderr.strip()[:2000],
        "runtime_fingerprint_before": runtime_before,
        "runtime_fingerprint_current": autonomous_runtime_fingerprint(),
        "receipt_state": receipt.get("state"),
        "provider_name": (receipt.get("provider") or {}).get("name"),
        "provider_matches_selected_cli": provider_matches_selected_cli,
        "runtime_current": autonomous.get("runtime_current"),
        "config_current": autonomous.get("config_current"),
        "lifecycle_verified": autonomous.get("lifecycle_verified"),
        "provider_isolated": autonomous.get("provider_isolated"),
        "distill_autonomous_cli": getattr(merged, "distill_autonomous_cli", None),
        "isolation": isolation,
        "persistence": persistence,
        "autonomous": autonomous,
    }
    ok = (
        proc.returncode == 0
        and autonomous.get("lifecycle_verified") is True
        and autonomous.get("runtime_current") is True
        and autonomous.get("config_current") is True
        and autonomous.get("provider_isolated") is True
        and autonomous.get("note_verified") is True
        and (autonomous.get("hook_guard_check") or {}).get("all_blocked") is True
        and int(
            (autonomous.get("hook_guard_check") or {}).get(
                "downstream_jobs_created", -1
            )
        )
        == 0
        and provider_matches_selected_cli
        and persistence.get("job_status") == "completed"
        and int(persistence.get("bound_truth_count") or 0) >= 1
        and int(persistence.get("sqlite_truth_count") or 0) >= 1
        and persistence.get("process_ok") is True
        and persistence.get("status") == "answered"
        and persistence.get("normal_search_hit") is True
        and all(isolation.values())
    )
    report["status"] = "passed" if ok else "failed"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
