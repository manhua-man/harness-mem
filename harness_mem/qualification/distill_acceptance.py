"""Unified, machine-readable runner for the distill acceptance matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import ProviderError
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
        # A memory expresses its user-visible statement through ``content``;
        # a rule expresses the same durable meaning through ``pattern`` and
        # ``trigger``.  Quality must judge the emitted knowledge, not assume
        # that every valid candidate used the memory schema.
        content = " ".join(
            str(item.get(field) or "")
            for item in candidates
            for field in ("content", "pattern", "trigger")
        ).lower()
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


def run_model_samples(
    *,
    output_path: Path,
    provider: Any,
    fixture_ids: tuple[str, ...] = ("F1", "F2", "F3"),
    stop_on_failure: bool = True,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []

    for fixture_id in fixture_ids:
        packet = _fixture_packet(fixture_id)
        manifest = build_provider_manifest(packet)
        manifest_sha = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(
                prefix="hm-distill-model-",
                dir=output_path.parent,
            ) as temporary:
                result = provider.decide(
                    manifest,
                    runtime_dir=Path(temporary),
                )
            decision = result.decision.model_dump(mode="json", exclude_none=True)
            quality = _quality(fixture_id, decision)
            receipt = result.receipt()
            wall_duration = time.monotonic() - started
            samples.append(
                {
                    "fixture_id": fixture_id,
                    "status": "passed" if quality["passed"] else "failed",
                    "manifest_sha256": manifest_sha,
                    "fixture_catalog": catalog_fingerprint(),
                    "provider": receipt,
                    "wall_duration_seconds": round(wall_duration, 3),
                    "quality": quality,
                    "compact_response": packet["response_budget"],
                    "usage_available": receipt.get("total_tokens") is not None,
                    "decision": decision,
                }
            )
            if not quality["passed"] and stop_on_failure:
                break
        except ProviderError as exc:
            samples.append(
                {
                    "fixture_id": fixture_id,
                    "status": "failed",
                    "manifest_sha256": manifest_sha,
                    "fixture_catalog": catalog_fingerprint(),
                    "schema_valid": False,
                    "attempt_count": 1,
                    "error": {"kind": exc.kind, "message": str(exc)[:1000]},
                }
            )
            if stop_on_failure:
                break
    passed = sum(item["status"] == "passed" for item in samples)
    failed = sum(item["status"] == "failed" for item in samples)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if failed else "passed",
        "passed": passed,
        "failed": failed,
        "total": len(samples),
        "planned_total": len(fixture_ids),
        "stopped_early": len(samples) < len(fixture_ids),
        "samples": samples,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-samples", action="store_true")
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
        try:
            from harness_mem.autonomous.executors.registry import (
                build_semantic_executor,
            )
            from harness_mem.commands.support import detect_runtime_client
            from harness_mem.config.merge import load_merged_config

            provider = build_semantic_executor(
                load_merged_config(project_root),
                detect_runtime_client() or "unknown",
            )
            report["model_samples"] = run_model_samples(
                output_path=model_path,
                provider=provider,
            )
        except ProviderError as exc:
            report["model_samples"] = {
                "status": "failed",
                "passed": 0,
                "failed": 3,
                "total": 3,
                "error": {"kind": exc.kind, "message": str(exc)[:1000]},
            }
        report["model_report_path"] = str(model_path)
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    model_status = report["model_samples"].get("status")
    report["status"] = (
        "failed" if l1["status"] != "passed" or model_status == "failed" else "passed"
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
    "run_l1",
    "run_model_samples",
]
