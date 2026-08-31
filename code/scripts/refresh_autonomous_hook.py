#!/usr/bin/env python3
"""Refresh the harness-mem autonomous outcome receipt via a real Codex Hook pair."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ISOLATED_DATA_DIR = REPO_ROOT / ".tmp" / "outcome-refresh-data"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        check=True,
    )


async def _persist_fixture_session(
    *,
    data_dir: Path,
    project_root: Path,
    session_id: str,
) -> None:
    from harness_mem.adapters.snapshot import persist_session_snapshot
    from harness_mem.core.schemas.observation import Observation
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        await persist_session_snapshot(
            backend,
            Observation(
                session_id=session_id,
                client="codex",
                raw_content=(
                    "User: Refresh autonomous outcome receipt for harness-mem.\n\n"
                    "Assistant: Proceed with the bounded background semantic batch.\n"
                ),
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "harness-mem"},
            ),
            project_name="harness-mem",
            project_root=str(project_root),
            client="codex",
            session_id=session_id,
            source_kind="jsonl",
            source_uri=f"file:///{session_id}.jsonl",
            source_text=(
                "User: Refresh autonomous outcome receipt for harness-mem.\n\n"
                "Assistant: Proceed with the bounded background semantic batch.\n"
            ),
        )
    finally:
        await backend.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=REPO_ROOT,
        help="Project root that owns .harness-mem.toml",
    )
    parser.add_argument(
        "--session-id",
        default=f"outcome-refresh-{uuid.uuid4().hex[:12]}",
        help="Synthetic Codex session id used for the refresh pair",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_ISOLATED_DATA_DIR,
        help="Isolated harness-mem data root used by default",
    )
    parser.add_argument(
        "--apply-live",
        action="store_true",
        help="Use the operator live data root (~/.harness-mem/data) instead of --data-dir",
    )
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise SystemExit(f"project root does not exist: {project_root}")

    if args.apply_live:
        data_dir = Path.home() / ".harness-mem" / "data"
    else:
        data_dir = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HARNESS_MEM_DATA_DIR"] = str(data_dir)

    asyncio.run(
        _persist_fixture_session(
            data_dir=data_dir,
            project_root=project_root,
            session_id=args.session_id,
        )
    )

    env = os.environ.copy()
    env["HARNESS_MEM_CLIENT"] = "codex"
    env["HARNESS_MEM_DATA_DIR"] = str(data_dir)
    hook = [
        sys.executable,
        "-m",
        "harness_mem.host_entry",
    ]
    start_payload = json.dumps(
        {
            "session_id": args.session_id,
            "turn_id": args.session_id,
        }
    )
    try:
        _run(
            [
                *hook,
                "--adapter",
                "codex-start",
                "--project-root",
                str(project_root),
            ],
            cwd=project_root,
            env=env,
            stdin=start_payload,
        )
        _run(
            [
                *hook,
                "--adapter",
                "codex-stop",
                "--project-root",
                str(project_root),
                "--wait",
                "--wait-timeout",
                "600",
            ],
            cwd=project_root,
            env=env,
            stdin=start_payload,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "autonomous refresh failed; isolated data remains under "
            f"{data_dir} for inspection"
        ) from exc
    print(f"autonomous refresh completed for session_id={args.session_id}", flush=True)
    print(f"data_dir={data_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
