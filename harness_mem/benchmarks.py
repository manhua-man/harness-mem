"""Performance benchmarks for harness-mem operations.

Measures latency and throughput for:
- ingest: session ingestion throughput
- search: FTS and hybrid search latency
- wake-up: context loading and budget calculation latency
"""

from __future__ import annotations
import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.core.schemas import Observation, MemoryEntry
from harness_mem.wake_selection import select_wake_memory_entries
from uuid import uuid4


async def benchmark_ingest(
    backend: LocalMemoryBackend,
    session_count: int = 100,
    observations_per_session: int = 50,
) -> dict[str, Any]:
    """Benchmark session ingestion.

    Creates mock sessions and measures ingestion throughput.
    Returns dict with timing metrics.
    """
    start = time.perf_counter()
    ingested = 0

    for i in range(session_count):
        session_id = f"bench-session-{i:04d}"
        for j in range(observations_per_session):
            obs = Observation(
                id=str(uuid4()),
                session_id=session_id,
                client="benchmark",
                raw_content=f"Benchmark observation {j} for session {i}: " + "x" * 200,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "benchmark-project"},
                tags=["benchmark"],
            )
            await backend.verbatim_store.save(obs)
            ingested += 1

    elapsed = time.perf_counter() - start
    return {
        "operation": "ingest",
        "total_items": ingested,
        "elapsed_seconds": round(elapsed, 3),
        "items_per_second": round(ingested / elapsed, 1) if elapsed > 0 else 0,
        "session_count": session_count,
        "observations_per_session": observations_per_session,
    }


async def benchmark_search(
    backend: LocalMemoryBackend,
    project_name: str = "benchmark-project",
    query_count: int = 20,
) -> dict[str, Any]:
    """Benchmark search operations.

    Measures FTS search latency and result quality.
    Returns dict with timing metrics.
    """
    queries = [
        "benchmark observation session",
        "performance measurement test",
        "harness-mem memory",
    ]

    latencies = []
    total_results = 0

    for i in range(query_count):
        query = queries[i % len(queries)]
        start = time.perf_counter()
        results = await backend.structured_store.search_memory_entries(
            query, project_name=project_name, limit=20
        )
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)
        total_results += len(results)

    avg_latency_ms = round(sum(latencies) / len(latencies) * 1000, 2)
    p95_latency_ms = round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if latencies else 0

    return {
        "operation": "search",
        "query_count": query_count,
        "total_results": total_results,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "queries_per_second": round(query_count / sum(latencies), 1) if sum(latencies) > 0 else 0,
    }


async def benchmark_wake_up(
    backend: LocalMemoryBackend,
    project_name: str = "benchmark-project",
    runs: int = 10,
) -> dict[str, Any]:
    """Benchmark wake-up context loading.

    Measures the full wake-up pipeline: profile + rules + entries + handoffs.
    Returns dict with timing metrics.
    """
    latencies = []

    for _ in range(runs):
        start = time.perf_counter()

        # Simulate wake-up data loading
        entry_candidates = await backend.structured_store.list_memory_entries(project_name, limit=50)
        entries = select_wake_memory_entries(entry_candidates, limit=5)
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)

        # Budget calculation
        entries_chars = sum(len(e.content or "") for e in entries)
        rules_chars = sum(len(r.trigger or "") + len(r.pattern or "") for r in rules)
        handoffs_chars = sum(len(h.summary or "") + len(str(h.next_steps)) + len(str(h.blockers)) for h in handoffs)
        _total = entries_chars + rules_chars + handoffs_chars

        elapsed = time.perf_counter() - start
        latencies.append(elapsed)

    avg_latency_ms = round(sum(latencies) / len(latencies) * 1000, 2)
    p95_latency_ms = round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2) if latencies else 0

    return {
        "operation": "wake-up",
        "runs": runs,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "total_ops_per_second": round(runs / sum(latencies), 1) if sum(latencies) > 0 else 0,
    }


async def benchmark_daily_wake_temporal_safety(
    backend: LocalMemoryBackend,
    project_name: str = "benchmark-project",
    limit: int = 5,
) -> dict[str, Any]:
    """Benchmark whether daily wake-up keeps old but critical memories.

    This is a gate for any future recency-biased default. A recency-only wake
    selection can look fresh while dropping older high-value decisions, so this
    benchmark reports that risk instead of changing wake behavior.
    """
    run_id = str(uuid4())[:8]
    old_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    critical_entry = MemoryEntry(
        id=f"wake-critical-{run_id}",
        project_name=project_name,
        category="decision",
        content=(
            "Critical stable decision: keep local-first storage and do not "
            "replace SQLite with an external service without explicit review."
        ),
        confidence=0.99,
        source="benchmark",
        created_at=old_date,
        updated_at=old_date,
        tags=["benchmark", "critical", "expected-wake"],
        usage_count=12,
        last_accessed_at=old_date,
    )
    await backend.structured_store.save_memory_entry(critical_entry)

    for index in range(limit + 2):
        created_at = recent_start + timedelta(days=index)
        routine_entry = MemoryEntry(
            id=f"wake-routine-{run_id}-{index}",
            project_name=project_name,
            category="note",
            content=f"Routine recent note {index}: transient daily implementation detail.",
            confidence=0.6,
            source="benchmark",
            created_at=created_at,
            updated_at=created_at,
            tags=["benchmark", "routine"],
        )
        await backend.structured_store.save_memory_entry(routine_entry)

    candidates = await backend.structured_store.list_memory_entries(project_name, limit=50)
    selected = select_wake_memory_entries(candidates, limit=limit)
    selected_ids = [entry.id for entry in selected]
    critical_retained = critical_entry.id in selected_ids
    displaced = [] if critical_retained else [critical_entry.id]

    return {
        "operation": "daily-wake-temporal-safety",
        "limit": limit,
        "expected_critical_count": 1,
        "critical_retained_count": 1 if critical_retained else 0,
        "critical_recall": 1.0 if critical_retained else 0.0,
        "critical_retained": critical_retained,
        "displaced_critical_ids": displaced,
        "selected_ids": selected_ids,
        "gate": "pass" if critical_retained else "fail",
        "reason": (
            "daily wake retained old critical memory"
            if critical_retained
            else "daily wake recency selection displaced old critical memory"
        ),
    }


async def run_benchmarks(tmp_path: Path | None = None) -> dict[str, Any]:
    """Run all benchmarks and return combined results.

    Args:
        tmp_path: Optional temp directory for benchmark data.

    Returns:
        Dict with all benchmark results keyed by operation name.
    """
    import tempfile
    data_dir = tmp_path or Path(tempfile.mkdtemp())
    backend = LocalMemoryBackend(data_dir)
    await backend.init()

    try:
        # Seed data for search benchmarks
        for i in range(10):
            entry = MemoryEntry(
                id=str(uuid4()),
                project_name="benchmark-project",
                category="architecture",
                content=f"Benchmark memory entry {i}: harness-mem performance measurement test data",
                confidence=0.8,
                source="benchmark",
            )
            await backend.structured_store.save_memory_entry(entry)

        results = {}

        results["ingest"] = await benchmark_ingest(backend)
        results["search"] = await benchmark_search(backend)
        results["wake-up"] = await benchmark_wake_up(backend)
        results["daily-wake-temporal-safety"] = await benchmark_daily_wake_temporal_safety(backend)

        return results

    finally:
        await backend.close()


def print_benchmark_results(results: dict[str, Any]) -> None:
    """Print benchmark results in a human-readable format."""
    print("\n=== harness-mem Performance Benchmarks ===\n")

    for op, data in results.items():
        print(f"[{op.upper()}]")
        for key, value in data.items():
            if key == "operation":
                continue
            if isinstance(value, float):
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")
        print()


if __name__ == "__main__":
    import tempfile
    import sys

    results = asyncio.run(run_benchmarks(Path(tempfile.mkdtemp())))
    print_benchmark_results(results)
    sys.exit(0)
