"""End-to-end smoke for the v2.3.0 signal chain — bypasses any running
MCP server, runs in-process against the real ~/.harness-mem/ data.

Sequence:
  1. Snapshot retrieval_signals row count.
  2. Call wake on a project that has confirmed rules (bazi-apps default).
  3. Call search_memory twice with broad queries.
  4. Snapshot row count again; print the delta + sample rows.

If the delta is zero, the signal write path is broken.
If the delta is non-zero, wake_surfaced / search_hit are wired correctly.

Run: python scripts/smoke_signal_chain.py [project_name] [search_query]
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys

from harness_mem.commands.support import DEFAULT_DATA_DIR
from harness_mem.commands.wake import cmd_wake_up
from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _count_signals() -> int:
    db = DEFAULT_DATA_DIR / "structured_index.sqlite"
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM retrieval_signals").fetchone()[0]
    finally:
        conn.close()


def _sample_signals(limit: int = 10) -> list[tuple]:
    db = DEFAULT_DATA_DIR / "structured_index.sqlite"
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT project_name, signal_type, target_kind, target_id, recorded_at "
            "FROM retrieval_signals ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return rows
    finally:
        conn.close()


async def _run(project_name: str, query: str) -> None:
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        before = _count_signals()
        print(f"baseline retrieval_signals row count: {before}")

        # cmd_wake_up is async but uses print(); capture stdout would be nicer
        # but for a smoke we just let it write — the row count delta is what
        # we care about.
        print(f"\n--- wake({project_name}) ---")
        try:
            await cmd_wake_up(project_name, no_auto_ingest=True)
        except SystemExit:
            pass  # cmd_wake_up may sys.exit on missing project

        after_wake = _count_signals()
        print(f"\nafter wake retrieval_signals row count: {after_wake} "
              f"(delta {after_wake - before})")

        print(f"\n--- search_memory({query!r}, project={project_name}) x2 ---")
        for i in range(2):
            entries, observations = await search_memory(
                backend,
                query=query,
                project_name=project_name,
                memory_entry_limit=5,
                observation_limit=5,
            )
            print(f"  call {i+1}: {len(entries)} entries + {len(observations)} observations")

        after_search = _count_signals()
        print(f"\nafter search retrieval_signals row count: {after_search} "
              f"(delta {after_search - after_wake})")

        print("\nrecent signal rows:")
        for row in _sample_signals(limit=10):
            print(f"  {row}")
    finally:
        await backend.close()


def main() -> None:
    project_name = sys.argv[1] if len(sys.argv) > 1 else "bazi-apps"
    query = sys.argv[2] if len(sys.argv) > 2 else "rule"
    asyncio.run(_run(project_name, query))


if __name__ == "__main__":
    main()
