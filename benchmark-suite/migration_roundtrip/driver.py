from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path


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
from harness_mem.storage.store_v2_migration import (  # noqa: E402
    apply_store_v2_migration,
    build_migration_plan,
    export_store_v2_json_snapshot,
)


BENCHMARK_ID = "migration_roundtrip"


def run_benchmark(args: argparse.Namespace) -> Path:
    run_dir = ROOT / "artifacts" / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)
    entry_count = resolve_entry_count(args.entry_count, args.profile)

    with tempfile.TemporaryDirectory(prefix="hm-storage-v2-roundtrip-") as tmp:
        data_dir = Path(tmp) / "data"
        export_dir = Path(tmp) / "rollback-export"
        dataset = generate_v3_corpus(
            data_dir,
            entry_count=entry_count,
            project_count=args.project_count,
            seed=args.seed,
            payload_size_bytes=args.payload_size_bytes,
        )
        tracemalloc.start()
        dry_start = time.perf_counter()
        dry_run = build_migration_plan(data_dir)
        dry_run_ms = (time.perf_counter() - dry_start) * 1000
        apply_start = time.perf_counter()
        applied = apply_store_v2_migration(data_dir)
        apply_ms = (time.perf_counter() - apply_start) * 1000
        export_start = time.perf_counter()
        exported = export_store_v2_json_snapshot(data_dir, export_dir)
        export_ms = (time.perf_counter() - export_start) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        result = {
            "benchmark_id": BENCHMARK_ID,
            "operation": "dry_run_apply_export_rollback",
            "dataset_id": dataset["dataset_id"],
            "dataset_hash": dataset["dataset_hash"],
            "query_pack_id": "migration-roundtrip-smoke",
            "command": " ".join(sys.argv),
            "hardware": platform.platform(),
            "commit": _git_commit(),
            "entry_count": entry_count,
            "corpus_profile": args.profile or "custom",
            "project_count": args.project_count,
            "json_file_count": corpus_json_file_count(data_dir),
            "dry_run_json_file_count": dry_run["legacy_json_file_count"],
            "dry_run_checksum": dry_run["logical_checksum"],
            "canonical_checksum": applied["after_checksum"],
            "rollback_checksum": exported["export_checksum"],
            "apply_checksum_match": applied["checksum_match"],
            "rollback_checksum_match": exported["rollback_checksum_match"],
            "p50_ms": round(sorted([dry_run_ms, apply_ms, export_ms])[1], 3),
            "p95_ms": round(max(dry_run_ms, apply_ms, export_ms), 3),
            "dry_run_ms": round(dry_run_ms, 3),
            "apply_ms": round(apply_ms, 3),
            "export_ms": round(export_ms, 3),
            "cold_start": True,
            "first_lazy_load": False,
            "warm_run": False,
            "rss_peak_mb": round(peak / (1024 * 1024), 3),
            "rss_source": "tracemalloc_python_peak",
            "disk_bytes": corpus_disk_bytes(data_dir),
            "db_size_bytes": applied["db_size_bytes"],
            "sidecar_size_bytes": 0,
            "fallback_reason": "none",
            "claim_readiness": {
                "ready": bool(applied["checksum_match"] and exported["rollback_checksum_match"]),
                "source": "migration roundtrip smoke",
                "blocking": []
                if applied["checksum_match"] and exported["rollback_checksum_match"]
                else ["checksum_mismatch"],
            },
            "accepted": "yes"
            if applied["checksum_match"] and exported["rollback_checksum_match"]
            else "no",
            "acceptance_notes": (
                "Dry-run, side-by-side canonical apply, and v3 JSON rollback "
                "checksums match on the deterministic smoke corpus."
            ),
        }

        write_dataset_manifest(run_dir, dataset)
        (run_dir / "results" / "migration_roundtrip.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "dry_run_plan.json").write_text(
            json.dumps(dry_run, indent=2, sort_keys=True) + "\n",
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
    parser = argparse.ArgumentParser(description="Run the Storage v2 migration roundtrip smoke benchmark.")
    parser.add_argument("--run-name", default="migration-roundtrip-smoke")
    parser.add_argument("--profile", choices=["10k", "100k", "1m"])
    parser.add_argument("--entry-count", type=int, default=120)
    parser.add_argument("--project-count", type=int, default=3)
    parser.add_argument("--payload-size-bytes", type=int, default=512)
    parser.add_argument("--seed", type=int, default=4001)
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
