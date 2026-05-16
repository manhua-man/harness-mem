"""v1.5.1 Pre-release Latency Baseline.
Measures 'wake-up' performance at different project scales and collects per-query search latency.
"""

import asyncio
import time
import statistics
import tempfile
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]

# Add parent dir to path
sys.path.append(str(REPO_ROOT))

from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.core.schemas import MemoryEntry, ConfirmedRule, TaskHandoff  # noqa: E402
from harness_mem.commands import cmd_wake_up  # noqa: E402

async def setup_bench_data(backend: LocalMemoryBackend, project_name: str, n_entries: int):
    """Setup project data with specific scale."""
    # Memory Entries
    for i in range(n_entries):
        entry = MemoryEntry(
            id=str(uuid4()),
            project_name=project_name,
            category="architecture",
            content=f"Scalability test entry {i} for {project_name}. This is a benchmark data point.",
            confidence=0.8,
            source="benchmark"
        )
        await backend.structured_store.save_memory_entry(entry)
    
    # Rules (fixed 5 for all scales to match wake_up logic)
    for i in range(5):
        rule = ConfirmedRule(
            id=str(uuid4()),
            project_name=project_name,
            pattern=f"pattern-{i}",
            trigger=f"trigger-{i}",
            confirmed_at=datetime.now(timezone.utc),
            source_candidate_id=str(uuid4())
        )
        await backend.structured_store.save_confirmed_rule(rule)
        
    # Handoffs (fixed 3)
    for i in range(3):
        handoff = TaskHandoff(
            id=str(uuid4()),
            project_name=project_name,
            task_id=f"task-{i}",
            summary=f"Summary for task {i}",
            status="done"
        )
        await backend.structured_store.save_task_handoff(handoff)

async def measure_wake_latency(project_name: str, runs: int = 10):
    """Measure cmd_wake_up latency directly."""
    latencies = []
    for _ in range(runs):
        start = time.perf_counter()
        # Suppress output for clean measurement
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            await cmd_wake_up(project_name)
        elapsed = time.perf_counter() - start
        latencies.append(elapsed * 1000) # ms
    
    p50 = statistics.median(latencies)
    sorted_lats = sorted(latencies)
    p95 = sorted_lats[int(len(sorted_lats) * 0.95)]
    return p50, p95

async def measure_search_latencies(backend: LocalMemoryBackend, project_name: str):
    """Collect per-query latencies for future v1.5.2 comparison."""
    queries = ["scalability test", "architecture", "benchmark data", "non-existent query", "test entry"]
    results = []
    for q in queries:
        start = time.perf_counter()
        await backend.structured_store.search_memory_entries(q, project_name=project_name)
        elapsed = (time.perf_counter() - start) * 1000
        results.append({"query": q, "latency_ms": round(elapsed, 2)})
    return results

async def main():
    data_dir = Path(tempfile.mkdtemp())
    print(f"Using temp data dir: {data_dir}")
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    
    # Patch the wake command stack to use the temp data dir for isolated benchmarking.
    from harness_mem.commands import support, wake
    support.DEFAULT_DATA_DIR = data_dir
    wake.DEFAULT_DATA_DIR = data_dir
    
    scales = [10, 100, 1000]
    baseline_report = ["# v1.5.1 Pre-release Latency Baseline\n"]
    baseline_report.append(f"Date: {datetime.now(timezone.utc).isoformat()}\n")
    
    baseline_report.append("## 1. Wake-up Latency (P50/P95)")
    baseline_report.append("| Scale (N) | P50 (ms) | P95 (ms) |")
    baseline_report.append("|-----------|----------|----------|")
    
    all_search_data = []

    for n in scales:
        project = f"bench-n{n}"
        print(f"Benchmarking Scale N={n}...")
        await setup_bench_data(backend, project, n)
        p50, p95 = await measure_wake_latency(project)
        baseline_report.append(f"| {n} | {p50:.2f} | {p95:.2f} |")
        
        # Collect search latency for v1.5.2 pre-work
        if n == 1000:
            all_search_data = await measure_search_latencies(backend, project)

    baseline_report.append("\n## 2. Search Latency Sample (N=1000, for v1.5.2 reference)")
    baseline_report.append("| Query | Latency (ms) |")
    baseline_report.append("|-------|--------------|")
    for item in all_search_data:
        baseline_report.append(f"| {item['query']} | {item['latency_ms']} |")

    await backend.close()
    
    # Output to markdown file
    report_path = REPO_ROOT / "docs" / "benchmark" / "v151-baseline.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(baseline_report), encoding="utf-8")
    print(f"\nBaseline report written to {report_path}")

if __name__ == "__main__":
    asyncio.run(main())
