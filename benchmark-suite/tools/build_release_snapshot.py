from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
TOOLS_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "release-snapshot.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from harness_mem.benchmark_matrix import benchmark_matrix_report  # noqa: E402
from validate_release_snapshot import validate_release_snapshot  # noqa: E402


CLAIM_BOUNDARIES = {
    "auto_maintenance_effectiveness": (
        "audited maintenance behavior; not production long-run precision/recall"
    ),
    "canonical_store_runtime_baseline": (
        "canonical-store contract smoke; not default canonical-store enablement or speedup"
    ),
    "client_enabled_vs_disabled": (
        "paired correctness and memory-call gating; no token-saving or speedup claim"
    ),
    "evidence_safety": "guarded evidence-safety task set only",
    "functional_token_economics": (
        "feature-level fixture payload economics; not global token/cost or real billing savings"
    ),
    "context_sufficiency_gate": (
        "deterministic context sufficiency smoke; not end-to-end answer quality"
    ),
    "generated_knowledge_freshness": (
        "generated boundary and freshness checks; no perfect source-map coverage claim"
    ),
    "local_index_fabric_smoke": (
        "manifest-last sidecar contract smoke; not runtime SearchBackend readiness"
    ),
    "latency_warm_path": (
        "synthetic warm-path FTS/wake latency; not true vector-hybrid latency"
    ),
    "migration_roundtrip": (
        "dry-run/apply/export checksum smoke; not default canonical-store enablement"
    ),
    "runtime_health_observability": (
        "local health/cost/gate/false-success evidence; not real billing telemetry"
    ),
    "storage_v2_baseline": (
        "deterministic Storage v2 corpus and baseline schema smoke; not public speedup"
    ),
    "temporal_product_query": (
        "product temporal boundaries; not LongMemEval retrieval score"
    ),
    "true_hybrid_retrieval_shootout": (
        "fixture contract and governance only; not public retrieval recall or true vector-hybrid latency"
    ),
}


NON_RELEASE_ARTIFACT_STATES = {"diagnostic", "partial", "quarantined"}


def _include_in_release_snapshot(manifest: dict[str, Any]) -> bool:
    if manifest.get("release_snapshot") is False:
        return False
    state = str(manifest.get("artifact_state") or "").strip().lower()
    return state not in NON_RELEASE_ARTIFACT_STATES


def _normal_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "accepted", "pass", "passed"}:
            return True
        if normalized in {"no", "false", "failed", "fail", "rejected"}:
            return False
    return None


def _infer_results_acceptance(results_dir: Path) -> bool | None:
    result_files = sorted(results_dir.glob("*.json"))
    if not result_files:
        return None

    saw_accepted = False
    for result_file in result_files:
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        accepted = _normal_bool(payload.get("accepted"))
        if accepted is True:
            saw_accepted = True
            continue
        if accepted is False:
            return False
        return None
    return True if saw_accepted else None


def _run_summary(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    collection_id = (
        manifest.get("benchmark_id")
        or manifest.get("collection_id")
        or manifest.get("suite_id")
    )
    if not collection_id:
        raise SystemExit(f"{manifest_path}: missing benchmark_id/collection_id")

    results_dir = manifest_path.parent / "results"
    accepted = _normal_bool(manifest.get("accepted"))
    if accepted is None:
        accepted = _infer_results_acceptance(results_dir)

    run_id = str(manifest.get("run_id") or manifest_path.parent.name)
    run = {
        "run_id": run_id,
        "collection_id": str(collection_id),
        "accepted": accepted,
        "result_count": len(list(results_dir.glob("*.json"))),
        "claim_boundary": _claim_boundary(str(collection_id), run_id),
    }
    if manifest.get("artifact_state"):
        run["artifact_state"] = str(manifest["artifact_state"])
    return run


def _claim_boundary(collection_id: str, run_id: str) -> str:
    if collection_id == "client_enabled_vs_disabled" and "real-token" in run_id:
        return (
            "paired token-observed local task; measured delta is not a token-saving claim"
        )
    if collection_id == "latency_warm_path" and "true-hybrid" in run_id:
        return (
            "local synthetic true-hybrid warm-path probe; not broad production latency"
        )
    if collection_id == "true_hybrid_retrieval_shootout" and "real-local" in run_id:
        return (
            "local smoke source-hit retrieval recall across fts/vector/hybrid; "
            "not end-to-end answer correctness or broad corpus quality"
        )
    return CLAIM_BOUNDARIES.get(
        collection_id,
        "bounded artifact claim; inspect benchmark report before publishing",
    )


def build_release_snapshot(
    suite_root: Path = ROOT,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    runs = []
    for manifest_path in sorted((suite_root / "artifacts").glob("*/run_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not _include_in_release_snapshot(manifest):
            continue
        runs.append(_run_summary(manifest_path))
    accepted_runs = sum(1 for run in runs if run["accepted"] is True)
    failed_runs = sum(1 for run in runs if run["accepted"] is False)
    unknown_runs = sum(1 for run in runs if run["accepted"] is None)
    matrix = benchmark_matrix_report(suite_root)

    return {
        "snapshot_version": 2,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "validated local benchmark artifacts",
        "artifact_run_count": len(runs),
        "accepted_runs": accepted_runs,
        "failed_runs": failed_runs,
        "unknown_runs": unknown_runs,
        "gate_passed": failed_runs == 0 and unknown_runs == 0 and bool(runs),
        "claim_readiness": matrix["claim_readiness"],
        "retrieval_shootout": matrix["retrieval_shootout"],
        "runs": runs,
    }


def sync_package_resources(suite_root: Path, rendered_snapshot: str) -> None:
    package_root = suite_root.parent / "harness_mem" / "resources" / "benchmark_suite"
    if not package_root.exists():
        return
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "suite.json").write_text(
        (suite_root / "suite.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (package_root / "release-snapshot.json").write_text(
        rendered_snapshot,
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build benchmark-suite/release-snapshot.json from local artifacts."
    )
    parser.add_argument("--suite-root", default=str(ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="Fail if output differs.")
    parser.add_argument(
        "--sync-package-resources",
        action="store_true",
        help="Also sync harness_mem/resources/benchmark_suite fallback JSON.",
    )
    args = parser.parse_args()

    suite_root = Path(args.suite_root)
    output = Path(args.output)
    generated_at = None
    if output.exists():
        try:
            generated_at = json.loads(output.read_text(encoding="utf-8")).get("generated_at")
        except json.JSONDecodeError:
            generated_at = None
    payload = build_release_snapshot(suite_root, generated_at=generated_at)
    rendered = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"

    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else ""
        if current != rendered:
            raise SystemExit(f"{output}: release snapshot is stale")
    else:
        output.write_text(rendered, encoding="utf-8")
        if args.sync_package_resources:
            sync_package_resources(suite_root, rendered)

    validate_release_snapshot(output)
    print(f"OK: built release snapshot with {payload['artifact_run_count']} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
