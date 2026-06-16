from __future__ import annotations

import argparse
import json
import platform
import statistics
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
from harness_mem.storage.canonical_store import (  # noqa: E402
    build_canonical_store,
    canonical_store_health,
    canonical_store_path,
    export_json_snapshot,
    read_compatible_payloads,
)


BENCHMARK_ID = "canonical_store_runtime_baseline"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def run_benchmark(args: argparse.Namespace) -> Path:
    if args.release_snapshot and not args.profile:
        raise SystemExit(
            "--release-snapshot requires --profile for canonical_store_runtime_baseline"
        )

    artifacts_root = Path(args.artifacts_root)
    run_dir = artifacts_root / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)
    entry_count = resolve_entry_count(args.entry_count, args.profile)

    with tempfile.TemporaryDirectory(prefix="hm-canonical-store-runtime-") as tmp:
        data_dir = Path(tmp) / "data"
        snapshot_dir = Path(tmp) / "snapshot"
        dataset = generate_v3_corpus(
            data_dir,
            entry_count=entry_count,
            project_count=args.project_count,
            seed=args.seed,
            payload_size_bytes=args.payload_size_bytes,
        )

        tracemalloc.start()
        build_start = time.perf_counter()
        build_result = build_canonical_store(data_dir)
        build_ms = (time.perf_counter() - build_start) * 1000

        sample_ms: list[float] = []
        health: dict[str, Any] = {}
        compatible_row_count = 0
        for _ in range(args.samples):
            sample_start = time.perf_counter()
            health = canonical_store_health(data_dir)
            compatible_row_count = len(read_compatible_payloads(data_dir))
            sample_ms.append((time.perf_counter() - sample_start) * 1000)

        export_result = export_json_snapshot(
            data_dir,
            snapshot_dir,
            apply=args.export_snapshot_apply,
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        db_path = canonical_store_path(data_dir)
        db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
        result = {
            "benchmark_id": BENCHMARK_ID,
            "operation": "canonical_store_runtime",
            "dataset_id": dataset["dataset_id"],
            "dataset_hash": dataset["dataset_hash"],
            "query_pack_id": "canonical-store-runtime-baseline",
            "command": " ".join(sys.argv),
            "hardware": platform.platform(),
            "commit": _git_commit(),
            "entry_count": entry_count,
            "corpus_profile": args.profile or "custom",
            "project_count": args.project_count,
            "json_file_count": corpus_json_file_count(data_dir),
            "canonical_row_count": build_result["canonical_row_count"],
            "checksum_match": bool(
                build_result["checksum_match"] and health.get("checksum_match")
            ),
            "p50_ms": round(statistics.median(sample_ms), 3),
            "p95_ms": round(percentile(sample_ms, 95), 3),
            "max_ms": round(max(sample_ms), 3) if sample_ms else 0.0,
            "build_ms": round(build_ms, 3),
            "sample_count": args.samples,
            "cold_start": True,
            "first_lazy_load": False,
            "warm_run": args.samples > 1,
            "rss_peak_mb": round(peak / (1024 * 1024), 3),
            "rss_source": "tracemalloc_python_peak",
            "disk_bytes": corpus_disk_bytes(data_dir),
            "db_size_bytes": db_size_bytes,
            "sidecar_size_bytes": 0,
            "fallback_reason": "canonical_store_contract_smoke",
            "claim_readiness": {
                "ready": False,
                "source": "v4.0.1 smoke",
                "blocking": ["requires_10k_100k_1m_release_runs"],
            },
            "accepted": "yes",
            "acceptance_notes": (
                "Canonical store contract smoke covers entity-table build, "
                "compatibility read path, health, and snapshot export surface; "
                "it is not Storage v2 speedup evidence."
            ),
        }

        write_dataset_manifest(run_dir, dataset)
        (run_dir / "results" / "canonical_store_runtime_baseline.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "build_result.json").write_text(
            json.dumps(build_result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "health.json").write_text(
            json.dumps(health, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "export_snapshot.json").write_text(
            json.dumps(export_result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "compatibility_read.json").write_text(
            json.dumps(
                {"compatible_row_count": compatible_row_count},
                indent=2,
                sort_keys=True,
            )
            + "\n",
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
        description="Run the canonical store runtime baseline benchmark."
    )
    parser.add_argument("--run-name", default="canonical-store-runtime-baseline")
    parser.add_argument("--artifacts-root", default=str(ROOT / "artifacts"))
    parser.add_argument("--profile", choices=["10k", "100k", "1m"])
    parser.add_argument("--entry-count", type=int, default=120)
    parser.add_argument("--project-count", type=int, default=3)
    parser.add_argument("--payload-size-bytes", type=int, default=512)
    parser.add_argument("--seed", type=int, default=4010)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--export-snapshot-apply", action="store_true")
    parser.add_argument("--release-snapshot", action="store_true")
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
