#!/usr/bin/env python3
"""Run an isolated autonomous distill batch through a real host CLI executor."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.worker import read_autonomous_receipt, run_autonomous_distill_batch
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.observation import Observation
from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

REPO_ROOT = Path(__file__).resolve().parents[2]

SESSION_FIXTURES: dict[str, str | None] = {
    "short": (
        "User: Always use SQLite for local indexes in this project.\n\n"
        "Assistant: I will preserve that project storage decision.\n"
    ),
    "medium": (
        "User: Always use SQLite for local indexes in this project.\n\n"
        "Assistant: I will preserve that project storage decision.\n\n"
        "User: Also keep FTS rebuildable from canonical SQLite without making "
        "Markdown the authority.\n\n"
        "Assistant: Derived indexes stay rebuildable; canonical SQLite remains "
        "the truth source.\n\n"
        "User: When distilling sessions, split broad decisions into independent "
        "promotion points.\n\n"
        "Assistant: Each durable point should be narrow enough to verify on its "
        "own before assimilation.\n"
    ),
    "long": None,
}


def _long_session_text(exchange_count: int = 80) -> str:
    lines: list[str] = []
    for index in range(exchange_count):
        lines.append(
            f"User: Decision {index}: keep module {index % 7} storage in SQLite.\n\n"
            f"Assistant: Confirmed durable decision {index} for project storage.\n"
        )
    return "".join(lines)


def _load_session_text(size: str) -> str:
    fixture = SESSION_FIXTURES[size]
    if size == "long":
        return _long_session_text()
    assert isinstance(fixture, str)
    return fixture


async def _prepare_run(
    *,
    cli: str,
    hook_client: str,
    size: str,
    work_dir: Path,
) -> tuple[LocalMemoryBackend, Path, Path, str, MergedConfig, str]:
    project = work_dir / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".harness-mem.toml").write_text(
        f"[distill.autonomous]\nenabled = true\ncli = \"{cli}\"\n",
        encoding="utf-8",
    )
    session_text = _load_session_text(size)
    session_id = f"validate-{cli}-{size}"
    data_dir = work_dir / "data"
    notes_dir = work_dir / "notes"
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    with temporarily_disable_embeddings():
        snapshot = await persist_session_snapshot(
            backend,
            Observation(
                session_id=session_id,
                client=hook_client,
                raw_content=session_text,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(project),
            client=hook_client,
            session_id=session_id,
            source_kind="jsonl",
            source_uri=f"file:///{session_id}.jsonl",
            source_text=session_text,
        )
    assert snapshot.distill_job_id is not None
    config = MergedConfig(
        distill_autonomous_enabled=True,
        distill_autonomous_cli=cli,
    )
    return backend, project, notes_dir, session_id, config, snapshot.distill_job_id


def run_chain(
    *,
    cli: str,
    hook_client: str,
    size: str,
    work_dir: Path,
    timeout_hint_seconds: int,
) -> dict[str, Any]:
    backend, project, notes_dir, session_id, config, job_id = asyncio.run(
        _prepare_run(
            cli=cli,
            hook_client=hook_client,
            size=size,
            work_dir=work_dir,
        )
    )
    try:
        started = time.monotonic()
        with temporarily_disable_embeddings():
            result = run_autonomous_distill_batch(
                backend,
                project_name="demo",
                project_root=project,
                config=config,
                trigger_id=session_id,
                client=hook_client,
                notes_dir=notes_dir,
                max_jobs=1,
                preferred_job_id=job_id,
                launch_source="manual",
                dispatch_generation=f"validate-{cli}-{size}",
            )
        elapsed = time.monotonic() - started
        receipt = read_autonomous_receipt(
            backend.data_dir,
            project_name="demo",
            project_root=project,
        )
        provider = (receipt or {}).get("provider") or {}
        verified = (receipt or {}).get("last_verified_completion") or {}
        verified_provider = verified.get("provider") or {}
        return {
            "cli": cli,
            "hook_client": hook_client,
            "size": size,
            "state": result.get("state"),
            "success": result.get("success"),
            "elapsed_seconds": round(elapsed, 2),
            "timeout_hint_seconds": timeout_hint_seconds,
            "provider_name": provider.get("name"),
            "execution_mode": provider.get("execution_mode"),
            "host_client": provider.get("host_client"),
            "input_tokens": provider.get("input_tokens"),
            "output_tokens": provider.get("output_tokens"),
            "total_tokens": provider.get("total_tokens"),
            "verified_provider_name": verified_provider.get("name"),
            "verified_execution_mode": verified_provider.get("execution_mode"),
            "hook_guard_all_blocked": (
                (provider.get("hook_guard_check") or {}).get("all_blocked")
            ),
            "work_dir": str(work_dir),
            "result": {
                "state": result.get("state"),
                "reason": result.get("reason"),
                "error": result.get("error"),
            },
        }
    finally:
        asyncio.run(backend.close())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli",
        required=True,
        choices=("codex", "claude-code", "hermes", "opencode"),
    )
    parser.add_argument(
        "--hook-client",
        default="cursor",
        help="Simulated hook host client (default: cursor)",
    )
    parser.add_argument(
        "--size",
        default="short",
        choices=("short", "medium", "long"),
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=REPO_ROOT / ".tmp" / "autonomous-chain-validate",
    )
    parser.add_argument(
        "--timeout-hint-seconds",
        type=int,
        default=600,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path",
    )
    args = parser.parse_args()
    run_dir = args.work_dir / f"{args.cli}-{args.size}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report = run_chain(
        cli=args.cli,
        hook_client=args.hook_client,
        size=args.size,
        work_dir=run_dir,
        timeout_hint_seconds=args.timeout_hint_seconds,
    )
    output = args.output or (run_dir / "report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("state") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
