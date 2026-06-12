from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLLECTION_DIR = Path(__file__).resolve().parent
SUITE_DIR = COLLECTION_DIR.parent
REPO_ROOT = SUITE_DIR.parent
ARTIFACTS = SUITE_DIR / "artifacts"
TOOLS_DIR = SUITE_DIR / "tools"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from render_report import build_report, write_summary_csv  # noqa: E402

from harness_mem import __version__ as HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.commands.support import get_embedding_model_id  # noqa: E402
from harness_mem.core.schemas import MemoryEntry  # noqa: E402
from harness_mem.embedding import embeddings_disabled, has_local_model_snapshot  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402


BENCHMARK_ID = "true_hybrid_retrieval_shootout"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


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
        "mean_ms": round(statistics.fmean(ordered), 3) if ordered else 0.0,
        "min_ms": round(min(ordered), 3) if ordered else 0.0,
        "max_ms": round(max(ordered), 3) if ordered else 0.0,
    }


def recall_at(retrieved_source_ids: list[str], expected_source_ids: list[str], k: int) -> float:
    expected = set(expected_source_ids)
    if not expected:
        return 0.0
    hits = expected.intersection(retrieved_source_ids[:k])
    return round(len(hits) / len(expected), 4)


def git_head(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={workspace.as_posix()}", "rev-parse", "HEAD"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_dirty(workspace: Path) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={workspace.as_posix()}", "status", "--short"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    return bool(result.stdout.strip()) if result.returncode == 0 else True


def build_run_dir(run_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return ARTIFACTS / f"{stamp}-{BENCHMARK_ID}-{run_name}"


def source_text(source_id: str) -> str:
    if source_id == "docs/benchmark/v162-embedding-shootout.md":
        return (
            "Which retrieval baseline is the default embedding anchor? "
            "The retrieval baseline default embedding anchor remains "
            "all-MiniLM-L6-v2. bge-small-en-v1.5 and "
            "nomic-embed-text-v1.5 are shootout candidates, not the default "
            "until later recall, latency, cache, disk, and install-friction "
            "evidence changes the baseline."
        )
    if source_id == "tests/temporal/test_current_history_reads.py":
        return (
            "What changed after a previous memory fact was superseded? "
            "Temporal truth keeps previous facts as history and reads the "
            "current replacement through valid_from, valid_to, recorded_at, "
            "supersedes, and superseded_by. Supersede explains what changed "
            "without autonomously deleting the older fact."
        )
    if source_id == "benchmark-suite/release-snapshot.json":
        return (
            "Which prior session evidence supports the release claim boundary? "
            "The release snapshot is the accepted benchmark evidence boundary. "
            "Public claims must use claim_readiness gates from release-snapshot "
            "and artifact results instead of borrowing codedb-mcp token, runtime, "
            "or code-intel benchmark scores."
        )
    return (
        f"Synthetic benchmark source {source_id}. This distractor is retained "
        "to make retrieval ranking non-trivial."
    )


async def seed_backend(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    queries: list[dict[str, Any]],
) -> None:
    source_ids = [source_id for query in queries for source_id in query["expected_source_ids"]]
    distractors = [
        "docs/reference-projects.md",
        "docs/roadmap-status.md",
        "benchmark-suite/client_enabled_vs_disabled/README.md",
        "benchmark-suite/latency_warm_path/driver.py",
        "harness_mem/benchmark_matrix.py",
    ]
    for index, source_id in enumerate([*source_ids, *distractors]):
        content = source_text(source_id)
        if source_id in distractors:
            content += (
                " This row is a nearby but non-oracle benchmark distractor for "
                "source-hit recall measurement."
            )
        entry = MemoryEntry(
            id=f"retrieval-shootout-{index:03d}",
            project_name=project_name,
            category="decision" if source_id in source_ids else "architecture",
            content=content,
            confidence=0.95 if source_id in source_ids else 0.65,
            source=source_id,
            tags=["benchmark-suite", BENCHMARK_ID],
        )
        await backend.structured_store.save_memory_entry(entry)


async def run_search(
    backend: LocalMemoryBackend,
    *,
    query: str,
    project_name: str,
    mode: str,
    limit: int,
) -> dict[str, Any]:
    extra_where = (
        "COALESCE(compacted, 0) = 0 "
        "AND COALESCE(status, 'accepted') = ? "
        "AND project_name = ?"
    )
    extra_params = ("accepted", project_name)
    search_layer = backend.structured_store._search
    if mode == "vector":
        result = await asyncio.to_thread(
            search_layer.search_vector,
            query,
            "memory_entries",
            limit,
            extra_where,
            extra_params,
        )
    else:
        result = await asyncio.to_thread(
            search_layer.search,
            query,
            "memory_entries",
            limit,
            extra_where,
            extra_params,
            mode,
        )
    return {
        "requested_mode": mode,
        "effective_mode": result.effective_mode,
        "fallback_reason": result.fallback_reason,
        "retrieved_entry_ids": [str(row.get("id") or "") for row in result.rows],
        "retrieved_source_ids": [
            str(row.get("source") or row.get("id") or "") for row in result.rows
        ],
    }


async def measure_query_mode(
    backend: LocalMemoryBackend,
    *,
    query_row: dict[str, Any],
    mode: str,
    project_name: str,
    limit: int,
    warmup: int,
    samples: int,
    model_id: str,
    environment: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    last_payload: dict[str, Any] = {}
    for _ in range(warmup):
        try:
            last_payload = await run_search(
                backend,
                query=query_row["query"],
                project_name=project_name,
                mode=mode,
                limit=limit,
            )
        except Exception as exc:
            errors.append(f"warmup: {type(exc).__name__}: {exc}")

    latencies_ms: list[float] = []
    started = time.perf_counter()
    for _ in range(samples):
        sample_started = time.perf_counter()
        try:
            last_payload = await run_search(
                backend,
                query=query_row["query"],
                project_name=project_name,
                mode=mode,
                limit=limit,
            )
            latencies_ms.append((time.perf_counter() - sample_started) * 1000)
        except Exception as exc:
            errors.append(f"sample: {type(exc).__name__}: {exc}")
    runtime_seconds = round(time.perf_counter() - started, 6)

    expected_source_ids = [str(item) for item in query_row["expected_source_ids"]]
    retrieved_source_ids = [
        str(item) for item in last_payload.get("retrieved_source_ids", [])
    ]
    fallback_reason = last_payload.get("fallback_reason")
    effective_mode = last_payload.get("effective_mode") or "missing"
    accepted = (
        "yes"
        if latencies_ms and not errors and effective_mode == mode and not fallback_reason
        else "no"
    )
    notes = (
        "Measured source-hit recall row."
        if accepted == "yes"
        else "Mode did not complete as requested; inspect errors or fallback_reason."
    )
    return {
        "query_id": query_row["query_id"],
        "query_type": query_row["query_type"],
        "query": query_row["query"],
        "mode": mode,
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "model_id": model_id,
        "expected_source_ids": expected_source_ids,
        "retrieved_source_ids": retrieved_source_ids,
        "retrieved_entry_ids": last_payload.get("retrieved_entry_ids", []),
        "recall_at_1": recall_at(retrieved_source_ids, expected_source_ids, 1),
        "recall_at_5": recall_at(retrieved_source_ids, expected_source_ids, 5),
        "recall_at_10": recall_at(retrieved_source_ids, expected_source_ids, 10),
        "runtime_seconds": runtime_seconds,
        "sample_count": len(latencies_ms),
        "warmup_count": warmup,
        "latencies_ms": [round(value, 3) for value in latencies_ms],
        **summarize_latencies(latencies_ms),
        "index_load_ms": 0.0,
        "fallback_reason": fallback_reason,
        "token_cost_estimate": 0,
        "fixture_only": False,
        "accepted": accepted,
        "acceptance_notes": notes,
        "errors": errors,
        "environment": environment,
        "cache_state": "warm",
        "hardware_note": platform.platform(),
    }


def build_manifest(args: argparse.Namespace, run_dir: Path, dataset_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_id": BENCHMARK_ID,
        "run_id": run_dir.name,
        "run_name": args.run_name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "client": "benchmark-suite-driver",
        "model": "local-runtime",
        "workspace_path": str(args.workspace),
        "dataset": dataset_manifest.get("dataset"),
        "split": dataset_manifest.get("split"),
        "sample_count": dataset_manifest.get("sample_count"),
        "repo_state": {
            "git_head": git_head(args.workspace),
            "git_dirty": git_dirty(args.workspace),
            "notes": "Driver uses isolated temporary harness-mem data unless --data-dir is provided.",
        },
        "operator_notes": [
            "True hybrid retrieval shootout driver.",
            "Retrieval recall is source-hit recall, not end-to-end answer correctness.",
            "fixture_only=false rows require fts/vector/hybrid to execute without fallback.",
        ],
    }


async def run_driver(args: argparse.Namespace, data_dir: Path, run_dir: Path) -> list[dict[str, Any]]:
    queries = load_json(COLLECTION_DIR / "queries.json")
    model_id = get_embedding_model_id()
    environment = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "workspace_path": str(args.workspace),
        "data_dir": str(data_dir),
        "harness_mem_version": HARNESS_MEM_VERSION,
        "embedding_disabled": embeddings_disabled(),
        "embedding_model_id": model_id,
        "embedding_model_cached": has_local_model_snapshot(model_id),
        "created_at": utc_now(),
    }

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        await seed_backend(backend, project_name=args.project_name, queries=queries)
        results: list[dict[str, Any]] = []
        for query_row in queries:
            for mode in ("fts", "vector", "hybrid"):
                result = await measure_query_mode(
                    backend,
                    query_row=query_row,
                    mode=mode,
                    project_name=args.project_name,
                    limit=args.limit,
                    warmup=args.warmup,
                    samples=args.samples,
                    model_id=model_id,
                    environment=environment,
                )
                results.append(result)
                write_json(
                    run_dir / "results" / f"{query_row['query_id']}-{mode}.json",
                    result,
                )
        return results
    finally:
        await backend.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run true hybrid retrieval shootout.")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--workspace", type=Path, default=REPO_ROOT)
    parser.add_argument("--project-name", default="benchmark-suite-retrieval-shootout")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    if args.warmup < 0:
        raise SystemExit("--warmup must be >= 0")
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    run_dir = build_run_dir(args.run_name)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "notes").mkdir()

    dataset_manifest = load_json(COLLECTION_DIR / "dataset.manifest.json")
    write_json(run_dir / "run_manifest.json", build_manifest(args, run_dir, dataset_manifest))
    shutil.copyfile(COLLECTION_DIR / "dataset.manifest.json", run_dir / "dataset.manifest.json")
    shutil.copyfile(COLLECTION_DIR / "queries.json", run_dir / "notes" / "queries.json")

    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        results = asyncio.run(run_driver(args, data_dir, run_dir))
    else:
        with tempfile.TemporaryDirectory(prefix="harness-mem-retrieval-shootout-") as tmp:
            results = asyncio.run(run_driver(args, Path(tmp), run_dir))

    write_summary_csv(run_dir, results, BENCHMARK_ID)
    (run_dir / "report.md").write_text(
        build_report(results, BENCHMARK_ID),
        encoding="utf-8",
    )
    (run_dir / "notes" / "method.md").write_text(
        (
            "Synthetic source-hit retrieval run from "
            "benchmark-suite/true_hybrid_retrieval_shootout/driver.py.\n"
            "Rows are fixture_only=false because they execute the local runtime "
            "search stack against a freshly seeded isolated data directory.\n"
        ),
        encoding="utf-8",
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
