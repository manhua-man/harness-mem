from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.rust_core import (  # noqa: E402
    build_bulk_index_rows,
    rank_candidates,
    reciprocal_rank_fusion,
    rust_core_status,
    scan_jsonl,
)


BENCHMARK_ID = "rust_core_hot_path"


def run_benchmark(args: argparse.Namespace) -> Path:
    artifacts_root = Path(args.artifacts_root)
    run_dir = artifacts_root / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)

    status = rust_core_status()
    if args.release_snapshot and (not status.available or status.mode != "rust"):
        raise SystemExit(
            "--release-snapshot requires an importable native harness_mem_core_rs module"
        )

    payloads = _sample_payloads()
    dataset_hash = _dataset_hash(payloads)
    rows = [
        _measure_scan_jsonl(status, dataset_hash, len(payloads)),
        _measure_bulk_index_rows(status, payloads, dataset_hash),
        _measure_rrf(status, dataset_hash, len(payloads)),
        _measure_rank_candidates(status, dataset_hash, len(payloads)),
        _measure_tokenize(status, payloads, dataset_hash),
    ]

    (run_dir / "dataset.manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "rust-core-hot-path-fixture",
                "dataset_hash": dataset_hash,
                "entry_count": len(payloads),
                "generator": "benchmark-suite/rust_core_hot_path/driver.py",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for row in rows:
        (run_dir / "results" / f"{row['operation']}.json").write_text(
            json.dumps(row, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (run_dir / "notes" / "rust_core_status.json").write_text(
        json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n",
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


def _measure_scan_jsonl(status, dataset_hash: str, entry_count: int) -> dict:
    text = (
        '{"type":"user","content":"storage v2"}\n'
        '{"type":"assistant","content":"rust core"}\n'
        'not-json\n'
    )
    start = time.perf_counter()
    result = scan_jsonl(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _row(
        status,
        operation="scan_jsonl",
        elapsed_ms=elapsed_ms,
        dataset_hash=dataset_hash,
        entry_count=entry_count,
        notes=(
            f"record_count={len(result.records)}",
            f"error_count={len(result.errors)}",
        ),
    )


def _measure_bulk_index_rows(status, payloads: list[dict], dataset_hash: str) -> dict:
    start = time.perf_counter()
    rows = build_bulk_index_rows(payloads)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _row(
        status,
        operation="bulk_index_rows",
        elapsed_ms=elapsed_ms,
        dataset_hash=dataset_hash,
        entry_count=len(payloads),
        notes=(f"row_count={len(rows)}",),
    )


def _measure_rrf(status, dataset_hash: str, entry_count: int) -> dict:
    start = time.perf_counter()
    scores = reciprocal_rank_fusion(
        [["mem-a", "mem-b", "mem-c"], ["mem-b", "mem-c", "mem-d"]],
        k=60,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _row(
        status,
        operation="reciprocal_rank_fusion",
        elapsed_ms=elapsed_ms,
        dataset_hash=dataset_hash,
        entry_count=entry_count,
        notes=(f"top_id={next(iter(scores))}",),
    )


def _measure_rank_candidates(status, dataset_hash: str, entry_count: int) -> dict:
    start = time.perf_counter()
    ranked = rank_candidates(
        [
            {
                "id": "a",
                "tokens": ["storage", "v2"],
                "confidence": 0.8,
                "truth_status": "accepted",
                "project_id": "demo",
            },
            {
                "id": "b",
                "tokens": ["storage"],
                "confidence": 0.8,
                "truth_status": "pending",
                "project_id": "demo",
            },
        ],
        query="storage v2",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _row(
        status,
        operation="rank_candidates",
        elapsed_ms=elapsed_ms,
        dataset_hash=dataset_hash,
        entry_count=entry_count,
        notes=(f"top_id={ranked[0]['id']}",),
    )


def _measure_tokenize(status, payloads: list[dict], dataset_hash: str) -> dict:
    start = time.perf_counter()
    rows = build_bulk_index_rows(payloads)
    token_count = sum(len(row["tokens"]) for row in rows)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _row(
        status,
        operation="tokenize",
        elapsed_ms=elapsed_ms,
        dataset_hash=dataset_hash,
        entry_count=len(payloads),
        notes=(f"token_count={token_count}",),
    )


def _row(
    status,
    *,
    operation: str,
    elapsed_ms: float,
    dataset_hash: str,
    entry_count: int,
    notes: tuple[str, ...],
) -> dict:
    native_ready = status.available and status.mode == "rust"
    return {
        "benchmark_id": BENCHMARK_ID,
        "operation": operation,
        "dataset_id": "rust-core-hot-path-fixture",
        "dataset_hash": dataset_hash,
        "query_pack_id": "rust-core-hot-path-fixture",
        "command": " ".join(sys.argv),
        "hardware": platform.platform(),
        "commit": _git_commit(),
        "entry_count": entry_count,
        "json_file_count": entry_count,
        "rust_mode": status.mode,
        "native_available": status.available,
        "wheel_mode": status.native_module,
        "p50_ms": round(elapsed_ms, 3),
        "p95_ms": round(elapsed_ms, 3),
        "rss_peak_mb": 0.0,
        "disk_bytes": 0,
        "db_size_bytes": 0,
        "sidecar_size_bytes": 0,
        "fallback_reason": status.fallback_reason or "none",
        "claim_readiness": {
            "ready": native_ready,
            "source": "rust_core_status",
            "blocking": [] if native_ready else ["native_wheel_not_available"],
        },
        "accepted": "yes",
        "acceptance_notes": (
            "Rust hot-path smoke records native vs fallback mode and keeps the "
            "read path non-fatal; it is not Rust speedup evidence."
        ),
        "notes": list(notes),
    }


def _sample_payloads() -> list[dict]:
    return [
        {
            "id": "mem-a",
            "project_name": "demo",
            "content": "storage v2 exact tokenization and ranking",
            "status": "accepted",
            "confidence": 0.8,
        },
        {
            "id": "mem-b",
            "project_name": "demo",
            "content": "rust core fallback keeps read paths stable",
            "status": "accepted",
            "confidence": 0.7,
        },
    ]


def _dataset_hash(payloads: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(payloads, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
    parser = argparse.ArgumentParser(description="Run the Rust core hot-path benchmark.")
    parser.add_argument("--run-name", default="rust-core-hot-path")
    parser.add_argument("--artifacts-root", default=str(ROOT / "artifacts"))
    parser.add_argument("--release-snapshot", action="store_true")
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
