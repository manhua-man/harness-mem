"""Report evidence prompt contracts only; no model, host or data access."""
import pytest

from harness_mem.autonomous.models import DREAM_SOURCE_RECHECK_CONTRACT
from harness_mem.autonomous.provider import (
    _REPORT_SUBSTANTIVE_EVIDENCE_CONTRACT,
    _build_assimilation_prompt,
    _build_verification_prompt,
)


@pytest.mark.parametrize("contract,native_final,route_guard", [
    (DREAM_SOURCE_RECHECK_CONTRACT, False, "Return SourceClassificationDecision JSON only"),
    ("final-knowledge-scope-v1", True, "Return NativeFinalScopeDecision JSON"),
    ("candidate-verification-v1", False, "Verify each candidate against only its supplied source excerpts"),
    ("final-knowledge-scope-v1", False, "missing, unclear, or dropping verdict defers the entire replacement"),
])
def test_actual_verification_routes_share_substantive_report_evidence_rule(contract, native_final, route_guard):
    prompt = _build_verification_prompt(
        {"contract_version": contract, "candidates": []}, native_final_transport=native_final,
    )
    assert route_guard in prompt
    assert prompt.count(_REPORT_SUBSTANTIVE_EVIDENCE_CONTRACT) == 1
    for clause in (
        "For a typed source_report",
        "a number or one-time event defines the reported conclusion",
        "causal evidence, comparison result or necessary limit",
        "do not classify it as temporary solely because it is single-run or date-scoped",
        "those limits constrain extrapolation, not its substantive meaning",
    ):
        assert clause in prompt


def test_rule_preserves_report_authority_and_temporary_counterexamples():
    contract = _REPORT_SUBSTANTIVE_EVIDENCE_CONTRACT
    for clause in (
        "Retain only the original speaker's bounded period report",
        "do not upgrade it to external current truth",
        "Ordinary progress, call statistics and static-pass counts with no substantive meaning may remain temporary",
        "Do not retain every number",
        "judge its role in the complete source account",
    ):
        assert clause in contract
    # This is a general distinction, with no target identity or case figures.
    assert not any(value in contract for value in (
        "HM", "Mem0", "85.17", "54.34", "74183", "20228", "1.57", "3.67", "User38",
    ))
    assert len(contract) < 650


def test_existing_classification_and_final_gates_remain_explicit():
    classification = _build_verification_prompt({
        "contract_version": DREAM_SOURCE_RECHECK_CONTRACT, "candidates": [],
    })
    assert "This classification schema has no edit, proposal or final-judgment fields" in classification
    assert "Original current knowledge and prior summaries are not evidence" in classification
    assert "Do not promote a mixed original wholesale" in classification
    final = _build_verification_prompt({
        "contract_version": "final-knowledge-scope-v1", "candidates": [],
    }, native_final_transport=True)
    for clause in (
        "Current memory and proposed_update_meaning_judgment are not proof",
        "Missing inventory, units, omission roles or required source evidence cannot be replaced",
        "All normal complete final-scope, whole-update, report-authority and commit checks remain",
    ):
        assert clause in final


def test_general_run_metric_rule_explicitly_defers_to_typed_report_evidence():
    prompt = _build_verification_prompt({"candidates": []})
    assert "For content outside the typed source_report evidence rule below" in prompt
    assert "particular identifier value is session_only" in prompt
    assert "task envelope is session_only" in prompt


def test_existing_assimilation_prose_bound_is_unchanged():
    prompt = _build_assimilation_prompt({"verified_candidates": []})
    assert len(prompt) < 5500
    assert _REPORT_SUBSTANTIVE_EVIDENCE_CONTRACT not in prompt
