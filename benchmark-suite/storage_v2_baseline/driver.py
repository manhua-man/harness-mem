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
from harness_mem.storage.store_v2_migration import build_migration_plan  # noqa: E402


BENCHMARK_ID = "storage_v2_baseline"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def run_benchmark(args: argparse.Namespace) -> Path:
    run_dir = ROOT / "artifacts" / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)
    entry_count = resolve_entry_count(args.entry_count, args.profile)

    with tempfile.TemporaryDirectory(prefix="hm-storage-v2-baseline-") as tmp:
        data_dir = Path(tmp) / "data"
        tracemalloc.start()
        start = time.perf_counter()
        dataset = generate_v3_corpus(
            data_dir,
            entry_count=entry_count,
            project_count=args.project_count,
            seed=args.seed,
            payload_size_bytes=args.payload_size_bytes,
        )
        generate_seconds = time.perf_counter() - start

        scan_samples: list[float] = []
        plan: dict[str, Any] = {}
        for _ in range(args.samples):
            sample_start = time.perf_counter()
            plan = build_migration_plan(data_dir)
            scan_samples.append((time.perf_counter() - sample_start) * 1000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        result = {
            "benchmark_id": BENCHMARK_ID,
            "operation": "legacy_json_scan",
            "dataset_id": dataset["dataset_id"],
            "dataset_hash": dataset["dataset_hash"],
            "query_pack_id": "storage-v2-baseline-smoke",
            "command": " ".join(sys.argv),
            "hardware": platform.platform(),
            "commit": _git_commit(),
            "entry_count": entry_count,
            "corpus_profile": args.profile or "custom",
            "project_count": args.project_count,
            "entry_mix": dataset["entry_mix"],
            "payload_size_bytes": args.payload_size_bytes,
            "json_file_count": corpus_json_file_count(data_dir),
            "legacy_json_file_count": plan.get("legacy_json_file_count", 0),
            "p50_ms": round(statistics.median(scan_samples), 3),
            "p95_ms": round(percentile(scan_samples, 95), 3),
            "max_ms": round(max(scan_samples), 3) if scan_samples else 0.0,
            "generate_ms": round(generate_seconds * 1000, 3),
            "sample_count": args.samples,
            "cold_start": True,
            "first_lazy_load": False,
            "warm_run": args.samples > 1,
            "rss_peak_mb": round(peak / (1024 * 1024), 3),
            "rss_source": "tracemalloc_python_peak",
            "disk_bytes": corpus_disk_bytes(data_dir),
            "db_size_bytes": 0,
            "sidecar_size_bytes": 0,
            "fallback_reason": "contract_smoke_no_default_storage_change",
            "claim_readiness": {
                "ready": False,
                "source": "v4.0.0 smoke",
                "blocking": ["requires_10k_100k_1m_release_runs"],
            },
            "accepted": "yes",
            "acceptance_notes": (
                "Deterministic synthetic corpus and artifact schema smoke; "
                "not a public performance claim."
            ),
        }

        write_dataset_manifest(run_dir, dataset)
        (run_dir / "results" / "storage_v2_baseline.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "dry_run_plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "run_id": args.run_name,
        "run_name": args.run_name,
        "artifact_state": "diagnostic",
        "release_snapshot": False,
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
    parser = argparse.ArgumentParser(description="Run the Storage v2 baseline smoke benchmark.")
    parser.add_argument("--run-name", default="storage-v2-baseline-smoke")
    parser.add_argument("--profile", choices=["10k", "100k", "1m"])
    parser.add_argument("--entry-count", type=int, default=120)
    parser.add_argument("--project-count", type=int, default=3)
    parser.add_argument("--payload-size-bytes", type=int, default=512)
    parser.add_argument("--seed", type=int, default=4000)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
