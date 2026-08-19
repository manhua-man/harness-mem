"""Unified, machine-readable runner for the distill acceptance matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from statistics import median
from typing import Any

from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import (
    DEFAULT_DISTILL_MODEL,
    DEFAULT_DISTILL_TIMEOUT_SECONDS,
    CodexExecProvider,
    ProviderError,
    ProviderResult,
    ResponsesApiProvider,
)
from harness_mem.autonomous.worker import (
    build_provider_manifest,
    normalize_provider_review_state,
    provider_candidate_control_reason,
)
from harness_mem.mcp.distill_projection import (
    build_distill_compact_outline,
    render_distill_exchange_windows,
)
from harness_mem.mcp.response_budget import serialized_result_tokens
from harness_mem.qualification.distill_fixture_catalog import (
    catalog_fingerprint,
    fixture,
)


PATH_TESTS: dict[str, tuple[str, ...]] = {
    "A1": (
        "code/tests/test_distill_acceptance.py::test_a1_compact_fixture_is_complete_and_honestly_budgeted",
        "code/tests/test_distill_projection.py::test_compact_outline_expands_instead_of_silently_dropping_coverage",
    ),
    "A2": (
        "code/tests/test_distill_acceptance.py::test_a2_full_and_compact_share_complete_exchange_coverage",
    ),
    "A3": (
        "code/tests/test_distill_acceptance.py::test_a3_drilldown_restores_begin_middle_end_and_rejects_out_of_range",
    ),
    "A4": (
        "code/tests/test_distill_acceptance.py::test_a4_raw_fixture_query_and_chunk_proof",
    ),
    "A5": (
        "code/tests/test_lossless_distill_mcp.py::test_mcp_reads_every_lossless_chunk_before_final_review",
        "code/tests/test_lossless_distill_mcp.py::test_finalize_does_not_auto_review_before_all_chunks_complete",
    ),
    "B1": (
        "code/tests/test_distill_acceptance.py::test_b1_f2_user_preference_promotes_once_and_is_retrievable",
        "code/tests/test_evidence_admission.py::test_explicit_user_statement_can_promote_but_transcript_only_cannot",
    ),
    "B2": (
        "code/tests/test_outcome_probe.py::test_partial_distill_runtime_outcome_probe",
        "code/tests/test_distill_acceptance.py::test_b2_unbound_handoff_cannot_satisfy_job_gate",
        "code/tests/test_distill_acceptance.py::test_b2_autonomous_partial_creates_handoff_and_only_one_truth",
    ),
    "B3": (
        "code/tests/test_distill_acceptance.py::test_b3_f1_zero_candidate_closes_without_pending_noise",
    ),
    "B4": (
        "code/tests/test_lossless_distill_mcp.py::test_finalize_promotes_answered_candidate_independently_of_session_handoff",
        "code/tests/test_lossless_distill_mcp.py::test_semantic_review_blocks_promotion_and_dream",
    ),
    "B5": (
        "code/tests/test_lossless_distill_mcp.py::test_legacy_observations_do_not_create_a_lossless_distill_job",
    ),
    "B6": (
        "code/tests/test_lossless_distill_mcp.py::test_explicit_session_rechecks_legacy_signal_false_negative",
        "code/tests/test_lossless_distill_mcp.py::test_signal_gate_recheck_does_not_reopen_ineligible_jobs",
    ),
    "C1": (
        "code/tests/test_lossless_distill_mcp.py::test_prepare_session_distill_claims_explicit_active_job",
        "code/tests/test_lossless_distill_mcp.py::test_prepare_session_distill_activates_explicit_parked_session",
    ),
    "C2": (
        "code/tests/test_distill_acceptance.py::test_c2_three_job_batch_defers_only_failure_and_continues",
    ),
    "C3": (
        "code/tests/test_autonomous_distill_worker.py::test_autonomous_worker_completes_job_materializes_note_and_receipt",
    ),
    "C4": (
        "code/tests/test_session_distill_store.py::test_rebalance_uses_three_recent_then_one_oldest_lane",
        "code/tests/test_distill_lifecycle.py::test_agent_active_drainer_enforces_daily_new_job_budget",
    ),
    "D1": (
        "code/tests/test_evidence_admission.py::test_repository_evidence_promotes_only_while_digest_is_current",
        "code/tests/test_evidence_admission.py::test_repository_change_rejects_candidate_and_proposes_matching_truth_history",
    ),
    "D2": (
        "code/tests/test_distill_acceptance.py::test_d2_assistant_role_cannot_impersonate_user_statement",
    ),
    "D3": (
        "code/tests/test_evidence_admission.py::test_answer_gate_status_is_runtime_derived",
        "code/tests/test_evidence_admission.py::test_evidence_admission_golden_policy_matrix",
    ),
    "E1": (
        "code/tests/test_distill_acceptance.py::test_e1_finalize_replay_keeps_note_hash_and_truth_count",
    ),
    "E2": (
        "code/tests/test_session_distill_store.py::test_review_lease_is_exclusive_and_expired_owner_is_recovered",
        "code/tests/test_session_distill_store.py::test_active_review_lease_guards_final_write_boundary",
    ),
    "E3": (
        "code/tests/test_distill_acceptance.py::test_e3_provider_failure_has_no_note_and_next_job_continues",
    ),
    "E4": (
        "code/tests/test_distill_acceptance.py::test_e4_note_write_failure_never_advances_latest_and_retry_recovers",
    ),
    "E5": (
        "code/tests/test_distill_acceptance.py::test_e5_projects_isolate_sessions_candidates_handoffs_and_search",
    ),
    "E6": (
        "code/tests/test_processed_source_cleanup.py::test_cleanup_prunes_raw_evidence_and_preserves_sanitized_truth",
        "code/tests/test_processed_source_cleanup.py::test_cleanup_completes_no_candidate_session_without_creating_truth",
        "code/tests/test_processed_source_cleanup.py::test_unsupported_native_cleanup_retains_all_local_evidence",
        "code/tests/test_processed_source_cleanup.py::test_existing_post_turn_maintenance_retries_partial_failure",
    ),
    "F8": (
        "code/tests/test_assimilation_shadow.py::test_f8_multi_promotion_points_terminate_independently",
    ),
    "F9": (
        "code/tests/test_assimilation_shadow.py::test_f9_separates_a_one_off_request_from_a_durable_preference",
    ),
    "F10": (
        "code/tests/test_assimilation_shadow.py::test_f10_preserves_confirm_refine_and_conflict_as_distinct_outcomes",
    ),
    "F11": (
        "code/tests/test_assimilation_shadow.py::test_f11_clean_projection_excludes_audit_metadata",
    ),
}


@dataclass(frozen=True)
class PathResult:
    path_id: str
    status: str
    tests: tuple[str, ...]
    duration_seconds: float
    returncode: int


def _run_pytest(nodes: tuple[str, ...], *, cwd: Path) -> tuple[int, float, str]:
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *nodes],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode, time.monotonic() - started, output[-4000:]


def run_l1(*, project_root: Path) -> dict[str, Any]:
    results: list[PathResult] = []
    outputs: dict[str, str] = {}
    for path_id, nodes in PATH_TESTS.items():
        returncode, duration, output = _run_pytest(nodes, cwd=project_root)
        results.append(
            PathResult(
                path_id=path_id,
                status="passed" if returncode == 0 else "failed",
                tests=nodes,
                duration_seconds=round(duration, 3),
                returncode=returncode,
            )
        )
        if returncode != 0:
            outputs[path_id] = output
    passed = sum(item.status == "passed" for item in results)
    return {
        "status": "passed" if passed == len(results) else "failed",
        "passed": passed,
        "total": len(results),
        "paths": [asdict(item) for item in results],
        "failure_output": outputs,
    }


def _fixture_packet(fixture_id: str) -> dict[str, Any]:
    item = fixture(fixture_id)
    compact, summary = build_distill_compact_outline(
        str(item["transcript"]),
        budget_tokens=3000,
    )
    refs = [
        {
            "exchange_index": index,
            "content_sha256": window["content_sha256"],
        }
        for index in summary.get("zero_candidate_required_exchange_indexes", [])
        for window in render_distill_exchange_windows(str(item["transcript"]), [index])
    ]
    checks = {
        "user_correction": "absent",
        "explicit_decision": "absent",
        "successful_solution": "absent",
        "repeated_failure": "absent",
        "rule_or_preference": "absent",
        "reusable_workflow_or_fact": "absent",
        "version_or_migration": "absent",
        "unfinished_handoff": "absent",
    }
    reasons = summary.get("zero_candidate_required_exchange_reasons", {})
    for signals in reasons.values():
        for signal in signals:
            if signal in checks:
                checks[signal] = "candidate_required"
    packet: dict[str, Any] = {
        "project_name": "distill-acceptance",
        "session_id": fixture_id,
        "distill_job_id": f"fixture-job-{fixture_id}",
        "source_revision": "sha256:" + hashlib.sha256(
            str(item["transcript"]).encode("utf-8")
        ).hexdigest(),
        "expected_chunk_count": 1,
        "completed_chunk_count": 1,
        "semantic_evidence": {
            "projection": summary.get("projection"),
            "exchange_count": summary.get("exchange_count"),
            "risk_exchange_count": summary.get("risk_exchange_count"),
            "content_sha256": hashlib.sha256(compact.encode("utf-8")).hexdigest(),
            "source_revision": None,
            "chunks": [{"chunk_index": 0, "content": compact}],
        },
        "semantic_decision_exchanges": [
            window
            for ref in refs
            for window in render_distill_exchange_windows(
                str(item["transcript"]), [ref["exchange_index"]]
            )
        ],
        "zero_candidate_exchange_refs": refs,
        "zero_candidate_challenge_template": {
            "version": "v1",
            "source_revision": "sha256:" + hashlib.sha256(
                str(item["transcript"]).encode("utf-8")
            ).hexdigest(),
            "evidence_fidelity": "complete",
            "future_utility": (
                "durable" if any(value == "candidate_required" for value in checks.values()) else "none"
            ),
            "checks": checks,
            "inspected_exchange_refs": refs,
            "conclusion": (
                "candidate_required"
                if any(value == "candidate_required" for value in checks.values())
                else "no_durable_candidate"
            ),
            "rationale": "Fixture template requires a complete evidence-grounded decision.",
        },
    }
    tokens, tokenizer, chars = serialized_result_tokens(packet)
    packet["response_budget"] = {
        "contract_version": "serialized-response-budget-v1",
        "scope": "mcp_content_text",
        "requested_target_tokens": 3000,
        "serialized_tokens": tokens,
        "serialized_chars": chars,
        "tokenizer": tokenizer,
        "outcome": "within_target" if tokens <= 3000 else "expanded_for_required_metadata",
        "reason": None if tokens <= 3000 else "complete fixture packet exceeds soft target",
        "hard_truncation_applied": False,
    }
    return packet


def _quality(fixture_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    expected = dict(fixture(fixture_id)["expected"])
    raw_candidates = list(decision.get("candidates") or [])
    typed_decision = normalize_provider_review_state(
        AutonomousDecision.model_validate(decision)
    )
    review = typed_decision.semantic_review.model_dump(mode="json", exclude_none=True)
    filtered: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for candidate in typed_decision.candidates:
        dumped = candidate.model_dump(mode="json", exclude_none=True)
        reason = provider_candidate_control_reason(
            candidate,
            decision=typed_decision,
        )
        if reason is None:
            candidates.append(dumped)
        else:
            filtered.append({"candidate": dumped, "reason": reason})
    candidate_count_ok = len(candidates) == int(expected.get("candidate_count", 0))
    promotion_ok = review.get("promotion_decision") == expected.get("promotion_decision")
    unfinished_ok = bool(review.get("unfinished_work")) is bool(expected.get("unfinished"))
    basis_ok = True
    terms_ok = True
    if candidates:
        basis_ok = candidates[0].get("evidence_basis") == expected.get("candidate_basis")
        content = " ".join(str(item.get("content") or "") for item in candidates).lower()
        groups = expected.get("required_term_groups")
        if groups:
            terms_ok = all(
                any(str(term).lower() in content for term in group)
                for group in groups
            )
        else:
            terms_ok = all(
                term.lower() in content
                for term in expected.get("required_terms", [])
            )
    checks = {
        "candidate_count": candidate_count_ok,
        "promotion_decision": promotion_ok,
        "unfinished_work": unfinished_ok,
        "evidence_basis": basis_ok,
        "required_terms": terms_ok,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "raw_candidate_count": len(raw_candidates),
        "effective_candidate_count": len(candidates),
        "filtered_control_candidates": filtered,
    }


def _model_sample_status(
    *,
    quality_passed: bool,
    token_complete: bool,
    warnings: list[str],
) -> str:
    if not quality_passed or not token_complete:
        return "failed"
    if warnings:
        return "warning"
    return "passed"


def _recover_prior_green_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover the measured baseline that an older report compared against."""

    recovered: list[dict[str, Any]] = []
    for item in payload.get("samples", []):
        if not isinstance(item, dict):
            continue
        provider = item.get("provider") or {}
        regression = item.get("regression") or {}
        token_delta = regression.get("token_delta_ratio")
        duration_delta = regression.get("duration_delta_ratio")
        if (
            item.get("fixture_catalog") != catalog_fingerprint()
            or regression.get("baseline_available") is not True
            or not isinstance(token_delta, (int, float))
            or not isinstance(duration_delta, (int, float))
            or float(token_delta) <= -1.0
            or float(duration_delta) <= -1.0
        ):
            continue
        current_tokens = int(provider.get("total_tokens") or 0)
        current_duration = float(provider.get("duration_seconds") or 0.0)
        if current_tokens <= 0 or current_duration <= 0:
            continue
        recovered.append(
            {
                "fixture_id": item.get("fixture_id"),
                "status": "passed",
                "fixture_catalog": item.get("fixture_catalog"),
                "provider": {
                    "model": provider.get("model"),
                    "total_tokens": round(current_tokens / (1.0 + float(token_delta))),
                    "duration_seconds": current_duration
                    / (1.0 + float(duration_delta)),
                },
                "baseline_recovered_from": "prior_regression_receipt",
            }
        )
    return recovered


def _duration_regression(
    *,
    baseline_duration: float,
    recent_durations: list[float],
) -> dict[str, Any]:
    usable = [float(value) for value in recent_durations if float(value) > 0][-3:]
    if baseline_duration <= 0:
        return {
            "duration_gate_ready": False,
            "duration_sample_count": len(usable),
            "duration_delta_ratio": None,
        }
    observed = median(usable) if len(usable) >= 3 else usable[-1] if usable else 0.0
    return {
        "duration_gate_ready": len(usable) >= 3,
        "duration_sample_count": len(usable),
        "duration_statistic": "recent_3_median" if len(usable) >= 3 else "single_observation",
        "duration_observed_seconds": observed,
        "duration_delta_ratio": (observed - baseline_duration) / baseline_duration,
    }


class _ModelSampleProviderError(ProviderError):
    def __init__(
        self,
        source: ProviderError,
        *,
        attempt_count: int,
        attempt_errors: list[dict[str, str]],
    ) -> None:
        super().__init__(str(source), kind=source.kind, exit_code=source.exit_code)
        self.attempt_count = attempt_count
        self.attempt_errors = attempt_errors


def _decide_model_sample_with_fallback(
    manifest: dict[str, Any],
    *,
    runtime_dir: Path,
    model: str | None,
) -> tuple[ProviderResult, list[dict[str, str]]]:
    """Prefer Responses API; fall back to Codex exec if provider is unavailable."""

    providers = (
        (
            "responses_api",
            ResponsesApiProvider(
                model=model or DEFAULT_DISTILL_MODEL,
                timeout_seconds=DEFAULT_DISTILL_TIMEOUT_SECONDS,
            ),
        ),
        (
            "codex_exec",
            CodexExecProvider(
                model=model or DEFAULT_DISTILL_MODEL,
                timeout_seconds=DEFAULT_DISTILL_TIMEOUT_SECONDS,
            ),
        ),
    )
    attempt_failures: list[dict[str, str]] = []
    for provider_name, provider in providers:
        try:
            result, transient_failures = _decide_model_sample_with_retry(
                provider,
                manifest,
                runtime_dir=runtime_dir,
            )
            combined_failures = attempt_failures + [
                {"provider": provider_name, **item}
                for item in transient_failures
            ]
            return result, combined_failures
        except ProviderError as exc:
            attempt_failures.append(
                {
                    "provider": provider_name,
                    "kind": exc.kind,
                    "message": str(exc)[:1000],
                }
            )
            if (
                provider_name == "responses_api"
                and exc.kind == "setup_required"
            ):
                continue
            raise _ModelSampleProviderError(
                exc,
                attempt_count=int(getattr(exc, "attempt_count", 1)),
                attempt_errors=attempt_failures,
            ) from exc
    raise _ModelSampleProviderError(
        ProviderError(
            "No available model provider for sample",
            kind="setup_required",
            exit_code=None,
        ),
        attempt_count=1,
        attempt_errors=attempt_failures,
    )


def _decide_model_sample_with_retry(
    provider: Any,
    manifest: dict[str, Any],
    *,
    runtime_dir: Path,
    max_attempts: int = 2,
) -> tuple[ProviderResult, list[dict[str, str]]]:
    """Retry one transient provider failure without masking stable failures."""

    transient_failures: list[dict[str, str]] = []
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            result = provider.decide(manifest, runtime_dir=runtime_dir)
        except ProviderError as exc:
            if exc.kind == "transient":
                transient_failures.append(
                    {"kind": exc.kind, "message": str(exc)[:1000]}
                )
            if exc.kind != "transient" or attempt >= attempts:
                raise _ModelSampleProviderError(
                    exc,
                    attempt_count=attempt,
                    attempt_errors=list(transient_failures),
                ) from exc
            continue
        return (
            replace(
                result,
                attempt_count=max(1, int(result.attempt_count))
                + len(transient_failures),
            ),
            transient_failures,
        )
    raise AssertionError("model sample retry loop did not return")


def run_model_samples(
    *,
    output_path: Path,
    model: str | None = None,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    previous: dict[str, dict[str, Any]] = {}
    baseline_path = output_path.with_name(output_path.stem + "-baseline.json")
    history_path = output_path.with_name(output_path.stem + "-history.json")
    try:
        prior_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            current_payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current_payload = {}
        prior_payload = {
            "samples": _recover_prior_green_samples(current_payload),
        }
    for item in prior_payload.get("samples", []):
        if (
            isinstance(item, dict)
            and item.get("status") == "passed"
            and item.get("fixture_catalog") == catalog_fingerprint()
        ):
            previous[str(item.get("fixture_id") or "")] = item
    try:
        history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        history_payload = {"schema_version": 1, "series": {}}
    history_series = history_payload.get("series")
    if not isinstance(history_series, dict):
        history_series = {}
    if not history_series:
        for fixture_id, item in previous.items():
            provider_receipt = item.get("provider") or {}
            manifest_sha = str(item.get("manifest_sha256") or "")
            model_name = str(provider_receipt.get("model") or "")
            duration = float(provider_receipt.get("duration_seconds") or 0.0)
            tokens = int(provider_receipt.get("total_tokens") or 0)
            if manifest_sha and model_name and duration > 0 and tokens > 0:
                history_series[f"{fixture_id}|{model_name}|{manifest_sha}"] = [
                    {
                        "duration_seconds": duration,
                        "total_tokens": tokens,
                        "source": "green_baseline",
                    }
                ]

    for fixture_id in ("F1", "F2", "F3"):
        packet = _fixture_packet(fixture_id)
        manifest = build_provider_manifest(packet)
        manifest_sha = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="hm-distill-model-") as temporary:
                result, transient_failures = _decide_model_sample_with_fallback(
                    manifest,
                    runtime_dir=Path(temporary),
                    model=(model or DEFAULT_DISTILL_MODEL),
                )
            decision = result.decision.model_dump(mode="json", exclude_none=True)
            quality = _quality(fixture_id, decision)
            receipt = result.receipt()
            wall_duration = time.monotonic() - started
            duration_regression = {
                "duration_gate_ready": False,
                "duration_delta_ratio": None,
            }
            token_complete = receipt.get("total_tokens") is not None
            warnings = []
            if not token_complete:
                warnings.append("usage_missing")
            if int(receipt.get("total_tokens") or 0) > 15_000:
                warnings.append("provider_tokens_over_15000")
            if float(receipt.get("duration_seconds") or 0.0) > 40.0:
                warnings.append("provider_duration_over_40s")
            if wall_duration > 60.0:
                warnings.append("wall_duration_over_60s")
            prior = previous.get(fixture_id)
            regression: dict[str, Any] = {"baseline_available": False}
            if (
                prior
                and (prior.get("provider") or {}).get("model") == receipt.get("model")
            ):
                prior_tokens = int((prior.get("provider") or {}).get("total_tokens") or 0)
                prior_duration = float(
                    (prior.get("provider") or {}).get("duration_seconds") or 0.0
                )
                series_key = f"{fixture_id}|{receipt.get('model')}|{manifest_sha}"
                measurements = history_series.get(series_key)
                if not isinstance(measurements, list):
                    measurements = []
                measurements.append(
                    {
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": float(
                            receipt.get("duration_seconds") or 0.0
                        ),
                        "total_tokens": int(receipt.get("total_tokens") or 0),
                    }
                )
                history_series[series_key] = measurements[-20:]
                token_delta = (
                    (int(receipt.get("total_tokens") or 0) - prior_tokens)
                    / prior_tokens
                    if prior_tokens
                    else None
                )
                duration_regression = _duration_regression(
                    baseline_duration=prior_duration,
                    recent_durations=[
                        float(measurement.get("duration_seconds") or 0.0)
                        for measurement in history_series[series_key]
                        if isinstance(measurement, dict)
                    ],
                )
                regression = {
                    "baseline_available": True,
                    "token_delta_ratio": token_delta,
                    **duration_regression,
                }
                if token_delta is not None and token_delta > 0.2:
                    warnings.append("provider_tokens_regressed_over_20pct")
            if (
                duration_regression["duration_gate_ready"]
                and duration_regression["duration_delta_ratio"] is not None
                and duration_regression["duration_delta_ratio"] > 0.2
            ):
                warnings.append("provider_duration_regressed_over_20pct")
            status = _model_sample_status(
                quality_passed=quality["passed"],
                token_complete=token_complete,
                warnings=warnings,
            )
            normalized_status = "passed" if status == "warning" else status
            samples.append(
                {
                    "fixture_id": fixture_id,
                    "status": normalized_status,
                    "manifest_sha256": manifest_sha,
                    "fixture_catalog": catalog_fingerprint(),
                    "provider": receipt,
                    "provider_transient_failures": transient_failures,
                    "wall_duration_seconds": round(wall_duration, 3),
                    "quality": quality,
                    "compact_response": packet["response_budget"],
                    "regression": regression,
                    "warnings": warnings,
                    "decision": decision,
                }
            )
        except ProviderError as exc:
            samples.append(
                {
                    "fixture_id": fixture_id,
                    "status": "failed",
                    "manifest_sha256": manifest_sha,
                    "fixture_catalog": catalog_fingerprint(),
                    "schema_valid": False,
                    "attempt_count": int(getattr(exc, "attempt_count", 1)),
                    "attempt_errors": list(getattr(exc, "attempt_errors", [])),
                    "error": {"kind": exc.kind, "message": str(exc)[:1000]},
                }
            )
    passed = sum(item["status"] == "passed" for item in samples)
    warned = sum(item["status"] == "warning" for item in samples)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "passed" if passed + warned == len(samples) else "failed"
        ),
        "passed": passed + warned,
        "warned": warned,
        "total": len(samples),
        "samples": samples,
        "baseline_path": str(baseline_path),
        "history_path": str(history_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps(
            {"schema_version": 1, "series": history_series},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if payload["status"] == "passed" and not baseline_path.exists():
        baseline_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-samples", action="store_true")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    started = time.monotonic()
    l1 = run_l1(project_root=project_root)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_catalog": catalog_fingerprint(),
        "l1": l1,
        "model_samples": {"status": "not_run"},
    }
    if args.model_samples and l1["status"] == "passed":
        model_path = args.output.with_name(args.output.stem + "-model.json")
        report["model_samples"] = run_model_samples(
            output_path=model_path,
            model=args.model,
        )
        report["model_report_path"] = str(model_path)
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    report["status"] = (
        "passed"
        if l1["status"] == "passed"
        and (
            not args.model_samples
            or report["model_samples"].get("status") == "passed"
        )
        else "failed"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PATH_TESTS",
    "_model_sample_status",
    "_duration_regression",
    "_recover_prior_green_samples",
    "run_l1",
    "run_model_samples",
]
