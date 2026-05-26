"""One-off script: invoke the v2.3.0 selector against real ~/.harness-mem/ data.

Not part of the test suite. Run with:
    python scripts/try_metabolism_preview.py [project_name]

Default project is F--memory-lab (the project with the most entries on this
host). Pass any other project name as a single argument to override.

We bypass the sync MCP wrapper (`tool_metabolism_preview`) because that
wrapper uses `asyncio.run` internally, which conflicts with the async
context this script needs to query the backend. Real MCP clients hit
`tool_metabolism_preview` over stdio (sync entry) — the wrapper is fine
for them. For the script we call `select_replay_window` directly and
persist the MetabolismRun ourselves, which exercises the same
contract.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

from harness_mem.commands.replay_window import ReplayBudget, select_replay_window
from harness_mem.commands.support import DEFAULT_DATA_DIR
from harness_mem.core.schemas.metabolism_run import MetabolismRun
from harness_mem.mcp.server import _replay_window_to_input_window
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def _list_recent_runs(backend: LocalMemoryBackend, project_name: str) -> None:
    runs = await backend.structured_store.list_metabolism_runs(project_name, limit=3)
    print(f"\nLast {len(runs)} MetabolismRun(s) for {project_name!r} (newest first):")
    for record in runs:
        print(
            f"  - id={record.id[:8]}  kind={record.kind}  status={record.status}"
            f"  signals={len(record.selected_signal_ids)}"
            f"  duration_ms={record.duration_ms}"
        )


async def _run(project_name: str) -> None:
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        budget = ReplayBudget()
        started_at = datetime.now(timezone.utc)
        window = await select_replay_window(
            backend, project_name=project_name, budget=budget
        )
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        input_window = _replay_window_to_input_window(window)

        run_id = await backend.structured_store.save_metabolism_run(
            MetabolismRun(
                project_name=project_name,
                kind="preview",
                status="preview",
                started_at=started_at,
                completed_at=completed_at,
                input_window=input_window,
                selected_signal_ids=list(window.signal_ids),
                output_counts={"suggestions": 0},
                duration_ms=duration_ms,
                notes=list(window.notes) if window.notes else None,
            )
        )

        payload = {
            "success": True,
            "run_id": run_id,
            "project_name": project_name,
            "time_range": input_window["time_range"],
            "dimensions": input_window["dimensions"],
            "notes": list(window.notes),
            "signals_used": len(window.signal_ids),
        }
        print(json.dumps(payload, indent=2, default=str))
        await _list_recent_runs(backend, project_name)
    finally:
        await backend.close()


def main() -> None:
    project_name = sys.argv[1] if len(sys.argv) > 1 else "F--memory-lab"
    asyncio.run(_run(project_name))


if __name__ == "__main__":
    main()
