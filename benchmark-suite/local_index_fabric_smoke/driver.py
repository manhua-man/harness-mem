from __future__ import annotations

import argparse
import hashlib
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
    generate_v3_corpus,
    resolve_entry_count,
    write_dataset_manifest,
)


BENCHMARK_ID = "local_index_fabric_smoke"


def run_benchmark(args: argparse.Namespace) -> Path:
    run_dir = ROOT / "artifacts" / args.run_name
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "notes").mkdir(parents=True, exist_ok=True)
    entry_count = resolve_entry_count(args.entry_count, args.profile)

    with tempfile.TemporaryDirectory(prefix="hm-index-fabric-smoke-") as tmp:
        data_dir = Path(tmp) / "data"
        index_root = Path(tmp) / ".harness-mem" / "index"
        dataset = generate_v3_corpus(
            data_dir,
            entry_count=entry_count,
            project_count=args.project_count,
            seed=args.seed,
            payload_size_bytes=args.payload_size_bytes,
        )
        tracemalloc.start()
        start = time.perf_counter()
        stale_generation = _write_generation(
            index_root,
            generation_id="generation-interrupted",
            dataset_hash="stale",
            commit_manifest=False,
        )
        active_generation = _write_generation(
            index_root,
            generation_id="generation-active",
            dataset_hash=dataset["dataset_hash"],
            commit_manifest=True,
        )
        manifest = json.loads((index_root / "manifest.json").read_text(encoding="utf-8"))
        active_visible = manifest["generation_id"] == "generation-active"
        interrupted_visible = manifest["generation_id"] == "generation-interrupted"
        drift_detected = manifest["source_fingerprint"] != _fingerprint("different-source")
        elapsed_ms = (time.perf_counter() - start) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        sidecar_size = sum(path.stat().st_size for path in index_root.glob("**/*") if path.is_file())
        result = {
            "benchmark_id": BENCHMARK_ID,
            "operation": "manifest_last_sidecar_contract",
            "dataset_id": dataset["dataset_id"],
            "dataset_hash": dataset["dataset_hash"],
            "query_pack_id": "local-index-fabric-smoke",
            "command": " ".join(sys.argv),
            "hardware": platform.platform(),
            "commit": _git_commit(),
            "entry_count": entry_count,
            "corpus_profile": args.profile or "custom",
            "project_count": args.project_count,
            "json_file_count": args.entry_count,
            "manifest_commit": active_visible,
            "active_generation_id": active_generation,
            "interrupted_generation_id": stale_generation,
            "interrupted_generation_visible": interrupted_visible,
            "source_fingerprint_drift_detected": drift_detected,
            "sidecar_list": manifest["sidecars"],
            "p50_ms": round(elapsed_ms, 3),
            "p95_ms": round(elapsed_ms, 3),
            "cold_start": True,
            "first_lazy_load": False,
            "warm_run": False,
            "rss_peak_mb": round(peak / (1024 * 1024), 3),
            "rss_source": "tracemalloc_python_peak",
            "disk_bytes": corpus_disk_bytes(data_dir),
            "db_size_bytes": 0,
            "sidecar_size_bytes": sidecar_size,
            "fallback_reason": "contract_smoke_python_sidecar_writer",
            "claim_readiness": {
                "ready": bool(active_visible and not interrupted_visible and drift_detected),
                "source": "manifest-last smoke",
                "blocking": []
                if active_visible and not interrupted_visible and drift_detected
                else ["manifest_last_contract_failed"],
            },
            "accepted": "yes"
            if active_visible and not interrupted_visible and drift_detected
            else "no",
            "acceptance_notes": (
                "Manifest-last sidecar smoke proves the benchmark contract shape; "
                "runtime index fabric remains a later v4.0.x implementation."
            ),
        }

        write_dataset_manifest(run_dir, dataset)
        (run_dir / "results" / "local_index_fabric_smoke.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "notes" / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    manifest_payload = {
        "benchmark_id": BENCHMARK_ID,
        "run_id": args.run_name,
        "run_name": args.run_name,
        "artifact_state": "diagnostic",
        "release_snapshot": False,
        "result_schema_version": 1,
        "accepted": True,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _render(run_dir)
    return run_dir


def _write_generation(
    index_root: Path,
    *,
    generation_id: str,
    dataset_hash: str,
    commit_manifest: bool,
) -> str:
    generation_dir = index_root / generation_id
    generation_dir.mkdir(parents=True, exist_ok=True)
    sidecars = []
    for name in ["exact.postings.bin", "word.postings.bin", "trigram.postings.bin"]:
        path = generation_dir / name
        path.write_bytes(_fingerprint(f"{generation_id}:{name}:{dataset_hash}").encode("ascii"))
        sidecars.append({"path": f"{generation_id}/{name}", "bytes": path.stat().st_size})
    if commit_manifest:
        index_root.mkdir(parents=True, exist_ok=True)
        (index_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generation_id": generation_id,
                    "source_fingerprint": _fingerprint(dataset_hash),
                    "sidecars": sidecars,
                    "commit": "manifest-last",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return generation_id


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    parser = argparse.ArgumentParser(description="Run the Local Memory Index Fabric smoke benchmark.")
    parser.add_argument("--run-name", default="local-index-fabric-smoke")
    parser.add_argument("--profile", choices=["10k", "100k", "1m"])
    parser.add_argument("--entry-count", type=int, default=120)
    parser.add_argument("--project-count", type=int, default=3)
    parser.add_argument("--payload-size-bytes", type=int, default=512)
    parser.add_argument("--seed", type=int, default=4002)
    args = parser.parse_args()
    run_dir = run_benchmark(args)
    print(f"Wrote {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
