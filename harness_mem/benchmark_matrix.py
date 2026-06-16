"""Benchmark matrix and release regression gate summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

BENCHMARK_MATRIX_VERSION = "v4.5.0"

ARTIFACT_STATES = ["accepted", "partial", "failed", "quarantined"]
NON_RELEASE_ARTIFACT_STATE_ALIASES = {
    "diagnostic": "partial",
}

RETRIEVAL_SHOOTOUT_COLLECTION_ID = "true_hybrid_retrieval_shootout"
RETRIEVAL_SHOOTOUT_MODES = ["fts", "vector", "hybrid"]
EMBEDDING_BASELINE = "all-MiniLM-L6-v2"
EMBEDDING_SHOOTOUT_CANDIDATES = [
    "all-MiniLM-L6-v2",
    "bge-small-en-v1.5",
    "nomic-embed-text-v1.5",
]
EVIDENCE_HARDENING_PROFILES = ["10k", "100k", "1m"]
INDEX_FABRIC_REQUIRED_OPERATIONS = [
    "exact_search",
    "word_search",
    "trigram_search",
    "graph_search",
]
RUST_NATIVE_REQUIRED_OPERATIONS = [
    "scan_jsonl",
    "bulk_index_rows",
    "reciprocal_rank_fusion",
    "rank_candidates",
    "tokenize",
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
    "memory_eval_matrix": ["memory_eval_matrix"],
    "retrieval_quality_pack": ["retrieval_quality_pack", "true_hybrid_retrieval_shootout"],
    "code_memory_federation": ["code_memory_federation"],
    "claim_promotion": ["claim_promotion_pack"],
    "release_evidence_pack": ["release_evidence_pack"],
}

LONGMEMEVAL_DIMENSIONS = [
    "knowledge-update",
    "temporal-reasoning",
    "multi-session",
    "single-session-user",
    "single-session-assistant",
]

MEMORY_EVAL_MATRIX = {
    "cross_session_resume": ["client_enabled_vs_disabled", "memory_shortcut_vs_source_recovery"],
    "stale_truth_rejection": ["temporal_product_query", "evidence_safety"],
    "raw_evidence_recovery": ["retrieval_diagnostics", "evidence_safety"],
    "candidate_noise_rejection": ["evidence_safety", "auto_maintenance_effectiveness"],
    "task_aware_wake_precision": ["task_aware_wake_precision"],
    "multi_client_consistency": ["client_trace_evidence"],
    "wire_format_backward_compat": ["runtime_health_observability"],
    "context_sufficiency_accuracy": ["context_sufficiency_gate"],
}

RETRIEVAL_QUALITY_COMPONENTS: list[dict[str, Any]] = [
    {
        "component": "reranker",
        "default_enabled": False,
        "gate": "precision@k + latency + RSS + model size + cold start",
        "collections": ["retrieval_quality_pack"],
    },
    {
        "component": "query_rewriting",
        "default_enabled": False,
        "gate": "recall uplift must exceed false-positive drift",
        "collections": ["retrieval_quality_pack", "context_sufficiency_gate"],
    },
    {
        "component": "multi_query_hyde",
        "default_enabled": False,
        "gate": "fanout cost + duplicate rate + sufficiency delta",
        "collections": ["retrieval_quality_pack"],
    },
    {
        "component": "embedding_shootout",
        "default_enabled": False,
        "gate": "recall + latency + disk/cache + install friction",
        "collections": ["true_hybrid_retrieval_shootout"],
    },
    {
        "component": "retrieval_drift_suite",
        "default_enabled": True,
        "gate": "fixed query pack + source-hit + negative queries",
        "collections": ["retrieval_diagnostics", "retrieval_quality_pack"],
    },
]

CLAIM_PROMOTION_POLICIES = [
    {
        "claim_id": "token_cost_saving",
        "source_gate": "claim_readiness.token_cost_saving",
        "public_scope": "blocked until paired token/cost delta is positive from a named source",
        "claim_type": "public_saving",
    },
    {
        "claim_id": "true_vector_hybrid_latency",
        "source_gate": "claim_readiness.true_vector_hybrid_latency",
        "public_scope": "bounded local synthetic probe only",
        "claim_type": "bounded_performance",
    },
    {
        "claim_id": "retrieval_recall",
        "source_gate": "claim_readiness.retrieval_recall",
        "public_scope": "bounded local source-hit recall only",
        "claim_type": "bounded_retrieval",
    },
    {
        "claim_id": "storage_v2_speedup",
        "source_gate": "storage profile artifacts",
        "public_scope": "blocked until 10k/100k/1m profile artifacts pass",
        "claim_type": "public_performance",
    },
    {
        "claim_id": "default_reranker_hyde",
        "source_gate": "retrieval quality component gates",
        "public_scope": "blocked; reranker and HyDE remain optional/experimental",
        "claim_type": "default_behavior_change",
    },
    {
        "claim_id": "code_memory_token_runtime",
        "source_gate": "code-memory federation artifacts",
        "public_scope": "blocked; federation contract is not code-intel token/runtime evidence",
        "claim_type": "public_performance",
    },
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
    raw_artifact_runs = _artifact_runs(artifacts_path)
    has_raw_artifacts = bool(raw_artifact_runs)
    release_artifact_runs = _release_artifact_runs(raw_artifact_runs)
    allow_packaged_snapshot = not suite_path.exists() and not has_raw_artifacts
    snapshot_claim_readiness = (
        _snapshot_claim_readiness(snapshot_path)
        if snapshot_path.exists() or allow_packaged_snapshot
        else _missing_claim_readiness("missing-or-invalid-snapshot")
    )
    artifact_collection_ids = {
        str(run.get("collection_id") or "")
        for run in raw_artifact_runs
        if run.get("collection_id")
    }
    claim_readiness = (
        _merge_claim_readiness(
            _artifact_claim_readiness(artifacts_path),
            snapshot_claim_readiness,
            artifact_collection_ids=artifact_collection_ids,
        )
        if has_raw_artifacts
        else snapshot_claim_readiness
    )
    snapshot_runs = (
        _snapshot_runs(snapshot_path)
        if snapshot_path.exists() or allow_packaged_snapshot
        else []
    )
    release_runs = _merge_release_runs(snapshot_runs, release_artifact_runs)
    gate_runs = release_runs if release_runs else raw_artifact_runs
    latest_run = release_runs[0] if release_runs else None
    accepted = sum(1 for run in release_runs if run.get("artifact_state") == "accepted")
    failed = sum(1 for run in release_runs if run.get("artifact_state") in {"failed", "quarantined"})
    unknown = sum(1 for run in release_runs if run.get("artifact_state") == "partial")
    gate_failed = sum(
        1 for run in gate_runs if run.get("artifact_state") in {"failed", "quarantined"}
    )
    gate_unknown = sum(1 for run in gate_runs if run.get("artifact_state") == "partial")
    gate_passed = (
        not missing_surface_coverage
        and bool(gate_runs)
        and gate_failed == 0
        and gate_unknown == 0
    )
    claim_promotion_gate = _claim_promotion_gate(collection_ids, claim_readiness)
    release_evidence_pack = _release_evidence_pack(
        root=root,
        suite_path=suite_path,
        snapshot_path=snapshot_path,
        artifact_runs=release_runs,
        collection_ids=collection_ids,
        gate_passed=gate_passed,
        claim_promotion_gate=claim_promotion_gate,
    )
    evidence_hardening_track = _evidence_hardening_track(
        artifacts_path=artifacts_path,
        snapshot_path=snapshot_path,
        allow_packaged_snapshot=allow_packaged_snapshot,
        collection_ids=collection_ids,
    )
    default_change_decision_gate = _default_change_decision_gate(
        evidence_hardening_track=evidence_hardening_track,
        retrieval_quality_pack=_retrieval_quality_pack(
            collection_ids,
            claim_readiness=claim_readiness,
        ),
        claim_promotion_gate=claim_promotion_gate,
        release_evidence_pack=release_evidence_pack,
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
            "memory_eval_dimensions": list(MEMORY_EVAL_MATRIX),
        },
        "surfaces": surface_rows,
        "dimension_scores": [
            {"dimension": dimension, "status": "tracked"}
            for dimension in LONGMEMEVAL_DIMENSIONS
        ],
        "memory_eval_matrix": _memory_eval_matrix(collection_ids),
        "memory_eval_gate": _memory_eval_gate(collection_ids),
        "retrieval_quality_pack": _retrieval_quality_pack(
            collection_ids,
            claim_readiness=claim_readiness,
        ),
        "claim_promotion_gate": claim_promotion_gate,
        "release_evidence_pack": release_evidence_pack,
        "evidence_hardening_track": evidence_hardening_track,
        "default_change_decision_gate": default_change_decision_gate,
        "release_snapshot": {
            "artifact_run_count": len(release_runs),
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
            allow_packaged_snapshot=allow_packaged_snapshot,
        ),
        "claim_readiness": claim_readiness,
        "gate": {
            "passed": gate_passed,
            "missing_surface_coverage": missing_surface_coverage,
            "failed_artifact_runs": gate_failed,
            "unknown_artifact_runs": gate_unknown,
            "has_artifacts": bool(gate_runs),
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


def _memory_eval_matrix(collection_ids: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension, targets in MEMORY_EVAL_MATRIX.items():
        if "memory_eval_matrix" in collection_ids:
            covered = ["memory_eval_matrix"]
            missing: list[str] = []
        else:
            covered = [target for target in targets if target in collection_ids]
            missing = [target for target in targets if target not in collection_ids]
        rows.append(
            {
                "dimension": dimension,
                "status": "tracked" if not missing else "missing_collection",
                "collections": covered,
                "missing_collections": missing,
            }
        )
    return rows


def _memory_eval_gate(collection_ids: set[str]) -> dict[str, Any]:
    rows = _memory_eval_matrix(collection_ids)
    missing = [
        row["dimension"]
        for row in rows
        if row["status"] != "tracked"
    ]
    return {
        "passed": not missing,
        "dimensions": len(rows),
        "missing_dimensions": missing,
        "claim_boundary": (
            "release gate for memory-runtime behavior; not a global answer-quality "
            "or token-saving claim"
        ),
    }


def _retrieval_quality_pack(
    collection_ids: set[str],
    *,
    claim_readiness: dict[str, Any],
) -> dict[str, Any]:
    components = []
    missing_components: list[str] = []
    for component in RETRIEVAL_QUALITY_COMPONENTS:
        targets = list(component["collections"])
        covered = [target for target in targets if target in collection_ids]
        missing = [target for target in targets if target not in collection_ids]
        if missing:
            missing_components.append(str(component["component"]))
        components.append(
            {
                **component,
                "collections": covered,
                "missing_collections": missing,
                "status": "tracked" if not missing else "missing_collection",
            }
        )
    return {
        "passed": not missing_components,
        "components": components,
        "missing_components": missing_components,
        "embedding_baseline": EMBEDDING_BASELINE,
        "embedding_candidates": EMBEDDING_SHOOTOUT_CANDIDATES,
        "claim_readiness": {
            "retrieval_recall": claim_readiness.get("retrieval_recall"),
            "true_vector_hybrid_latency": claim_readiness.get(
                "true_vector_hybrid_latency"
            ),
        },
        "claim_boundary": (
            "quality-pack gates retrieval behavior and artifact hygiene; reranker, "
            "query rewriting, and HyDE remain opt-in/experimental unless their "
            "component gates pass"
        ),
    }


def _claim_promotion_gate(
    collection_ids: set[str],
    claim_readiness: dict[str, Any],
) -> dict[str, Any]:
    readiness_by_claim = {
        "token_cost_saving": claim_readiness.get("token_cost_saving"),
        "true_vector_hybrid_latency": claim_readiness.get("true_vector_hybrid_latency"),
        "retrieval_recall": claim_readiness.get("retrieval_recall"),
    }
    rows: list[dict[str, Any]] = []
    blocked_claims: list[str] = []
    bounded_claims: list[str] = []
    unsafe_promotions: list[str] = []

    for policy in CLAIM_PROMOTION_POLICIES:
        claim_id = str(policy["claim_id"])
        readiness = readiness_by_claim.get(claim_id)
        ready = bool(isinstance(readiness, dict) and readiness.get("ready") is True)
        if claim_id in {"true_vector_hybrid_latency", "retrieval_recall"} and ready:
            status = "bounded_ready"
            bounded_claims.append(claim_id)
        elif ready:
            status = "public_ready"
        else:
            status = "blocked"
            blocked_claims.append(claim_id)

        if claim_id in {
            "storage_v2_speedup",
            "default_reranker_hyde",
            "code_memory_token_runtime",
        } and status == "public_ready":
            unsafe_promotions.append(claim_id)

        rows.append(
            {
                **policy,
                "status": status,
                "ready": ready,
                "blocking": (
                    list(readiness.get("blocking") or [])
                    if isinstance(readiness, dict)
                    else [f"{claim_id}/no_public_promotion_artifact"]
                ),
            }
        )

    return {
        "passed": "claim_promotion_pack" in collection_ids and not unsafe_promotions,
        "policy_enforced": "claim_promotion_pack" in collection_ids,
        "claims": rows,
        "blocked_claims": blocked_claims,
        "bounded_claims": bounded_claims,
        "unsafe_promotions": unsafe_promotions,
        "claim_boundary": (
            "v4.4 promotes only machine-gated claims; bounded local readiness is "
            "kept separate from public performance, token-saving, default-behavior, "
            "and code-intel runtime claims"
        ),
    }


def _release_evidence_pack(
    *,
    root: Path,
    suite_path: Path,
    snapshot_path: Path,
    artifact_runs: list[dict[str, Any]],
    collection_ids: set[str],
    gate_passed: bool,
    claim_promotion_gate: dict[str, Any],
) -> dict[str, Any]:
    package_match = _packaged_resource_match(
        root=root,
        suite_path=suite_path,
        snapshot_path=snapshot_path,
    )
    accepted = sum(1 for run in artifact_runs if run.get("artifact_state") == "accepted")
    failed = sum(1 for run in artifact_runs if run.get("artifact_state") in {"failed", "quarantined"})
    unknown = sum(1 for run in artifact_runs if run.get("artifact_state") == "partial")
    present = "release_evidence_pack" in collection_ids
    return {
        "passed": (
            present
            and gate_passed
            and failed == 0
            and unknown == 0
            and package_match["matches"] is True
            and claim_promotion_gate.get("policy_enforced") is True
        ),
        "collection_present": present,
        "snapshot_run_count": len(artifact_runs),
        "accepted_runs": accepted,
        "failed_runs": failed,
        "unknown_runs": unknown,
        "packaged_resource_match": package_match,
        "claim_promotion_policy_enforced": claim_promotion_gate.get("policy_enforced") is True,
        "claim_boundary": (
            "v4.5 packages release evidence for clean-checkout/runtime consumers; "
            "it does not upgrade blocked claims into public performance claims"
        ),
    }


def _evidence_hardening_track(
    *,
    artifacts_path: Path,
    snapshot_path: Path,
    allow_packaged_snapshot: bool,
    collection_ids: set[str],
) -> dict[str, Any]:
    raw_track = _artifact_evidence_hardening_track(artifacts_path, collection_ids)
    if raw_track is not None:
        return raw_track

    snapshot_track = _snapshot_evidence_hardening_track(
        snapshot_path,
        allow_packaged_snapshot=allow_packaged_snapshot,
    )
    if snapshot_track is not None:
        return snapshot_track

    return _missing_evidence_hardening_track(collection_ids)


def _artifact_evidence_hardening_track(
    artifacts_path: Path,
    collection_ids: set[str],
) -> dict[str, Any] | None:
    if not artifacts_path.exists():
        return None

    cost_token_evidence = _cost_token_evidence(
        memory_shortcut_rows=_artifact_results(
            artifacts_path, "memory_shortcut_vs_source_recovery"
        ),
        functional_rows=_artifact_results(
            artifacts_path, "functional_token_economics"
        ),
        collection_ids=collection_ids,
    )
    storage_v2_scale_evidence = _storage_v2_scale_evidence(
        baseline_rows=_artifact_results_all_runs(artifacts_path, "storage_v2_baseline"),
        migration_rows=_artifact_results_all_runs(artifacts_path, "migration_roundtrip"),
        canonical_rows=_artifact_results_all_runs(
            artifacts_path, "canonical_store_runtime_baseline"
        ),
        collection_ids=collection_ids,
    )
    index_fabric_runtime_evidence = _index_fabric_runtime_evidence(
        rows=_artifact_results(artifacts_path, "index_fabric_runtime_conformance"),
        collection_ids=collection_ids,
    )
    rust_native_hot_path_evidence = _rust_native_hot_path_evidence(
        rows=_artifact_results(artifacts_path, "rust_core_hot_path"),
        collection_ids=collection_ids,
    )
    return {
        "cost_token_evidence": cost_token_evidence,
        "storage_v2_scale_evidence": storage_v2_scale_evidence,
        "index_fabric_runtime_evidence": index_fabric_runtime_evidence,
        "rust_native_hot_path_evidence": rust_native_hot_path_evidence,
        "claim_boundary": (
            "future-track evidence gates measure bounded cost, storage, index, and "
            "native hot-path readiness; they do not upgrade blocked public claims "
            "or default behaviors by themselves"
        ),
    }


def _snapshot_evidence_hardening_track(
    snapshot_path: Path,
    *,
    allow_packaged_snapshot: bool,
) -> dict[str, Any] | None:
    snapshot = (
        _read_snapshot_json(snapshot_path)
        if snapshot_path.exists() or allow_packaged_snapshot
        else None
    )
    if not isinstance(snapshot, dict):
        return None
    track = snapshot.get("evidence_hardening_track")
    return track if isinstance(track, dict) else None


def _missing_evidence_hardening_track(collection_ids: set[str]) -> dict[str, Any]:
    return {
        "cost_token_evidence": _missing_gate(
            source="missing",
            collection_present="memory_shortcut_vs_source_recovery" in collection_ids,
            missing_reason="memory_shortcut_vs_source_recovery/missing",
            claim_boundary=(
                "bounded long-source memory-shortcut evidence only; not a global "
                "token/cost or real-billing claim"
            ),
        ),
        "storage_v2_scale_evidence": _missing_gate(
            source="missing",
            collection_present=all(
                target in collection_ids
                for target in [
                    "storage_v2_baseline",
                    "migration_roundtrip",
                    "canonical_store_runtime_baseline",
                ]
            ),
            missing_reason="storage_v2_scale_artifacts/missing",
            claim_boundary=(
                "10k/100k/1m storage evidence is required before any default "
                "canonical-store or speedup discussion"
            ),
        ),
        "index_fabric_runtime_evidence": _missing_gate(
            source="missing",
            collection_present="index_fabric_runtime_conformance" in collection_ids,
            missing_reason="index_fabric_runtime_conformance/missing",
            claim_boundary=(
                "runtime conformance evidence is required before any index-fabric, "
                "Tantivy, LanceDB, or ANN readiness language"
            ),
        ),
        "rust_native_hot_path_evidence": _missing_gate(
            source="missing",
            collection_present="rust_core_hot_path" in collection_ids,
            missing_reason="rust_core_hot_path/missing",
            claim_boundary=(
                "native Rust evidence is required before any Rust speedup or "
                "default-wheel readiness claim"
            ),
        ),
        "claim_boundary": (
            "future-track evidence gates measure bounded cost, storage, index, and "
            "native hot-path readiness; they do not upgrade blocked public claims "
            "or default behaviors by themselves"
        ),
    }


def _missing_gate(
    *,
    source: str,
    collection_present: bool,
    missing_reason: str,
    claim_boundary: str,
) -> dict[str, Any]:
    blocking = [] if collection_present else ["collection_missing"]
    blocking.append(missing_reason)
    return {
        "passed": False,
        "source": source,
        "collection_present": collection_present,
        "blocking": blocking,
        "claim_boundary": claim_boundary,
    }


def _cost_token_evidence(
    *,
    memory_shortcut_rows: list[dict[str, Any]],
    functional_rows: list[dict[str, Any]],
    collection_ids: set[str],
) -> dict[str, Any]:
    if not memory_shortcut_rows:
        return {
            **_missing_gate(
                source="artifact-results",
                collection_present="memory_shortcut_vs_source_recovery" in collection_ids,
                missing_reason="memory_shortcut_vs_source_recovery/missing",
                claim_boundary=(
                    "bounded long-source memory-shortcut evidence only; not a global "
                    "token/cost or real-billing claim"
                ),
            ),
            "memory_shortcut_ready": False,
            "functional_token_economics_ready": False,
        }

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in memory_shortcut_rows:
        grouped.setdefault(str(row.get("task_id") or ""), {})[
            str(row.get("condition") or "")
        ] = row

    long_source_both_passed = 0
    source_read_reduction_pairs = 0
    enabled_source_budget_ok_pairs = 0
    negative_control_pairs = 0
    negative_control_budget_ok_pairs = 0
    long_source_ratios: list[float] = []
    blockers: list[str] = []

    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled is None or disabled is None:
            blockers.append(f"{task_id}/missing_pair")
            continue
        for condition, row in [("enabled", enabled), ("disabled", disabled)]:
            if _named_token_total(row) is None:
                blockers.append(f"{task_id}/{condition}/token_total_unavailable")

        task_type = str(enabled.get("task_type") or disabled.get("task_type") or "")
        both_passed = enabled.get("accepted") == "yes" and disabled.get("accepted") == "yes"
        ratio = _saving_ratio(disabled, enabled)
        source_delta = _source_read_delta_num(disabled, enabled)
        if task_type == "negative_control":
            negative_control_pairs += 1
            if _budget_ok(enabled) and _budget_ok(disabled):
                negative_control_budget_ok_pairs += 1
            else:
                blockers.append(
                    f"{task_id}/budget={_memory_shortcut_budget_violation(enabled)}"
                )
            if ratio is not None and ratio >= 0.2:
                blockers.append(f"{task_id}/negative_control_token_advantage={ratio:.3f}")
            if source_delta is not None and source_delta > 0:
                blockers.append(
                    f"{task_id}/negative_control_source_read_advantage={int(source_delta)}"
                )
            if enabled.get("memory_calls"):
                blockers.append(f"{task_id}/negative_control_memory_calls_present")
            continue

        if task_type != "long_source_recovery":
            blockers.append(f"{task_id}/task_type={task_type or 'missing'}")
            continue
        if both_passed:
            long_source_both_passed += 1
            if _budget_ok(enabled):
                enabled_source_budget_ok_pairs += 1
                if ratio is not None:
                    long_source_ratios.append(ratio)
                if source_delta is not None and source_delta > 0:
                    source_read_reduction_pairs += 1
            else:
                blockers.append(
                    f"{task_id}/budget={_memory_shortcut_budget_violation(enabled)}"
                )

    median_ratio = _median(long_source_ratios)
    if long_source_both_passed < 6:
        blockers.append(f"long_source_both_passed={long_source_both_passed}/6")
    if median_ratio is None or median_ratio < 0.2:
        blockers.append(f"median_token_saving_ratio={_ratio_display(median_ratio)}")
    if source_read_reduction_pairs < 6:
        blockers.append(f"source_read_reduction_pairs={source_read_reduction_pairs}/6")
    if enabled_source_budget_ok_pairs < 6:
        blockers.append(
            f"enabled_source_budget_ok_pairs={enabled_source_budget_ok_pairs}/6"
        )
    if negative_control_pairs < 2:
        blockers.append(f"negative_control_pairs={negative_control_pairs}/2")
    if negative_control_budget_ok_pairs < 2:
        blockers.append(
            f"negative_control_budget_ok_pairs={negative_control_budget_ok_pairs}/2"
        )

    functional_ready = _functional_token_economics_ready(functional_rows)
    if not functional_ready["passed"]:
        blockers.extend(functional_ready["blocking"])

    memory_shortcut_ready = (
        long_source_both_passed >= 6
        and median_ratio is not None
        and median_ratio >= 0.2
        and source_read_reduction_pairs >= 6
        and enabled_source_budget_ok_pairs >= 6
        and negative_control_pairs >= 2
        and negative_control_budget_ok_pairs >= 2
    )
    passed = not blockers
    return {
        "passed": passed,
        "source": "artifact-results",
        "collection_present": True,
        "memory_shortcut_ready": memory_shortcut_ready,
        "functional_token_economics_ready": functional_ready["passed"],
        "long_source_both_passed": long_source_both_passed,
        "median_token_saving_ratio": _ratio_display(median_ratio),
        "source_read_reduction_pairs": source_read_reduction_pairs,
        "enabled_source_budget_ok_pairs": enabled_source_budget_ok_pairs,
        "negative_control_pairs": negative_control_pairs,
        "negative_control_budget_ok_pairs": negative_control_budget_ok_pairs,
        "blocking": sorted(set(blockers)),
        "claim_boundary": (
            "bounded long-source memory-shortcut evidence only; not a global "
            "token/cost or real-billing claim"
        ),
    }


def _functional_token_economics_ready(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "passed": False,
            "blocking": ["functional_token_economics/missing"],
            "scenario_count": 0,
        }
    blockers: list[str] = []
    for row in rows:
        scenario_id = str(row.get("scenario_id") or "unknown")
        ratio = _safe_float(row.get("saving_ratio"))
        minimum = _safe_float(row.get("minimum_saving_ratio"))
        token_delta = _safe_float(row.get("token_delta"))
        if row.get("accepted") != "yes":
            blockers.append(f"functional_token_economics/{scenario_id}/accepted")
        if row.get("fixture_only") is not True:
            blockers.append(f"functional_token_economics/{scenario_id}/fixture_only")
        if ratio is None or minimum is None or token_delta is None:
            blockers.append(f"functional_token_economics/{scenario_id}/missing_metrics")
            continue
        if token_delta <= 0:
            blockers.append(
                f"functional_token_economics/{scenario_id}/token_delta_not_saving={row.get('token_delta')}"
            )
        if ratio < minimum:
            blockers.append(
                f"functional_token_economics/{scenario_id}/saving_ratio_below_minimum"
            )
    return {
        "passed": not blockers,
        "blocking": blockers,
        "scenario_count": len(rows),
    }


def _storage_v2_scale_evidence(
    *,
    baseline_rows: list[dict[str, Any]],
    migration_rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
    collection_ids: set[str],
) -> dict[str, Any]:
    if not baseline_rows and not migration_rows and not canonical_rows:
        return _missing_gate(
            source="artifact-results",
            collection_present=all(
                target in collection_ids
                for target in [
                    "storage_v2_baseline",
                    "migration_roundtrip",
                    "canonical_store_runtime_baseline",
                ]
            ),
            missing_reason="storage_v2_scale_artifacts/missing",
            claim_boundary=(
                "10k/100k/1m storage evidence is required before any default "
                "canonical-store or speedup discussion"
            ),
        )

    blockers: list[str] = []
    baseline_profiles = _collect_profiles(
        baseline_rows, required_profiles=EVIDENCE_HARDENING_PROFILES
    )
    migration_profiles = _collect_profiles(
        migration_rows, required_profiles=EVIDENCE_HARDENING_PROFILES
    )
    canonical_profiles = _collect_profiles(
        canonical_rows, required_profiles=EVIDENCE_HARDENING_PROFILES
    )
    blockers.extend(baseline_profiles["blocking"])
    blockers.extend(migration_profiles["blocking"])
    blockers.extend(canonical_profiles["blocking"])

    for row in migration_rows:
        row_id = str(row.get("corpus_profile") or row.get("dataset_id") or "unknown")
        if row.get("apply_checksum_match") is not True:
            blockers.append(f"migration_roundtrip/{row_id}/apply_checksum_match=false")
        if row.get("rollback_checksum_match") is not True:
            blockers.append(
                f"migration_roundtrip/{row_id}/rollback_checksum_match=false"
            )
    for row in canonical_rows:
        row_id = str(row.get("corpus_profile") or row.get("dataset_id") or "unknown")
        if row.get("checksum_match") is not True:
            blockers.append(f"canonical_store_runtime_baseline/{row_id}/checksum_match=false")

    passed = not blockers
    return {
        "passed": passed,
        "source": "artifact-results",
        "collection_present": True,
        "baseline_profiles": baseline_profiles["profiles"],
        "migration_profiles": migration_profiles["profiles"],
        "canonical_profiles": canonical_profiles["profiles"],
        "blocking": sorted(set(blockers)),
        "claim_boundary": (
            "10k/100k/1m storage evidence is required before any default "
            "canonical-store or speedup discussion"
        ),
    }


def _index_fabric_runtime_evidence(
    *,
    rows: list[dict[str, Any]],
    collection_ids: set[str],
) -> dict[str, Any]:
    if not rows:
        return _missing_gate(
            source="artifact-results",
            collection_present="index_fabric_runtime_conformance" in collection_ids,
            missing_reason="index_fabric_runtime_conformance/missing",
            claim_boundary=(
                "runtime conformance evidence is required before any index-fabric, "
                "Tantivy, LanceDB, or ANN readiness language"
            ),
        )

    operations = {
        str(row.get("operation") or "")
        for row in rows
        if row.get("operation")
    }
    blockers: list[str] = []
    for operation in INDEX_FABRIC_REQUIRED_OPERATIONS:
        if operation not in operations:
            blockers.append(f"index_fabric_runtime_conformance/op={operation}/missing")
    if not any(row.get("first_lazy_load") is True for row in rows):
        blockers.append("index_fabric_runtime_conformance/first_lazy_load/missing")
    if not any(row.get("warm_run") is True for row in rows):
        blockers.append("index_fabric_runtime_conformance/warm_run/missing")
    for row in rows:
        row_id = str(row.get("operation") or row.get("dataset_id") or "unknown")
        for field in [
            "manifest_commit",
            "search_backend_conformance",
            "source_fingerprint_drift_detected",
        ]:
            if row.get(field) is not True:
                blockers.append(f"index_fabric_runtime_conformance/{row_id}/{field}=false")
        if row.get("interrupted_generation_visible") is not False:
            blockers.append(
                f"index_fabric_runtime_conformance/{row_id}/interrupted_generation_visible=true"
            )
        if not isinstance(row.get("fallback_reason"), str):
            blockers.append(f"index_fabric_runtime_conformance/{row_id}/fallback_reason_missing")

    return {
        "passed": not blockers,
        "source": "artifact-results",
        "collection_present": True,
        "operations": sorted(operations),
        "blocking": sorted(set(blockers)),
        "claim_boundary": (
            "runtime conformance evidence is required before any index-fabric, "
            "Tantivy, LanceDB, or ANN readiness language"
        ),
    }


def _rust_native_hot_path_evidence(
    *,
    rows: list[dict[str, Any]],
    collection_ids: set[str],
) -> dict[str, Any]:
    if not rows:
        return _missing_gate(
            source="artifact-results",
            collection_present="rust_core_hot_path" in collection_ids,
            missing_reason="rust_core_hot_path/missing",
            claim_boundary=(
                "native Rust evidence is required before any Rust speedup or "
                "default-wheel readiness claim"
            ),
        )

    operations = {
        str(row.get("operation") or "")
        for row in rows
        if row.get("operation")
    }
    blockers: list[str] = []
    for operation in RUST_NATIVE_REQUIRED_OPERATIONS:
        if operation not in operations:
            blockers.append(f"rust_core_hot_path/op={operation}/missing")
    for row in rows:
        row_id = str(row.get("operation") or row.get("dataset_id") or "unknown")
        if row.get("accepted") != "yes":
            blockers.append(f"rust_core_hot_path/{row_id}/accepted={row.get('accepted')}")
        if row.get("native_available") is not True:
            blockers.append(f"rust_core_hot_path/{row_id}/native_available=false")
        if row.get("rust_mode") != "rust":
            blockers.append(
                f"rust_core_hot_path/{row_id}/rust_mode={row.get('rust_mode') or 'missing'}"
            )

    return {
        "passed": not blockers,
        "source": "artifact-results",
        "collection_present": True,
        "operations": sorted(operations),
        "blocking": sorted(set(blockers)),
        "claim_boundary": (
            "native Rust evidence is required before any Rust speedup or "
            "default-wheel readiness claim"
        ),
    }


def _default_change_decision_gate(
    *,
    evidence_hardening_track: dict[str, Any],
    retrieval_quality_pack: dict[str, Any],
    claim_promotion_gate: dict[str, Any],
    release_evidence_pack: dict[str, Any],
) -> dict[str, Any]:
    gate_status = {
        "cost_token_evidence": bool(
            evidence_hardening_track.get("cost_token_evidence", {}).get("passed")
        ),
        "storage_v2_scale_evidence": bool(
            evidence_hardening_track.get("storage_v2_scale_evidence", {}).get("passed")
        ),
        "index_fabric_runtime_evidence": bool(
            evidence_hardening_track.get("index_fabric_runtime_evidence", {}).get("passed")
        ),
        "rust_native_hot_path_evidence": bool(
            evidence_hardening_track.get("rust_native_hot_path_evidence", {}).get("passed")
        ),
        "retrieval_quality_pack": bool(retrieval_quality_pack.get("passed")),
        "claim_promotion_policy": bool(claim_promotion_gate.get("policy_enforced")),
        "release_evidence_pack": bool(release_evidence_pack.get("passed")),
    }
    blocking = [name for name, passed in gate_status.items() if not passed]
    return {
        "ready": not blocking,
        "required_gates": gate_status,
        "blocking": blocking,
        "claim_boundary": (
            "default storage/index/reranker/HyDE decisions require artifact-backed "
            "evidence across cost, storage, index, native hot path, retrieval "
            "quality, claim-promotion policy, and release evidence; smoke alone "
            "never changes defaults"
        ),
    }


def _collect_profiles(
    rows: list[dict[str, Any]],
    *,
    required_profiles: list[str],
) -> dict[str, Any]:
    seen_profiles = {
        str(row.get("corpus_profile") or "")
        for row in rows
        if row.get("corpus_profile")
    }
    profiles = [profile for profile in required_profiles if profile in seen_profiles]
    profiles.extend(
        sorted(profile for profile in seen_profiles if profile and profile not in required_profiles)
    )
    blocking = [f"profile/{profile}/missing" for profile in required_profiles if profile not in profiles]
    for row in rows:
        row_id = str(row.get("corpus_profile") or row.get("dataset_id") or "unknown")
        if row.get("accepted") != "yes":
            blocking.append(f"{row_id}/accepted={row.get('accepted') or 'missing'}")
    return {"profiles": profiles, "blocking": blocking}


def _packaged_resource_match(
    *,
    root: Path,
    suite_path: Path,
    snapshot_path: Path,
) -> dict[str, Any]:
    package_suite = _read_resource_json("suite.json")
    package_snapshot = _read_resource_json("release-snapshot.json")
    if not suite_path.exists() and not snapshot_path.exists():
        return {
            "source": "packaged",
            "available": package_suite is not None and package_snapshot is not None,
            "matches": package_suite is not None and package_snapshot is not None,
            "blocking": [],
        }

    blocking: list[str] = []
    if package_suite is None:
        blocking.append("packaged_suite_json/missing_or_invalid")
    elif suite_path.exists():
        try:
            repo_suite = json.loads(suite_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            repo_suite = None
        if repo_suite != package_suite:
            blocking.append("packaged_suite_json/stale")

    if package_snapshot is None:
        blocking.append("packaged_release_snapshot_json/missing_or_invalid")
    elif snapshot_path.exists():
        try:
            repo_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            repo_snapshot = None
        if repo_snapshot != package_snapshot:
            blocking.append("packaged_release_snapshot_json/stale")

    return {
        "source": str(root),
        "available": package_suite is not None and package_snapshot is not None,
        "matches": not blocking,
        "blocking": blocking,
    }


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
                "release_snapshot": data.get("release_snapshot"),
            }
        )
    runs.sort(key=lambda item: str(item["run_id"]), reverse=True)
    return runs


def _release_artifact_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for run in runs:
        if run.get("release_snapshot") is False:
            continue
        if run.get("artifact_state") == "partial":
            continue
        out.append(dict(run))
    return out


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


def _artifact_results_all_runs(path: Path, benchmark_id: str) -> list[dict[str, Any]]:
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
    merged_rows: list[dict[str, Any]] = []
    for _, rows in accepted_runs:
        merged_rows.extend(rows)
    return merged_rows


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


def _saving_ratio(disabled: dict[str, Any], enabled: dict[str, Any]) -> float | None:
    disabled_total = _named_token_total(disabled)
    enabled_total = _named_token_total(enabled)
    if disabled_total is None or enabled_total is None or disabled_total <= 0:
        return None
    return (disabled_total - enabled_total) / disabled_total


def _format_delta(disabled: dict[str, Any], enabled: dict[str, Any]) -> str:
    disabled_total = _named_token_total(disabled)
    enabled_total = _named_token_total(enabled)
    if disabled_total is None or enabled_total is None:
        return "unavailable"
    delta = disabled_total - enabled_total
    return str(int(delta)) if float(delta).is_integer() else f"{delta:.2f}"


def _source_read_delta_num(
    disabled: dict[str, Any],
    enabled: dict[str, Any],
) -> float | None:
    disabled_reads = _safe_float(disabled.get("source_read_count"))
    enabled_reads = _safe_float(enabled.get("source_read_count"))
    if disabled_reads is None or enabled_reads is None:
        return None
    return disabled_reads - enabled_reads


def _memory_shortcut_budget_violation(row: dict[str, Any]) -> str:
    task_type = str(row.get("task_type") or "")
    condition = str(row.get("condition") or "")
    source_reads = _safe_float(row.get("source_read_count"))
    source_reads = 0 if source_reads is None else int(source_reads)
    repo_calls = row.get("repo_calls")
    repo_call_count = len(repo_calls) if isinstance(repo_calls, list) else 0
    if task_type == "long_source_recovery" and condition == "enabled":
        if source_reads > 2:
            return "enabled_source_reads>2"
    if task_type == "negative_control":
        if source_reads > 1:
            return "negative_control_source_reads>1"
        if repo_call_count > 3:
            return "negative_control_repo_calls>3"
    return "none"


def _budget_ok(row: dict[str, Any] | None) -> bool:
    if row is None:
        return False
    return _memory_shortcut_budget_violation(row) == "none"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _ratio_display(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.3f}"


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


def _merge_claim_readiness(
    local_readiness: dict[str, Any],
    snapshot_readiness: dict[str, Any],
    *,
    artifact_collection_ids: set[str],
) -> dict[str, Any]:
    mapping = {
        "token_cost_saving": "client_enabled_vs_disabled",
        "true_vector_hybrid_latency": "latency_warm_path",
        "retrieval_recall": RETRIEVAL_SHOOTOUT_COLLECTION_ID,
    }
    merged: dict[str, Any] = {}
    for key, collection_id in mapping.items():
        if collection_id in artifact_collection_ids:
            merged[key] = local_readiness.get(key, snapshot_readiness.get(key))
        else:
            merged[key] = snapshot_readiness.get(key, local_readiness.get(key))
    return merged


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


def _merge_release_runs(
    snapshot_runs: list[dict[str, Any]],
    raw_artifact_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = {
        str(run["run_id"]): dict(run)
        for run in snapshot_runs
        if isinstance(run, dict) and run.get("run_id")
    }
    for run in raw_artifact_runs:
        if not isinstance(run, dict) or not run.get("run_id"):
            continue
        merged[str(run["run_id"])] = dict(run)
    return sorted(merged.values(), key=lambda item: str(item["run_id"]), reverse=True)


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
    if state in NON_RELEASE_ARTIFACT_STATE_ALIASES:
        return NON_RELEASE_ARTIFACT_STATE_ALIASES[state]
    if state in ARTIFACT_STATES:
        return state
    if data.get("release_snapshot") is False:
        return "partial"
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
