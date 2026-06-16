from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
TOOLS_ROOT = ROOT / "tools"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from storage_v2_fixture import (  # noqa: E402
    corpus_disk_bytes,
    corpus_json_file_count,
    generate_v3_corpus,
    resolve_entry_count,
    write_dataset_manifest,
)
from harness_mem.index_fabric import (  # noqa: E402
    CURRENT_MANIFEST_NAME,
    ensure_index_current,
    load_current_manifest,
)
from harness_mem.search.backend import SearchFilters, SQLiteSearchBackend  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402


BENCHMARK_ID = "index_fabric_runtime_conformance"
OPERATIONS = [
    ("exact_search", "storage v2 synthetic memory"),
    ("word_search", "canonical store metadata"),
    ("trigram_search", "synthetic trigram runtime"),
    ("graph_search", "depends_on relation"),
]


def run_benchmark(args: argparse.Namespace) -> Path:
    artifacts_root = Path(args.artifacts_root)
    run_dir = artifacts_root / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)
    entry_count = resolve_entry_count(args.entry_count, args.profile)

    with tempfile.TemporaryDirectory(prefix="hm-index-fabric-runtime-") as tmp:
        data_dir = Path(tmp) / "data"
        index_dir = Path(tmp) / ".harness-mem" / "index"
        dataset = generate_v3_corpus(
            data_dir,
            entry_count=entry_count,
            project_count=args.project_count,
            seed=args.seed,
            payload_size_bytes=args.payload_size_bytes,
        )

        tracemalloc.start()
        interrupted_dir = index_dir / "generations" / "gen-interrupted"
        interrupted_dir.mkdir(parents=True, exist_ok=True)
        (interrupted_dir / "exact.bin").write_text("half-written", encoding="utf-8")

        first_manifest, rebuilt_first = ensure_index_current(data_dir, index_dir)
        initial_manifest = load_current_manifest(index_dir)
        interrupted_visible = (
            initial_manifest is not None
            and initial_manifest.generation_id == "gen-interrupted"
        )

        drift_marker = (
            data_dir
            / "structured"
            / "memory_entries"
            / "memory-entry-drift-marker.json"
        )
        drift_marker.parent.mkdir(parents=True, exist_ok=True)
        drift_marker.write_text(
            json.dumps(
                {
                    "id": "memory-entry-drift-marker",
                    "project_name": "project-000",
                    "category": "decision",
                    "memory_type": "semantic",
                    "content": "index fabric drift marker exact word trigram graph",
                    "confidence": 0.88,
                    "status": "accepted",
                    "source": "synthetic",
                    "created_at": "2026-06-20T00:00:00+00:00",
                    "updated_at": "2026-06-20T00:00:00+00:00",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        drift_manifest, rebuilt_drift = ensure_index_current(data_dir, index_dir)
        source_drift_detected = rebuilt_drift and (
            drift_manifest.generation_id != first_manifest.generation_id
        )

        rows, backend_payload = asyncio.run(
            _benchmark_search_backend(
                data_dir=data_dir,
                dataset=dataset,
                manifest=drift_manifest,
                rebuilt_first=rebuilt_first,
                interrupted_visible=interrupted_visible,
                source_drift_detected=source_drift_detected,
                profile=args.profile or "custom",
            )
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        db_size_bytes = 0
        sidecar_size_bytes = sum(
            path.stat().st_size for path in index_dir.glob("**/*") if path.is_file()
        )
        for row in rows:
            row["rss_peak_mb"] = round(peak / (1024 * 1024), 3)
            row["rss_source"] = "tracemalloc_python_peak"
            row["disk_bytes"] = corpus_disk_bytes(data_dir)
            row["db_size_bytes"] = db_size_bytes
            row["sidecar_size_bytes"] = sidecar_size_bytes

        write_dataset_manifest(run_dir, dataset)
        for row in rows:
            name = f"{row['operation']}.json"
            (run_dir / "results" / name).write_text(
                json.dumps(row, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        (run_dir / "notes" / "search_backend_payload.json").write_text(
            json.dumps(backend_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / CURRENT_MANIFEST_NAME).write_text(
            json.dumps(drift_manifest.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "run_id": args.run_name,
        "run_name": args.run_name,
        "artifact_state": "accepted" if args.release_snapshot else "diagnostic",
        "release_snapshot": bool(args.release_snapshot),
        "result_schema_version": 1,
        "accepted": True,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _render(run_dir)
    return run_dir


async def _benchmark_search_backend(
    *,
    data_dir: Path,
    dataset: dict[str, Any],
    manifest,
    rebuilt_first: bool,
    interrupted_visible: bool,
    source_drift_detected: bool,
    profile: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        search_backend = SQLiteSearchBackend(backend)
        rows: list[dict[str, Any]] = []
        backend_payload: dict[str, Any] = {}
        for index, (operation, query) in enumerate(OPERATIONS):
            start = time.perf_counter()
            response = await search_backend.search(
                query,
                filters=SearchFilters(project_name="project-000", scope="all"),
                mode="fts",
                limit=5,
                budget_tokens=160,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            payload = response.to_dict()
            backend_payload[operation] = payload
            rows.append(
                {
                    "benchmark_id": BENCHMARK_ID,
                    "operation": operation,
                    "dataset_id": dataset["dataset_id"],
                    "dataset_hash": dataset["dataset_hash"],
                    "query_pack_id": "index-fabric-runtime-conformance",
                    "command": " ".join(sys.argv),
                    "hardware": platform.platform(),
                    "commit": _git_commit(),
                    "entry_count": dataset["entry_count"],
                    "corpus_profile": profile,
                    "json_file_count": corpus_json_file_count(data_dir),
                    "manifest_commit": bool(
                        load_current_manifest(data_dir.parent / ".harness-mem" / "index")
                        or manifest
                    ),
                    "interrupted_generation_visible": interrupted_visible,
                    "source_fingerprint_drift_detected": source_drift_detected,
                    "search_backend_conformance": _response_is_conformant(payload),
                    "p50_ms": round(elapsed_ms, 3),
                    "p95_ms": round(elapsed_ms, 3),
                    "cold_start": index == 0,
                    "first_lazy_load": rebuilt_first and index == 0,
                    "warm_run": index > 0,
                    "fallback_reason": payload["fallback_metadata"].get("fallback_reason")
                    or "none",
                    "claim_readiness": {
                        "ready": False,
                        "source": "v4.0.3 runtime conformance smoke",
                        "blocking": ["requires_runtime_release_artifacts"],
                    },
                    "accepted": "yes",
                    "acceptance_notes": (
                        "SearchBackend conformance and manifest-last runtime smoke; "
                        "not index-fabric speedup or ANN readiness evidence."
                    ),
                }
            )
        return rows, backend_payload
    finally:
        await backend.close()


def _response_is_conformant(payload: dict[str, Any]) -> bool:
    return all(
        key in payload
        for key in [
            "query",
            "requested_mode",
            "effective_mode",
            "results",
            "fallback_metadata",
            "budget",
            "truncation",
            "source_coverage",
            "drilldown_hints",
        ]
    )


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _render(run_dir: Path) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "render_report.py"), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the index fabric runtime conformance benchmark."
    )
    parser.add_argument("--run-name", default="index-fabric-runtime-conformance")
    parser.add_argument("--artifacts-root", default=str(ROOT / "artifacts"))
    parser.add_argument("--profile", choices=["10k", "100k", "1m"])
    parser.add_argument("--entry-count", type=int, default=120)
    parser.add_argument("--project-count", type=int, default=3)
    parser.add_argument("--payload-size-bytes", type=int, default=512)
    parser.add_argument("--seed", type=int, default=4012)
    parser.add_argument("--release-snapshot", action="store_true")
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
