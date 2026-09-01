#!/usr/bin/env python3
"""Stage a release session and run a real Cursor-style Hook through the worker."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.worker import autonomous_runtime_fingerprint, read_autonomous_receipt
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.observation import Observation
from harness_mem.embedding import temporarily_disable_embeddings
from harness_mem.outcome_probe import collect_outcomes
from harness_mem.storage.local_memory_backend import LocalMemoryBackend, DEFAULT_DATA_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]

RELEASE_SESSION_TEXT = (
    "User: Release 0.9.26 background memory uses the project-selected host CLI only.\n\n"
    "Assistant: Confirmed. Background work runs through Hermes or Claude Code CLI with "
    "honest host_cli receipts and no HTTP profile fallback.\n"
)


async def _stage_session(
    *,
    project_root: Path,
    project_name: str,
    hook_client: str,
    session_id: str,
) -> str:
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        with temporarily_disable_embeddings():
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id=session_id,
                    client=hook_client,
                    raw_content=RELEASE_SESSION_TEXT,
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"release_acceptance": "0.9.26"},
                ),
                project_name=project_name,
                project_root=str(project_root),
                client=hook_client,
                session_id=session_id,
                source_kind="jsonl",
                source_uri=f"file:///{session_id}.jsonl",
                source_text=RELEASE_SESSION_TEXT,
            )
        assert snapshot.distill_job_id is not None
        return snapshot.distill_job_id
    finally:
        await backend.close()


def _run_hook(
    *,
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
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_timeout + 120,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--project-name", default="harness-mem")
    parser.add_argument("--hook-client", default="cursor")
    parser.add_argument(
        "--cli",
        default="hermes",
        choices=("codex", "claude-code", "hermes", "opencode"),
    )
    parser.add_argument("--wait-timeout", type=int, default=900)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / ".tmp" / "release-hook-acceptance.json",
    )
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    session_id = f"release-0926-{uuid.uuid4().hex[:8]}"
    config_path = project_root / ".harness-mem.toml"
    config_text = (
        "[distill.autonomous]\n"
        f"enabled = true\n"
        f'cli = "{args.cli}"\n'
    )
    if config_path.is_file():
        existing = config_path.read_text(encoding="utf-8")
        if f'cli = "{args.cli}"' not in existing:
            print(
                f"warning: {config_path} does not set cli={args.cli}; "
                "update it before relying on this run.",
                file=sys.stderr,
            )
    else:
        config_path.write_text(config_text, encoding="utf-8")

    runtime_before = autonomous_runtime_fingerprint()
    job_id = asyncio.run(
        _stage_session(
            project_root=project_root,
            project_name=args.project_name,
            hook_client=args.hook_client,
            session_id=session_id,
        )
    )
    started = time.monotonic()
    proc = _run_hook(
        project_root=project_root,
        hook_client=args.hook_client,
        session_id=session_id,
        wait_timeout=args.wait_timeout,
    )
    elapsed = time.monotonic() - started
    receipt = read_autonomous_receipt(
        DEFAULT_DATA_DIR,
        project_name=args.project_name,
        project_root=project_root,
    ) or {}
    outcomes = collect_outcomes(
        project_name=args.project_name,
        project_root=project_root,
        client=args.hook_client,
        data_dir=DEFAULT_DATA_DIR,
        notes_dir=Path.home() / ".codex" / "hm-distill" / "sessions",
        recent_days=7,
        sections=["autonomous"],
        compact=True,
    )
    autonomous = outcomes.get("autonomous") or {}
    merged = load_merged_config(project_root)
    report = {
        "session_id": session_id,
        "distill_job_id": job_id,
        "hook_client": args.hook_client,
        "selected_cli": args.cli,
        "elapsed_seconds": round(elapsed, 2),
        "hook_exit_code": proc.returncode,
        "hook_stdout": proc.stdout.strip()[:2000],
        "hook_stderr": proc.stderr.strip()[:2000],
        "runtime_fingerprint_before": runtime_before,
        "runtime_fingerprint_current": autonomous_runtime_fingerprint(),
        "receipt_state": receipt.get("state"),
        "provider_name": (receipt.get("provider") or {}).get("name"),
        "execution_mode": (receipt.get("provider") or {}).get("execution_mode"),
        "runtime_current": autonomous.get("runtime_current"),
        "config_current": autonomous.get("config_current"),
        "lifecycle_verified": autonomous.get("lifecycle_verified"),
        "provider_isolated": autonomous.get("provider_isolated"),
        "distill_autonomous_cli": getattr(merged, "distill_autonomous_cli", None),
        "autonomous": autonomous,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = (
        proc.returncode == 0
        and autonomous.get("lifecycle_verified") is True
        and autonomous.get("runtime_current") is True
        and str((receipt.get("provider") or {}).get("name") or "").endswith("_cli")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
