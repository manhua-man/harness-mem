"""Benchmark matrix and release regression gate summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_MATRIX_VERSION = "v3.4.2"

SURFACE_REGRESSION_TARGETS = {
    "wake": ["latency_warm_path", "client_enabled_vs_disabled"],
    "search": ["retrieval_quality_longmemeval", "retrieval_diagnostics"],
    "file_context": ["retrieval_diagnostics", "evidence_safety"],
    "wiki_compact": ["generated_knowledge_freshness"],
    "temporal_query": ["temporal_product_query"],
}

LONGMEMEVAL_DIMENSIONS = [
    "knowledge-update",
    "temporal-reasoning",
    "multi-session",
    "single-session-user",
    "single-session-assistant",
]


def benchmark_matrix_report(suite_root: Path | None = None) -> dict[str, Any]:
    """Read benchmark-suite metadata and return a release gate snapshot."""
    root = Path(suite_root) if suite_root is not None else Path("benchmark-suite")
    suite_path = root / "suite.json"
    collections = _read_collections(suite_path)
    collection_ids = {str(collection.get("id")) for collection in collections}
    surface_rows = []
    missing_surface_coverage: list[str] = []
    for surface, targets in SURFACE_REGRESSION_TARGETS.items():
        covered = [target for target in targets if target in collection_ids]
        missing = [target for target in targets if target not in collection_ids]
        if missing:
            missing_surface_coverage.append(surface)
        surface_rows.append(
            {
                "surface": surface,
                "smoke": bool(covered),
                "regression_collections": covered,
                "missing_collections": missing,
            }
        )

    artifact_runs = _artifact_runs(root / "artifacts")
    latest_run = artifact_runs[0] if artifact_runs else None
    accepted = sum(1 for run in artifact_runs if run.get("accepted") is True)
    failed = sum(1 for run in artifact_runs if run.get("accepted") is False)
    unknown = sum(1 for run in artifact_runs if run.get("accepted") is None)
    gate_passed = (
        not missing_surface_coverage
        and bool(artifact_runs)
        and failed == 0
        and unknown == 0
    )

    return {
        "success": True,
        "matrix_version": BENCHMARK_MATRIX_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy": {
            "use_cases": sorted(collection_ids),
            "methods": ["smoke", "regression", "release-snapshot"],
            "datasets": ["synthetic", "LongMemEval", "local-artifacts"],
            "dimensions": LONGMEMEVAL_DIMENSIONS,
        },
        "surfaces": surface_rows,
        "dimension_scores": [
            {"dimension": dimension, "status": "tracked"}
            for dimension in LONGMEMEVAL_DIMENSIONS
        ],
        "release_snapshot": {
            "artifact_run_count": len(artifact_runs),
            "accepted_runs": accepted,
            "failed_runs": failed,
            "unknown_runs": unknown,
            "latest_run": latest_run,
        },
        "gate": {
            "passed": gate_passed,
            "missing_surface_coverage": missing_surface_coverage,
            "failed_artifact_runs": failed,
            "unknown_artifact_runs": unknown,
            "has_artifacts": bool(artifact_runs),
        },
    }


def _read_collections(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    collections = data.get("collections", [])
    return collections if isinstance(collections, list) else []


def _artifact_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    runs: list[dict[str, Any]] = []
    for manifest in path.glob("*/run_manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        run_id = str(data.get("run_id") or manifest.parent.name)
        accepted = data.get("accepted")
        if accepted is None:
            accepted = _infer_report_acceptance(manifest.parent / "report.md")
        runs.append(
            {
                "run_id": run_id,
                "path": str(manifest.parent),
                "collection_id": data.get("collection_id") or data.get("suite_id"),
                "accepted": accepted,
            }
        )
    runs.sort(key=lambda item: str(item["run_id"]), reverse=True)
    return runs


def _infer_report_acceptance(path: Path) -> bool | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").lower()
    if "accepted: true" in text or "status: accepted" in text:
        return True
    if "accepted: false" in text or "status: failed" in text:
        return False
    return None


__all__ = ["BENCHMARK_MATRIX_VERSION", "benchmark_matrix_report"]
