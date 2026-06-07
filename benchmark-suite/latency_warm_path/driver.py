from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
ARTIFACTS = ROOT / "artifacts"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import __version__ as HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, Observation, TaskHandoff  # noqa: E402
from harness_mem.embedding import embeddings_disabled  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.wake_selection import select_wake_memory_entries  # noqa: E402


Operation = Callable[[], Awaitable[dict[str, Any]]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * pct
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    weight = pos - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def summarize_latencies(latencies_ms: list[float]) -> dict[str, float]:
    ordered = sorted(latencies_ms)
    return {
        "p50_ms": round(percentile(ordered, 0.50), 3),
        "p95_ms": round(percentile(ordered, 0.95), 3),
        "p99_ms": round(percentile(ordered, 0.99), 3),
        "max_ms": round(max(ordered), 3) if ordered else 0.0,
        "min_ms": round(min(ordered), 3) if ordered else 0.0,
        "mean_ms": round(statistics.fmean(ordered), 3) if ordered else 0.0,
    }


async def seed_backend(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    memory_entry_count: int,
    observation_count: int,
) -> None:
    for index in range(memory_entry_count):
        category = ["architecture", "decision", "convention", "api"][index % 4]
        entry = MemoryEntry(
            id=f"latency-entry-{index:04d}-{uuid4().hex[:8]}",
            project_name=project_name,
            category=category,
            content=(
                f"Warm path latency benchmark entry {index}. "
                "harness-mem uses SQLite FTS5, local-first storage, MCP read "
                "surfaces, wake context assembly, and benchmark isolation. "
                f"Category marker: {category}. "
                "Repeated query terms: latency warm path memory retrieval."
            ),
            confidence=0.9,
            source="benchmark-suite-latency-driver",
            tags=["benchmark-suite", "latency-warm-path", category],
        )
        await backend.structured_store.save_memory_entry(entry)

    for index in range(observation_count):
        observation = Observation(
            id=f"latency-observation-{index:04d}-{uuid4().hex[:8]}",
            session_id=f"latency-session-{index // 25:03d}",
            client="benchmark-suite",
            raw_content=(
                f"Observation {index}: warm path latency benchmark transcript "
                "mentions SQLite FTS5, wake recovery, memory retrieval, and "
                "isolated benchmark artifacts."
            ),
            content_type="transcript",
            metadata={"project_name": project_name},
            tags=["benchmark-suite", "latency-warm-path"],
        )
        await backend.verbatim_store.save(observation)

    for index in range(3):
        rule = ConfirmedRule(
            id=f"latency-rule-{index}-{uuid4().hex[:8]}",
            project_name=project_name,
            pattern=(
                "Keep benchmark drivers isolated from the product runtime and "
                "record fallback modes explicitly."
            ),
            trigger=f"latency benchmark rule {index}",
            examples=["Record effective_mode when hybrid falls back to FTS."],
            source_candidate_id=f"latency-candidate-{index}",
            source_session_id="latency-suite",
            tags=["benchmark-suite", "latency-warm-path"],
        )
        await backend.structured_store.save_confirmed_rule(rule)

    for index in range(3):
        handoff = TaskHandoff(
            id=f"latency-handoff-{index}-{uuid4().hex[:8]}",
            project_name=project_name,
            task_id=f"latency-task-{index}",
            summary=(
                "Warm path latency benchmark handoff with next steps for "
                "wake/search timing."
            ),
            status="in_progress",
            next_steps=["Run warm-up samples", "Render benchmark-suite report"],
            blockers=[],
            context={"benchmark_id": "latency_warm_path"},
        )
        await backend.structured_store.save_task_handoff(handoff)


async def measure_operation(
    *,
    task_id: str,
    operation_name: str,
    operation: Operation,
    warmup: int,
    samples: int,
    base_result: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    last_payload: dict[str, Any] = {}

    for _ in range(warmup):
        try:
            last_payload = await operation()
        except Exception as exc:
            errors.append(f"warmup: {type(exc).__name__}: {exc}")

    latencies_ms: list[float] = []
    started = time.perf_counter()
    for _ in range(samples):
        sample_started = time.perf_counter()
        try:
            last_payload = await operation()
            latencies_ms.append((time.perf_counter() - sample_started) * 1000)
        except Exception as exc:
            errors.append(f"sample: {type(exc).__name__}: {exc}")
    runtime_seconds = round(time.perf_counter() - started, 6)

    accepted = "yes" if latencies_ms and not errors else "no"
    summary = summarize_latencies(latencies_ms)
    result = {
        **base_result,
        "task_id": task_id,
        "condition": "warm",
        "runtime_seconds": runtime_seconds,
        "accepted": accepted,
        "acceptance_notes": (
            "Warm samples completed without errors."
            if accepted == "yes"
            else "One or more warm samples failed; inspect errors."
        ),
        "operation": operation_name,
        "sample_count": len(latencies_ms),
        "warmup_count": warmup,
        "error_count": len(errors),
        "errors": errors,
        "latencies_ms": [round(value, 3) for value in latencies_ms],
        **summary,
        **last_payload,
    }
    return result


def build_manifest(args: argparse.Namespace, run_name: str) -> dict[str, Any]:
    return {
        "benchmark_id": "latency_warm_path",
        "run_name": run_name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "client": "benchmark-suite-driver",
        "model": "local-runtime",
        "workspace_path": args.workspace,
        "repo_state": {
            "git_head": args.git_head or "unknown",
            "git_dirty": args.git_dirty,
            "notes": "Driver uses isolated temporary harness-mem data unless --data-dir is provided.",
        },
        "operator_notes": [
            "Warm path synthetic latency run.",
            "Hybrid search may fall back to FTS when embeddings or persisted vectors are unavailable.",
        ],
    }


def build_run_dir(run_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return ARTIFACTS / f"{stamp}-latency_warm_path-{run_name}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def build_report(results: list[dict[str, Any]], args: argparse.Namespace) -> str:
    lines = [
        "# Warm Path Latency Report",
        "",
        f"- Created: {utc_now()}",
        f"- Workspace: `{args.workspace}`",
        f"- Samples: `{args.samples}`",
        f"- Warm-up runs: `{args.warmup}`",
        f"- Memory entries: `{args.memory_entry_count}`",
        f"- Observations: `{args.observation_count}`",
        "",
        "| Task | Accepted | p50 ms | p95 ms | p99 ms | max ms | effective mode | fallback |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        lines.append(
            "| {task_id} | {accepted} | {p50_ms} | {p95_ms} | {p99_ms} | {max_ms} | {effective_mode} | {fallback_reason} |".format(
                task_id=result.get("task_id", ""),
                accepted=result.get("accepted", ""),
                p50_ms=result.get("p50_ms", ""),
                p95_ms=result.get("p95_ms", ""),
                p99_ms=result.get("p99_ms", ""),
                max_ms=result.get("max_ms", ""),
                effective_mode=result.get("effective_mode", ""),
                fallback_reason=result.get("fallback_reason") or "",
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Results are synthetic warm-path timings from an isolated benchmark data directory.",
            "- `search_hybrid` records `effective_mode` and `fallback_reason`; fallback to FTS is explicit.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_driver(args: argparse.Namespace, data_dir: Path, run_dir: Path) -> list[dict[str, Any]]:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        await seed_backend(
            backend,
            project_name=args.project_name,
            memory_entry_count=args.memory_entry_count,
            observation_count=args.observation_count,
        )

        base_result = {
            "environment": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "workspace_path": args.workspace,
                "data_dir": str(data_dir),
                "harness_mem_version": HARNESS_MEM_VERSION,
                "embedding_disabled": embeddings_disabled(),
            },
            "parameters": {
                "project_name": args.project_name,
                "memory_entry_count": args.memory_entry_count,
                "observation_count": args.observation_count,
                "query": args.query,
                "limit": args.limit,
            },
        }

        async def wake_synthetic() -> dict[str, Any]:
            entries = await backend.structured_store.list_memory_entries(
                args.project_name,
                limit=args.wake_candidate_limit,
            )
            selected = select_wake_memory_entries(entries, limit=args.wake_limit)
            rules = await backend.structured_store.list_confirmed_rules(args.project_name)
            handoffs = await backend.structured_store.get_latest_handoffs(
                args.project_name,
                limit=3,
            )
            return {
                "result_count_last_sample": len(selected) + len(rules) + len(handoffs),
                "selected_entry_count": len(selected),
                "confirmed_rule_count": len(rules),
                "handoff_count": len(handoffs),
                "requested_mode": "wake_synthetic",
                "effective_mode": "wake_synthetic",
                "fallback_reason": None,
            }

        async def search_fts() -> dict[str, Any]:
            results = await backend.structured_store.search_memory_entries(
                args.query,
                project_name=args.project_name,
                limit=args.limit,
                mode="fts",
            )
            effective_mode = getattr(results[0], "_search_mode", "fts") if results else "fts"
            fallback_reason = (
                getattr(results[0], "_search_fallback_reason", None) if results else None
            )
            return {
                "result_count_last_sample": len(results),
                "requested_mode": "fts",
                "effective_mode": effective_mode,
                "fallback_reason": fallback_reason,
            }

        async def search_hybrid() -> dict[str, Any]:
            results = await backend.structured_store.search_memory_entries(
                args.query,
                project_name=args.project_name,
                limit=args.limit,
                mode="hybrid",
            )
            effective_mode = getattr(results[0], "_search_mode", "hybrid") if results else "hybrid"
            fallback_reason = (
                getattr(results[0], "_search_fallback_reason", None) if results else None
            )
            return {
                "result_count_last_sample": len(results),
                "requested_mode": "hybrid",
                "effective_mode": effective_mode,
                "fallback_reason": fallback_reason,
            }

        tasks: list[tuple[str, str, Operation]] = [
            ("wake_synthetic", "wake synthetic selection", wake_synthetic),
            ("search_fts", "structured memory FTS search", search_fts),
            ("search_hybrid", "structured memory hybrid search", search_hybrid),
        ]

        results = []
        for task_id, operation_name, operation in tasks:
            result = await measure_operation(
                task_id=task_id,
                operation_name=operation_name,
                operation=operation,
                warmup=args.warmup,
                samples=args.samples,
                base_result=base_result,
            )
            results.append(result)
            write_json(run_dir / "results" / f"{task_id}.json", result)
        return results
    finally:
        await backend.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated warm-path latency benchmark.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--workspace", default=str(REPO_ROOT))
    parser.add_argument("--project-name", default="benchmark-suite-latency")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--memory-entry-count", type=int, default=200)
    parser.add_argument("--observation-count", type=int, default=100)
    parser.add_argument("--query", default="latency warm path memory retrieval")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--wake-candidate-limit", type=int, default=50)
    parser.add_argument("--wake-limit", type=int, default=5)
    parser.add_argument("--data-dir")
    parser.add_argument("--git-head")
    parser.add_argument("--git-dirty", action="store_true")
    args = parser.parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")
    if args.memory_entry_count < 1:
        raise SystemExit("--memory-entry-count must be >= 1")
    if args.observation_count < 0:
        raise SystemExit("--observation-count must be >= 0")
    return args


def main() -> int:
    args = parse_args()
    run_dir = build_run_dir(args.run_name)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "notes").mkdir()

    write_json(run_dir / "run_manifest.json", build_manifest(args, args.run_name))

    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        results = asyncio.run(run_driver(args, data_dir, run_dir))
    else:
        with tempfile.TemporaryDirectory(prefix="harness-mem-latency-") as tmp:
            results = asyncio.run(run_driver(args, Path(tmp), run_dir))

    (run_dir / "report.md").write_text(build_report(results, args), encoding="utf-8")
    (run_dir / "notes" / "method.md").write_text(
        "Synthetic warm-path latency run from benchmark-suite/latency_warm_path/driver.py.\n",
        encoding="utf-8",
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
