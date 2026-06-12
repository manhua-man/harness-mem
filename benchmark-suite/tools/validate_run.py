from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suite.json"
STORAGE_V2_BENCHMARKS = {
    "storage_v2_baseline",
    "migration_roundtrip",
    "local_index_fabric_smoke",
    "canonical_store_runtime_baseline",
    "rust_core_hot_path",
    "index_fabric_runtime_conformance",
    "context_sufficiency_gate",
    "task_aware_wake_precision",
}
MEMORY_EVAL_DIMENSIONS = {
    "cross_session_resume",
    "stale_truth_rejection",
    "raw_evidence_recovery",
    "candidate_noise_rejection",
    "task_aware_wake_precision",
    "multi_client_consistency",
    "wire_format_backward_compat",
    "context_sufficiency_accuracy",
}
RETRIEVAL_QUALITY_CAPABILITIES = {
    "reranker",
    "query_rewriting",
    "multi_query_hyde",
    "embedding_shootout",
    "retrieval_drift_suite",
}
CLAIM_PROMOTION_CLAIMS = {
    "token_cost_saving",
    "true_vector_hybrid_latency",
    "retrieval_recall",
    "storage_v2_speedup",
    "default_reranker_hyde",
    "code_memory_token_runtime",
}


def load_suite(path: Path = SUITE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0


def _is_real_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def validate_token_usage(path: Path, payload: dict) -> None:
    usage = payload.get("token_usage")
    if not isinstance(usage, dict):
        raise SystemExit(f"{path.name}: token_usage must be an object")

    required = [
        "available",
        "source",
        "total",
        "input",
        "cached_input",
        "output",
        "reasoning",
        "cost_usd",
        "notes",
    ]
    for field in required:
        if field not in usage:
            raise SystemExit(f"{path.name}: token_usage missing field '{field}'")

    if not isinstance(usage["available"], bool):
        raise SystemExit(f"{path.name}: token_usage.available must be boolean")
    if not isinstance(usage["source"], str) or not usage["source"]:
        raise SystemExit(f"{path.name}: token_usage.source must be a non-empty string")
    if not isinstance(usage["notes"], list) or not all(
        isinstance(item, str) for item in usage["notes"]
    ):
        raise SystemExit(f"{path.name}: token_usage.notes must be a string array")

    numeric_fields = ["total", "input", "cached_input", "output", "reasoning", "cost_usd"]
    for field in numeric_fields:
        value = usage[field]
        if value is not None and not _is_number(value):
            raise SystemExit(f"{path.name}: token_usage.{field} must be a non-negative number or null")

    has_number = any(usage[field] is not None for field in numeric_fields)
    if usage["available"]:
        if usage["source"] == "unavailable":
            raise SystemExit(f"{path.name}: available token_usage cannot use source='unavailable'")
        if not has_number:
            raise SystemExit(f"{path.name}: available token_usage requires at least one numeric field")
    else:
        if usage["total"] is not None:
            raise SystemExit(f"{path.name}: unavailable token_usage must keep total=null")
        if payload.get("token_total") != "unavailable":
            raise SystemExit(f"{path.name}: unavailable token_usage requires token_total='unavailable'")


def validate_memory_shortcut_result(path: Path, payload: dict) -> None:
    validate_token_usage(path, payload)
    source_read_count = payload.get("source_read_count")
    if not isinstance(source_read_count, int) or isinstance(source_read_count, bool):
        raise SystemExit(f"{path.name}: source_read_count must be a non-negative integer")
    if source_read_count < 0:
        raise SystemExit(f"{path.name}: source_read_count must be a non-negative integer")
    cited_sources = payload.get("cited_sources")
    if not isinstance(cited_sources, list) or not all(
        isinstance(item, str) for item in cited_sources
    ):
        raise SystemExit(f"{path.name}: cited_sources must be a string array")
    repo_calls = payload.get("repo_calls")
    if not isinstance(repo_calls, list) or not all(isinstance(item, str) for item in repo_calls):
        raise SystemExit(f"{path.name}: repo_calls must be a string array")
    if not isinstance(payload.get("memory_calls"), list) or not all(
        isinstance(item, str) for item in payload.get("memory_calls")
    ):
        raise SystemExit(f"{path.name}: memory_calls must be a string array")


def _is_positive_number(value: Any) -> bool:
    return _is_number(value) and value > 0


def _validate_source_summaries(path: Path, payload: dict, field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, list) or not value:
        raise SystemExit(f"{path.name}: {field} must be a non-empty array")
    for index, source in enumerate(value):
        if not isinstance(source, dict):
            raise SystemExit(f"{path.name}: {field}[{index}] must be an object")
        kind = source.get("kind")
        if kind not in {"file", "text"}:
            raise SystemExit(f"{path.name}: {field}[{index}].kind must be file or text")
        chars = source.get("chars")
        if not isinstance(chars, int) or isinstance(chars, bool) or chars < 0:
            raise SystemExit(f"{path.name}: {field}[{index}].chars must be a non-negative integer")
        if kind == "file" and not isinstance(source.get("path"), str):
            raise SystemExit(f"{path.name}: {field}[{index}].path must be a string")
        if kind == "text" and not isinstance(source.get("label"), str):
            raise SystemExit(f"{path.name}: {field}[{index}].label must be a string")


def validate_functional_token_economics_result(path: Path, payload: dict) -> None:
    positive_numeric_fields = ["baseline_tokens", "optimized_tokens"]
    for field in positive_numeric_fields:
        if not _is_positive_number(payload.get(field)):
            raise SystemExit(f"{path.name}: {field} must be a positive number")

    non_negative_numeric_fields = [
        "token_delta",
        "saving_ratio",
        "minimum_saving_ratio",
    ]
    for field in non_negative_numeric_fields:
        if not _is_number(payload.get(field)):
            raise SystemExit(f"{path.name}: {field} must be a non-negative number")

    accepted = payload.get("accepted")
    if accepted not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if not isinstance(payload.get("fixture_only"), bool):
        raise SystemExit(f"{path.name}: fixture_only must be boolean")
    if payload.get("fixture_only") is not True:
        raise SystemExit(f"{path.name}: fixture_only must be true for this fixture collection")
    for field in [
        "scenario_id",
        "workflow",
        "baseline_label",
        "optimized_label",
        "tokenizer",
        "token_source",
        "claim_scope",
        "acceptance_notes",
    ]:
        if not isinstance(payload.get(field), str) or not payload.get(field):
            raise SystemExit(f"{path.name}: {field} must be a non-empty string")

    _validate_source_summaries(path, payload, "baseline_sources")
    _validate_source_summaries(path, payload, "optimized_sources")
    if payload.get("baseline_source_count") != len(payload["baseline_sources"]):
        raise SystemExit(f"{path.name}: baseline_source_count does not match baseline_sources")
    if payload.get("optimized_source_count") != len(payload["optimized_sources"]):
        raise SystemExit(f"{path.name}: optimized_source_count does not match optimized_sources")
    if payload["token_delta"] != payload["baseline_tokens"] - payload["optimized_tokens"]:
        raise SystemExit(f"{path.name}: token_delta must equal baseline_tokens - optimized_tokens")
    if accepted == "yes" and payload["saving_ratio"] < payload["minimum_saving_ratio"]:
        raise SystemExit(f"{path.name}: accepted=yes but saving_ratio is below minimum_saving_ratio")


def validate_storage_v2_result(path: Path, benchmark_id: str, payload: dict) -> None:
    for field in ["dataset_id", "dataset_hash", "query_pack_id", "command", "hardware", "commit"]:
        if not isinstance(payload.get(field), str) or not payload.get(field):
            raise SystemExit(f"{path.name}: {field} must be a non-empty string")
    for field in [
        "entry_count",
        "json_file_count",
        "p50_ms",
        "p95_ms",
        "rss_peak_mb",
        "disk_bytes",
        "db_size_bytes",
        "sidecar_size_bytes",
    ]:
        if not _is_number(payload.get(field)):
            raise SystemExit(f"{path.name}: {field} must be a non-negative number")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    readiness = payload.get("claim_readiness")
    if not isinstance(readiness, dict):
        raise SystemExit(f"{path.name}: claim_readiness must be an object")
    if not isinstance(readiness.get("ready"), bool):
        raise SystemExit(f"{path.name}: claim_readiness.ready must be boolean")
    if not isinstance(readiness.get("source"), str) or not readiness.get("source"):
        raise SystemExit(f"{path.name}: claim_readiness.source must be a non-empty string")
    blocking = readiness.get("blocking")
    if not isinstance(blocking, list) or not all(isinstance(item, str) for item in blocking):
        raise SystemExit(f"{path.name}: claim_readiness.blocking must be a string array")

    if benchmark_id == "migration_roundtrip":
        for field in ["dry_run_checksum", "canonical_checksum", "rollback_checksum"]:
            if not isinstance(payload.get(field), str) or len(payload[field]) != 64:
                raise SystemExit(f"{path.name}: {field} must be a sha256 hex string")
        for field in ["apply_checksum_match", "rollback_checksum_match"]:
            if not isinstance(payload.get(field), bool):
                raise SystemExit(f"{path.name}: {field} must be boolean")
        if payload.get("accepted") == "yes" and not (
            payload["apply_checksum_match"] and payload["rollback_checksum_match"]
        ):
            raise SystemExit(f"{path.name}: accepted=yes requires both checksum matches")

    if benchmark_id == "local_index_fabric_smoke":
        for field in [
            "manifest_commit",
            "interrupted_generation_visible",
            "source_fingerprint_drift_detected",
        ]:
            if not isinstance(payload.get(field), bool):
                raise SystemExit(f"{path.name}: {field} must be boolean")
        if payload.get("accepted") == "yes" and payload["interrupted_generation_visible"]:
            raise SystemExit(f"{path.name}: accepted=yes requires interrupted generation to stay invisible")
    if benchmark_id == "canonical_store_runtime_baseline":
        if not isinstance(payload.get("canonical_row_count"), int):
            raise SystemExit(f"{path.name}: canonical_row_count must be an integer")
        if not isinstance(payload.get("checksum_match"), bool):
            raise SystemExit(f"{path.name}: checksum_match must be boolean")
    if benchmark_id == "rust_core_hot_path":
        if payload.get("rust_mode") not in {"rust", "python_fallback"}:
            raise SystemExit(f"{path.name}: rust_mode must be rust or python_fallback")
        if not isinstance(payload.get("native_available"), bool):
            raise SystemExit(f"{path.name}: native_available must be boolean")
    if benchmark_id == "index_fabric_runtime_conformance":
        for field in [
            "manifest_commit",
            "interrupted_generation_visible",
            "source_fingerprint_drift_detected",
            "search_backend_conformance",
        ]:
            if not isinstance(payload.get(field), bool):
                raise SystemExit(f"{path.name}: {field} must be boolean")
    if benchmark_id == "context_sufficiency_gate":
        if payload.get("sufficiency_status") not in {"sufficient", "partial", "insufficient"}:
            raise SystemExit(f"{path.name}: sufficiency_status has invalid value")
        if not isinstance(payload.get("safe_to_answer"), bool):
            raise SystemExit(f"{path.name}: safe_to_answer must be boolean")
        if not isinstance(payload.get("missing_evidence_count"), int):
            raise SystemExit(f"{path.name}: missing_evidence_count must be integer")
    if benchmark_id == "task_aware_wake_precision":
        if not _is_number(payload.get("precision_at_k")):
            raise SystemExit(f"{path.name}: precision_at_k must be a non-negative number")
        for field in ["budget_tokens", "budget_used_tokens"]:
            if not isinstance(payload.get(field), int) or payload[field] < 0:
                raise SystemExit(f"{path.name}: {field} must be a non-negative integer")
        if not isinstance(payload.get("safe_to_answer"), bool):
            raise SystemExit(f"{path.name}: safe_to_answer must be boolean")


def validate_memory_eval_matrix_result(path: Path, payload: dict) -> None:
    if payload.get("dimension") not in MEMORY_EVAL_DIMENSIONS:
        raise SystemExit(f"{path.name}: dimension has invalid value")
    for field in ["expected_source_ids", "retrieved_source_ids"]:
        if not isinstance(payload.get(field), list) or not all(
            isinstance(item, str) for item in payload[field]
        ):
            raise SystemExit(f"{path.name}: {field} must be a string array")
    if not isinstance(payload.get("safe_to_answer"), bool):
        raise SystemExit(f"{path.name}: safe_to_answer must be boolean")
    if not isinstance(payload.get("false_positive_count"), int) or payload["false_positive_count"] < 0:
        raise SystemExit(f"{path.name}: false_positive_count must be non-negative integer")
    if payload.get("artifact_state") not in {"accepted", "partial", "failed", "quarantined"}:
        raise SystemExit(f"{path.name}: artifact_state has invalid value")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if payload.get("accepted") == "yes" and payload.get("artifact_state") != "accepted":
        raise SystemExit(f"{path.name}: accepted=yes requires artifact_state=accepted")


def validate_retrieval_quality_pack_result(path: Path, payload: dict) -> None:
    capability = payload.get("capability")
    if capability not in RETRIEVAL_QUALITY_CAPABILITIES:
        raise SystemExit(f"{path.name}: capability has invalid value")
    if not isinstance(payload.get("default_enabled"), bool):
        raise SystemExit(f"{path.name}: default_enabled must be boolean")
    for field in [
        "precision_at_k",
        "recall_delta",
        "false_positive_delta",
        "fanout_cost",
        "duplicate_rate",
        "sufficiency_delta",
        "model_size_mb",
        "cold_start_ms",
    ]:
        if not _is_real_number(payload.get(field)):
            raise SystemExit(f"{path.name}: {field} must be a number")
    if not isinstance(payload.get("install_friction"), str) or not payload["install_friction"]:
        raise SystemExit(f"{path.name}: install_friction must be a non-empty string")
    readiness = payload.get("claim_readiness")
    if not isinstance(readiness, dict) or not isinstance(readiness.get("ready"), bool):
        raise SystemExit(f"{path.name}: claim_readiness.ready must be boolean")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if (
        capability == "query_rewriting"
        and payload.get("accepted") == "yes"
        and float(payload["recall_delta"]) <= float(payload["false_positive_delta"])
    ):
        raise SystemExit(
            f"{path.name}: accepted query_rewriting requires recall_delta > false_positive_delta"
        )


def validate_code_memory_federation_result(path: Path, payload: dict) -> None:
    for field in ["file_path", "source_id", "fingerprint", "claim_boundary"]:
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise SystemExit(f"{path.name}: {field} must be a non-empty string")
    line_range = payload.get("line_range")
    if line_range is not None and (
        not isinstance(line_range, list)
        or len(line_range) != 2
        or not all(isinstance(item, int) for item in line_range)
    ):
        raise SystemExit(f"{path.name}: line_range must be null or [start, end]")
    stale_check = payload.get("stale_check")
    if not isinstance(stale_check, dict) or not isinstance(stale_check.get("status"), str):
        raise SystemExit(f"{path.name}: stale_check.status must be present")
    if not isinstance(payload.get("current_code_symbols"), list):
        raise SystemExit(f"{path.name}: current_code_symbols must be an array")
    if not isinstance(payload.get("generated_layer_is_truth"), bool):
        raise SystemExit(f"{path.name}: generated_layer_is_truth must be boolean")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if payload.get("accepted") == "yes" and payload.get("generated_layer_is_truth") is not False:
        raise SystemExit(f"{path.name}: accepted=yes requires generated_layer_is_truth=false")


def validate_claim_promotion_pack_result(path: Path, payload: dict) -> None:
    if payload.get("claim_id") not in CLAIM_PROMOTION_CLAIMS:
        raise SystemExit(f"{path.name}: claim_id has invalid value")
    if payload.get("status") not in {"blocked", "bounded_ready", "public_ready"}:
        raise SystemExit(f"{path.name}: status has invalid value")
    for field in ["source_gate", "public_scope", "claim_type", "claim_boundary"]:
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise SystemExit(f"{path.name}: {field} must be a non-empty string")
    if not isinstance(payload.get("ready"), bool):
        raise SystemExit(f"{path.name}: ready must be boolean")
    blocking = payload.get("blocking")
    if not isinstance(blocking, list) or not all(isinstance(item, str) for item in blocking):
        raise SystemExit(f"{path.name}: blocking must be a string array")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if payload.get("claim_id") in {
        "storage_v2_speedup",
        "default_reranker_hyde",
        "code_memory_token_runtime",
    } and payload.get("status") != "blocked":
        raise SystemExit(f"{path.name}: unsafe promotion claims must stay blocked")


def validate_release_evidence_pack_result(path: Path, payload: dict) -> None:
    for field in ["pack_id", "snapshot_id", "claim_boundary"]:
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise SystemExit(f"{path.name}: {field} must be a non-empty string")
    for field in [
        "snapshot_run_count",
        "accepted_runs",
        "failed_runs",
        "unknown_runs",
        "blocked_claim_count",
        "bounded_claim_count",
    ]:
        if not isinstance(payload.get(field), int) or isinstance(payload[field], bool) or payload[field] < 0:
            raise SystemExit(f"{path.name}: {field} must be a non-negative integer")
    for field in [
        "packaged_suite_match",
        "packaged_snapshot_match",
        "claim_promotion_policy_enforced",
        "gate_passed",
    ]:
        if not isinstance(payload.get(field), bool):
            raise SystemExit(f"{path.name}: {field} must be boolean")
    if payload.get("accepted") not in {"yes", "no"}:
        raise SystemExit(f"{path.name}: accepted must be 'yes' or 'no'")
    if payload.get("accepted") == "yes" and not (
        payload["packaged_suite_match"]
        and payload["packaged_snapshot_match"]
        and payload["claim_promotion_policy_enforced"]
        and payload["gate_passed"]
        and payload["failed_runs"] == 0
        and payload["unknown_runs"] == 0
    ):
        raise SystemExit(
            f"{path.name}: accepted=yes requires package match, policy enforcement, gate pass, and no failed/unknown runs"
        )


def validate_memory_eval_matrix_bundle(payloads: list[dict]) -> None:
    covered = {payload.get("dimension") for payload in payloads}
    missing = sorted(MEMORY_EVAL_DIMENSIONS - covered)
    if missing:
        raise SystemExit(f"memory_eval_matrix missing dimensions: {', '.join(missing)}")


def validate_retrieval_quality_pack_bundle(payloads: list[dict]) -> None:
    covered = {payload.get("capability") for payload in payloads}
    missing = sorted(RETRIEVAL_QUALITY_CAPABILITIES - covered)
    if missing:
        raise SystemExit(f"retrieval_quality_pack missing capabilities: {', '.join(missing)}")


def validate_claim_promotion_pack_bundle(payloads: list[dict]) -> None:
    covered = {payload.get("claim_id") for payload in payloads}
    missing = sorted(CLAIM_PROMOTION_CLAIMS - covered)
    if missing:
        raise SystemExit(f"claim_promotion_pack missing claims: {', '.join(missing)}")


def validate_run(run_dir: Path, suite_path: Path = SUITE_PATH) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Missing run_manifest.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_id = manifest["benchmark_id"]

    suite = load_suite(suite_path)
    collection = None
    for item in suite["collections"]:
        if item["id"] == benchmark_id:
            collection = item
            break
    if collection is None:
        raise SystemExit(f"Unknown benchmark id in manifest: {benchmark_id}")

    missing = []
    for rel in collection["artifact_requirements"]:
        if not (run_dir / rel).exists():
            missing.append(rel)
    if missing:
        raise SystemExit(f"Missing required artifacts: {', '.join(missing)}")

    result_files = sorted((run_dir / "results").glob("*.json"))
    if not result_files:
        raise SystemExit("No result JSON files found under results/")

    required_fields = collection["required_result_fields"]
    requires_token_usage = False
    if benchmark_id == "client_enabled_vs_disabled" and int(
        manifest.get("result_schema_version", 1)
    ) >= 2:
        required_fields = [*required_fields, "token_usage"]
        requires_token_usage = True
    checked = 0
    payloads: list[dict] = []
    for path in result_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append(payload)
        for field in required_fields:
            if field not in payload:
                raise SystemExit(f"{path.name}: missing field '{field}'")
        if requires_token_usage:
            validate_token_usage(path, payload)
        if benchmark_id == "memory_shortcut_vs_source_recovery":
            validate_memory_shortcut_result(path, payload)
        if benchmark_id == "functional_token_economics":
            validate_functional_token_economics_result(path, payload)
        if benchmark_id in STORAGE_V2_BENCHMARKS:
            validate_storage_v2_result(path, benchmark_id, payload)
        if benchmark_id == "memory_eval_matrix":
            validate_memory_eval_matrix_result(path, payload)
        if benchmark_id == "retrieval_quality_pack":
            validate_retrieval_quality_pack_result(path, payload)
        if benchmark_id == "code_memory_federation":
            validate_code_memory_federation_result(path, payload)
        if benchmark_id == "claim_promotion_pack":
            validate_claim_promotion_pack_result(path, payload)
        if benchmark_id == "release_evidence_pack":
            validate_release_evidence_pack_result(path, payload)
        checked += 1

    if benchmark_id == "memory_eval_matrix":
        validate_memory_eval_matrix_bundle(payloads)
    if benchmark_id == "retrieval_quality_pack":
        validate_retrieval_quality_pack_bundle(payloads)
    if benchmark_id == "claim_promotion_pack":
        validate_claim_promotion_pack_bundle(payloads)

    return {
        "benchmark_id": benchmark_id,
        "result_count": checked,
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a benchmark run bundle.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    result = validate_run(Path(args.run_dir))
    print(f"OK: validated {result['result_count']} result files for {result['benchmark_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
