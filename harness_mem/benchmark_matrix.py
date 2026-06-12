"""Benchmark matrix and release regression gate summaries."""

from __future__ import annotations

import json
from importlib import resources
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_MATRIX_VERSION = "v4.1.0"

ARTIFACT_STATES = ["accepted", "partial", "failed", "quarantined"]

RETRIEVAL_SHOOTOUT_COLLECTION_ID = "true_hybrid_retrieval_shootout"
RETRIEVAL_SHOOTOUT_MODES = ["fts", "vector", "hybrid"]
EMBEDDING_BASELINE = "all-MiniLM-L6-v2"
EMBEDDING_SHOOTOUT_CANDIDATES = [
    "all-MiniLM-L6-v2",
    "bge-small-en-v1.5",
    "nomic-embed-text-v1.5",
]

SURFACE_REGRESSION_TARGETS = {
    "wake": ["latency_warm_path", "client_enabled_vs_disabled"],
    "search": ["retrieval_quality_longmemeval", "retrieval_diagnostics"],
    "file_context": ["retrieval_diagnostics", "evidence_safety"],
    "wiki_compact": ["generated_knowledge_freshness"],
    "temporal_query": ["temporal_product_query"],
    "storage_v2": ["storage_v2_baseline", "migration_roundtrip"],
    "canonical_store": ["canonical_store_runtime_baseline"],
    "rust_core": ["rust_core_hot_path"],
    "index_fabric": ["local_index_fabric_smoke", "index_fabric_runtime_conformance"],
    "lifecycle_tiering": ["canonical_store_runtime_baseline"],
    "context_sufficiency": ["context_sufficiency_gate"],
    "task_aware_wake": ["task_aware_wake_precision"],
}

LONGMEMEVAL_DIMENSIONS = [
    "knowledge-update",
    "temporal-reasoning",
    "multi-session",
    "single-session-user",
    "single-session-assistant",
]

_RESOURCE_PACKAGE = "harness_mem.resources.benchmark_suite"


def _read_resource_json(name: str) -> dict[str, Any] | None:
    try:
        return json.loads(resources.files(_RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError):
        return None


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

    artifacts_path = root / "artifacts"
    snapshot_path = root / "release-snapshot.json"
    artifact_runs = _artifact_runs(artifacts_path)
    has_raw_artifacts = bool(artifact_runs)
    claim_readiness = (
        _artifact_claim_readiness(artifacts_path)
        if has_raw_artifacts
        else _snapshot_claim_readiness(snapshot_path)
    )
    if not artifact_runs:
        artifact_runs = _snapshot_runs(snapshot_path)
    latest_run = artifact_runs[0] if artifact_runs else None
    accepted = sum(1 for run in artifact_runs if run.get("artifact_state") == "accepted")
    failed = sum(1 for run in artifact_runs if run.get("artifact_state") in {"failed", "quarantined"})
    unknown = sum(1 for run in artifact_runs if run.get("artifact_state") == "partial")
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
            "purpose_map": _purpose_map(collections),
            "methods": ["smoke", "regression", "release-snapshot"],
            "datasets": ["synthetic", "LongMemEval", "local-artifacts"],
            "dimensions": LONGMEMEVAL_DIMENSIONS,
            "artifact_states": ARTIFACT_STATES,
            "embedding_baseline": EMBEDDING_BASELINE,
            "embedding_candidates": EMBEDDING_SHOOTOUT_CANDIDATES,
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
        "retrieval_shootout": _retrieval_shootout_summary(
            artifact_results=(
                _artifact_results(artifacts_path, RETRIEVAL_SHOOTOUT_COLLECTION_ID)
                if has_raw_artifacts
                else []
            ),
            snapshot_path=snapshot_path,
            allow_packaged_snapshot=not suite_path.exists() and not has_raw_artifacts,
        ),
        "claim_readiness": claim_readiness,
        "gate": {
            "passed": gate_passed,
            "missing_surface_coverage": missing_surface_coverage,
            "failed_artifact_runs": failed,
            "unknown_artifact_runs": unknown,
            "has_artifacts": bool(artifact_runs),
        },
    }


def _read_collections(path: Path) -> list[dict[str, Any]]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = _read_resource_json("suite.json")
    if not isinstance(data, dict):
        return []
    collections = data.get("collections", [])
    return collections if isinstance(collections, list) else []


def _purpose_map(collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for collection in collections:
        collection_id = str(collection.get("id") or "")
        if not collection_id:
            continue
        rows.append(
            {
                "id": collection_id,
                "title": str(collection.get("title") or collection_id),
                "purpose": str(collection.get("purpose") or "release regression evidence"),
                "proves": list(collection.get("proves") or []),
                "does_not_prove": list(collection.get("does_not_prove") or []),
                "artifact_requirements": list(collection.get("artifact_requirements") or []),
            }
        )
    return rows


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
        if accepted is None:
            accepted = _infer_results_acceptance(manifest.parent / "results")
        runs.append(
            {
                "run_id": run_id,
                "path": str(manifest.parent),
                "collection_id": (
                    data.get("benchmark_id")
                    or data.get("collection_id")
                    or data.get("suite_id")
                ),
                "artifact_state": _artifact_state(data, accepted),
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


def _artifact_claim_readiness(path: Path) -> dict[str, Any]:
    return {
        "token_cost_saving": _token_cost_saving_readiness(
            _artifact_results(path, "client_enabled_vs_disabled")
        ),
        "true_vector_hybrid_latency": _true_vector_hybrid_readiness(
            _artifact_results(path, "latency_warm_path")
        ),
        "retrieval_recall": _retrieval_recall_readiness(
            _artifact_results(path, RETRIEVAL_SHOOTOUT_COLLECTION_ID)
        ),
    }


def _artifact_results(path: Path, benchmark_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    accepted_runs: list[tuple[str, list[dict[str, Any]]]] = []
    for manifest in path.glob("*/run_manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        collection_id = data.get("benchmark_id") or data.get("collection_id") or data.get("suite_id")
        if collection_id != benchmark_id:
            continue
        accepted = data.get("accepted")
        if accepted is None:
            accepted = _infer_report_acceptance(manifest.parent / "report.md")
        if accepted is None:
            accepted = _infer_results_acceptance(manifest.parent / "results")
        if _artifact_state(data, accepted) != "accepted":
            continue
        results_dir = manifest.parent / "results"
        if not results_dir.exists():
            continue
        rows: list[dict[str, Any]] = []
        for result_file in sorted(results_dir.glob("*.json")):
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        if rows:
            accepted_runs.append((str(data.get("run_id") or manifest.parent.name), rows))
    accepted_runs.sort(key=lambda item: item[0], reverse=True)
    return accepted_runs[0][1] if accepted_runs else []


def _token_cost_saving_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "ready": False,
            "dimension": "cost_discipline",
            "source": "artifact-results",
            "blocking": ["client_enabled_vs_disabled/missing"],
        }

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("task_id") or ""), {})[str(row.get("condition") or "")] = row

    blockers: list[str] = []
    for task_id, pair in sorted(grouped.items()):
        if not task_id:
            blockers.append("unknown_task/missing_task_id")
            continue
        for condition in ("enabled", "disabled"):
            result_row = pair.get(condition)
            if result_row is None:
                blockers.append(f"{task_id}/{condition}/missing")
                continue
            if not _has_named_token_total(result_row):
                blockers.append(f"{task_id}/{condition}/token_total_unavailable")
        enabled_total = _named_token_total(pair.get("enabled"))
        disabled_total = _named_token_total(pair.get("disabled"))
        if enabled_total is not None and disabled_total is not None:
            delta = disabled_total - enabled_total
            if delta <= 0:
                blockers.append(f"{task_id}/token_delta_not_saving={int(delta)}")

    return {
        "ready": not blockers,
        "dimension": "cost_discipline",
        "source": "artifact-results",
        "blocking": blockers,
    }


def _has_named_token_total(row: dict[str, Any]) -> bool:
    return _named_token_total(row) is not None


def _named_token_total(row: dict[str, Any] | None) -> float | None:
    if row is None:
        return None
    usage = row.get("token_usage")
    if isinstance(usage, dict):
        source = str(usage.get("source") or "")
        total = _safe_float(usage.get("total"))
        if usage.get("available") is True and source not in {"", "unavailable"}:
            return total
        return None
    return _safe_float(row.get("token_total"))


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _true_vector_hybrid_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hybrid_rows = [
        row
        for row in rows
        if row.get("requested_mode") == "hybrid" or row.get("task_id") == "search_hybrid"
    ]
    if not hybrid_rows:
        return {
            "ready": False,
            "dimension": "performance",
            "source": "artifact-results",
            "blocking": ["search_hybrid/missing"],
        }

    blockers: list[str] = []
    for row in hybrid_rows:
        task_id = str(row.get("task_id") or "unknown")
        accepted = row.get("accepted")
        effective_mode = row.get("effective_mode") or "missing"
        fallback_reason = row.get("fallback_reason") or "none"
        if accepted != "yes":
            blockers.append(f"{task_id}/accepted={accepted or 'missing'}")
        if effective_mode != "hybrid" or fallback_reason != "none":
            blockers.append(
                f"{task_id}/effective_mode={effective_mode}/fallback_reason={fallback_reason}"
            )

    return {
        "ready": not blockers,
        "dimension": "performance",
        "source": "artifact-results",
        "blocking": blockers,
    }


def _retrieval_recall_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "ready": False,
            "dimension": "retrieval_recall",
            "source": "artifact-results",
            "blocking": [f"{RETRIEVAL_SHOOTOUT_COLLECTION_ID}/missing"],
        }

    modes_seen: set[str] = set()
    blockers: list[str] = []
    for row in rows:
        task_id = str(row.get("query_id") or row.get("task_id") or "unknown")
        mode = str(row.get("mode") or row.get("retrieval_mode") or "")
        if mode:
            modes_seen.add(mode)
        if mode not in RETRIEVAL_SHOOTOUT_MODES:
            blockers.append(f"{task_id}/mode={mode or 'missing'}")
        if row.get("accepted") not in {"yes", True, "true", "accepted", "pass", "passed"}:
            blockers.append(f"{task_id}/accepted={row.get('accepted') or 'missing'}")
        if row.get("fixture_only") is True:
            blockers.append(f"{task_id}/fixture_only")
        if _safe_float(row.get("recall_at_5")) is None and _safe_float(row.get("r_at_5")) is None:
            blockers.append(f"{task_id}/recall_at_5/missing")
        expected = row.get("expected_source_ids")
        if not isinstance(expected, list) or not expected:
            blockers.append(f"{task_id}/expected_source_ids/missing")

    missing_modes = [mode for mode in RETRIEVAL_SHOOTOUT_MODES if mode not in modes_seen]
    blockers.extend(f"mode/{mode}/missing" for mode in missing_modes)
    return {
        "ready": not blockers,
        "dimension": "retrieval_recall",
        "source": "artifact-results",
        "blocking": blockers,
    }


def _retrieval_shootout_summary(
    *,
    artifact_results: list[dict[str, Any]],
    snapshot_path: Path,
    allow_packaged_snapshot: bool = False,
) -> dict[str, Any]:
    rows = artifact_results
    source = "artifact-results"
    if not rows:
        snapshot = (
            _read_snapshot_json(snapshot_path)
            if snapshot_path.exists() or allow_packaged_snapshot
            else None
        )
        snapshot_summary = snapshot.get("retrieval_shootout") if snapshot else None
        if isinstance(snapshot_summary, dict):
            return {
                **snapshot_summary,
                "default_embedding_baseline": snapshot_summary.get(
                    "default_embedding_baseline",
                    EMBEDDING_BASELINE,
                ),
                "embedding_candidates": snapshot_summary.get(
                    "embedding_candidates",
                    EMBEDDING_SHOOTOUT_CANDIDATES,
                ),
                "source": snapshot_summary.get("source", "release-snapshot"),
            }
        rows = []
        source = "missing"

    query_ids = {
        str(row.get("query_id") or row.get("task_id") or "")
        for row in rows
        if row.get("query_id") or row.get("task_id")
    }
    modes = sorted(
        {
            str(row.get("mode") or row.get("retrieval_mode") or "")
            for row in rows
            if row.get("mode") or row.get("retrieval_mode")
        }
    )
    fallback_count = sum(1 for row in rows if row.get("fallback_reason") not in {None, "", "none"})
    readiness = _retrieval_recall_readiness(rows)
    return {
        "source": source,
        "ready": readiness["ready"],
        "query_count": len(query_ids),
        "modes": modes,
        "fallback_count": fallback_count,
        "default_embedding_baseline": EMBEDDING_BASELINE,
        "embedding_candidates": EMBEDDING_SHOOTOUT_CANDIDATES,
        "blocking": readiness["blocking"],
    }


def _snapshot_claim_readiness(path: Path) -> dict[str, Any]:
    data = _read_snapshot_json(path)
    if data is None:
        return _missing_claim_readiness("missing-or-invalid-snapshot")
    readiness = data.get("claim_readiness")
    if isinstance(readiness, dict):
        return readiness
    return _missing_claim_readiness("snapshot-without-claim-readiness")


def _missing_claim_readiness(reason: str) -> dict[str, Any]:
    return {
        "token_cost_saving": {
            "ready": False,
            "dimension": "cost_discipline",
            "source": reason,
            "blocking": ["client_enabled_vs_disabled/missing"],
        },
        "true_vector_hybrid_latency": {
            "ready": False,
            "dimension": "performance",
            "source": reason,
            "blocking": ["search_hybrid/missing"],
        },
        "retrieval_recall": {
            "ready": False,
            "dimension": "retrieval_recall",
            "source": reason,
            "blocking": [f"{RETRIEVAL_SHOOTOUT_COLLECTION_ID}/missing"],
        },
    }


def _infer_results_acceptance(path: Path) -> bool | None:
    if not path.exists():
        return None
    result_files = sorted(path.glob("*.json"))
    if not result_files:
        return None

    saw_accepted = False
    for result_file in result_files:
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        value = data.get("accepted")
        if value is True or _normal_bool(value) is True:
            saw_accepted = True
            continue
        if value is False or _normal_bool(value) is False:
            return False
        return None
    return True if saw_accepted else None


def _normal_bool(value: Any) -> bool | None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "accepted", "pass", "passed"}:
            return True
        if normalized in {"no", "false", "failed", "fail", "rejected"}:
            return False
    return None


def _snapshot_runs(path: Path) -> list[dict[str, Any]]:
    data = _read_snapshot_json(path)
    if data is None:
        return []
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        return []

    out: list[dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("run_id") or "")
        if not run_id:
            continue
        accepted = item.get("accepted")
        if accepted is None:
            accepted = _normal_bool(item.get("accepted"))
        out.append(
            {
                "run_id": run_id,
                "path": str(path),
                "collection_id": item.get("collection_id"),
                "artifact_state": _snapshot_artifact_state(item),
                "accepted": accepted,
            }
        )
    out.sort(key=lambda item: str(item["run_id"]), reverse=True)
    return out


def _read_snapshot_json(path: Path) -> dict[str, Any] | None:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if _valid_snapshot_payload(data) else None
    data = _read_resource_json("release-snapshot.json")
    return data if _valid_snapshot_payload(data) else None


def _valid_snapshot_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("snapshot_version") != 2:
        return False
    if not _non_empty_string(data.get("generated_at")):
        return False
    if not _non_empty_string(data.get("source")):
        return False

    counts = {
        field: _non_negative_int(data.get(field))
        for field in [
            "artifact_run_count",
            "accepted_runs",
            "failed_runs",
            "unknown_runs",
        ]
    }
    if any(value is None for value in counts.values()):
        return False
    if not isinstance(data.get("gate_passed"), bool):
        return False

    runs = data.get("runs")
    if not isinstance(runs, list):
        return False
    if len(runs) != counts["artifact_run_count"]:
        return False

    accepted = failed = unknown = 0
    for item in runs:
        if not isinstance(item, dict):
            return False
        for field in ["run_id", "collection_id", "claim_boundary"]:
            if not _non_empty_string(item.get(field)):
                return False
        accepted_value = item.get("accepted")
        if accepted_value is True:
            accepted += 1
        elif accepted_value is False:
            failed += 1
        elif accepted_value is None:
            unknown += 1
        else:
            return False

    if accepted != counts["accepted_runs"]:
        return False
    if failed != counts["failed_runs"]:
        return False
    if unknown != counts["unknown_runs"]:
        return False
    if data["gate_passed"] != (failed == 0 and unknown == 0 and bool(runs)):
        return False

    readiness = data.get("claim_readiness")
    if not isinstance(readiness, dict) or not all(
        _valid_claim_gate(readiness.get(key))
        for key in ["token_cost_saving", "true_vector_hybrid_latency", "retrieval_recall"]
    ):
        return False
    retrieval_shootout = data.get("retrieval_shootout")
    return isinstance(retrieval_shootout, dict)


def _valid_claim_gate(gate: Any) -> bool:
    if not isinstance(gate, dict):
        return False
    if not isinstance(gate.get("ready"), bool):
        return False
    if not _non_empty_string(gate.get("dimension")):
        return False
    if not _non_empty_string(gate.get("source")):
        return False
    blocking = gate.get("blocking")
    if not isinstance(blocking, list) or not all(
        isinstance(item, str) for item in blocking
    ):
        return False
    if gate["ready"]:
        return blocking == []
    return blocking != []


def _artifact_state(data: dict[str, Any], accepted: bool | None) -> str:
    state = str(data.get("artifact_state") or data.get("state") or "").strip().lower()
    if state in ARTIFACT_STATES:
        return state
    if accepted is True:
        return "accepted"
    if accepted is False:
        return "failed"
    return "partial"


def _snapshot_artifact_state(item: dict[str, Any]) -> str:
    state = str(item.get("artifact_state") or item.get("state") or "").strip().lower()
    if state in ARTIFACT_STATES:
        return state
    accepted = item.get("accepted")
    if accepted is True:
        return "accepted"
    if accepted is False:
        return "failed"
    return "partial"


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


__all__ = ["BENCHMARK_MATRIX_VERSION", "benchmark_matrix_report"]
