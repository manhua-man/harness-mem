"""Prompt contracts align with exact shared checks; no provider/model calls."""
import pytest

from harness_mem.autonomous.models import DREAM_SOURCE_RECHECK_CONTRACT, SourceClassificationDecision
from harness_mem.autonomous.provider import (
    _REPORT_SCOPE_QUALIFIER_CONTRACT,
    _UPDATE_MEANING_LITERAL_CONTRACT,
    _build_assimilation_prompt,
    _build_verification_prompt,
)


@pytest.mark.parametrize("builder,manifest", [
    (_build_assimilation_prompt, {}),
    (_build_assimilation_prompt, {"maintenance_candidates": [{"candidate_id": "fixture"}]}),
    (_build_verification_prompt, {"contract_version": "final-knowledge-scope-v1", "candidates": []}),
    (_build_verification_prompt, {"contract_version": "candidate-verification-v1", "candidates": []}),
])
def test_shared_literal_contract_covers_exact_binding_and_complete_meaning(builder, manifest):
    prompt = builder(manifest)
    assert prompt.count(_UPDATE_MEANING_LITERAL_CONTRACT) == 1
    for clause in [
        "Bind predecessor_statements/versions and successor_statements exactly in order",
        "Independently list ALL applicable predecessor_conditions/undecided_state",
        "verbatim final-successor substrings",
        "no paraphrase, omission or emptying to pass",
        "If meaning cannot be fully retained and literally bound",
        "vote drops_applicable_meaning/unclear; do not write or rewrite during verification",
    ]:
        assert clause in prompt
    assert len(_UPDATE_MEANING_LITERAL_CONTRACT) <= 400


def test_report_scope_clarification_is_scoped_to_maintenance_and_verification():
    assert _REPORT_SCOPE_QUALIFIER_CONTRACT not in _build_assimilation_prompt({})
    for prompt in [
        _build_assimilation_prompt({"maintenance_candidates": [{}]}),
        _build_verification_prompt({"contract_version": "final-knowledge-scope-v1", "candidates": []}),
    ]:
        assert prompt.count(_REPORT_SCOPE_QUALIFIER_CONTRACT) == 1
        assert "original speaker, dated period, native source identity" in prompt
        assert "not-independent-evidence boundary remain required attribution and scope qualifiers" in prompt
        assert "A historical date alone is not temporary progress or authorization" in prompt
        assert "actual one-off progress still is not made durable by its report wrapper" in prompt


def test_classification_prompt_remains_narrow_and_does_not_request_literal_inventory():
    prompt = _build_verification_prompt({"contract_version": DREAM_SOURCE_RECHECK_CONTRACT, "candidates": []})
    assert _UPDATE_MEANING_LITERAL_CONTRACT not in prompt
    assert _REPORT_SCOPE_QUALIFIER_CONTRACT not in prompt
    assert "Return SourceClassificationDecision JSON only" in prompt
    assert "no edit, proposal or final-judgment fields" in prompt
    assert "Do not generate proposal or final verdict inside this classification" in prompt
    assert "retained text, exclusions, title offsets or retention selection" in prompt
    properties = SourceClassificationDecision.model_json_schema()["$defs"]["SourceClassificationPoint"]["properties"]
    assert not {"literal_edit_contract", "report_outputs", "replacement_items", "update_meaning_judgment"} & properties.keys()


def test_existing_final_semantic_verdict_and_report_authority_instructions_remain():
    prompt = _build_verification_prompt({"contract_version": "final-knowledge-scope-v1", "candidates": []})
    assert "proposed_update_meaning_judgment is untrusted input, not a verdict" in prompt
    assert "missing, unclear, or dropping verdict defers the entire replacement" in prompt
    assert "not external current truth or approval" in prompt or "does not prove" in prompt
    maintenance = _build_assimilation_prompt({"maintenance_candidates": [{}]})
    assert "Partial original report support cannot authorize" in maintenance
    assert "independently judged by the existing final verifier" in maintenance
