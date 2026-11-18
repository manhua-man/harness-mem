"""Exact report projection fixtures; no models, native events or live store."""
import pytest
from pydantic import ValidationError
from test_shared_maintenance_proposals import _report_fixture, _prepared, _classified_report_decision
from harness_mem.core.schemas.source_report import (
    ReportOmission, ReportQualifier, ReportOutputProposal, bind_report_split, report_output_scope_text,
)
from harness_mem.commands.separated_assimilation import (
    validate_separated_assimilation_decision, final_scope_payload, final_scope_verification_rows,
    prove_supplied_final_scope,
)
from harness_mem.autonomous.models import CandidateVerificationDecision


def case(original="Compatibility stays local. Count=7. No natural acceptance.",
         retained="Compatibility stays local. No natural acceptance.",
         omissions=(" Count=7.",)):
    parent, _, proposal, _ = _report_fixture()
    parent = parent.model_copy(update={"text": original})
    written = parent.model_copy(update={"text": retained})
    proposal = proposal.model_copy(update={"text": retained, "scope_segments": [
        proposal.scope_segments[0].model_copy(update={"text": report_output_scope_text(written)})]})
    omitted = [ReportOmission(text=text, classification="temporary_context") for text in omissions]
    return parent, written, proposal, omitted


def bind(fixture):
    parent, _written, proposal, omissions = fixture
    return bind_report_split(parent, original_support="supported", outputs=[proposal], omissions=omissions)


def test_middle_receipt_removed_necessary_evidence_limit_retained():
    fixture = case()
    assert bind(fixture) == [fixture[1]]
    assert fixture[1].text.endswith("No natural acceptance.")
    assert fixture[1].same_account_source(fixture[0])
    assert fixture[1].period == fixture[0].period
    assert fixture[1].exchange_indexes == fixture[0].exchange_indexes


@pytest.mark.parametrize("text", [
    "Compatibility remains local. No natural acceptance.",
    "Compatibility stays local.No natural acceptance.",
    "No natural acceptance. Compatibility stays local.",
    "Compatibility stays local.",
])
def test_paraphrase_punctuation_reordering_or_unaccounted_loss_refused(text):
    with pytest.raises(ValueError):
        bind(case(retained=text))


@pytest.mark.parametrize("omissions,match", [
    ((), "requires explicit"),
    (("missing",), "not an exact"),
    ((" Count=7.", "Count=7."), "overlap"),
    ((" Count=7.", " Count=7."), "overlap"),
    ((" ",), "ambiguous"),
])
def test_absent_ambiguous_duplicate_overlapping_or_missing_omission_refused(omissions, match):
    with pytest.raises(ValueError, match=match):
        bind(case(omissions=omissions))


def test_second_occurrence_including_overlapping_is_ambiguous():
    with pytest.raises(ValueError, match="ambiguous"):
        bind(case(original="Claim. aaa. Limit.", retained="Claim. a. Limit.", omissions=("aa",)))


def test_multiple_omissions_are_deleted_in_original_order_without_strip():
    fixture = case(original="Claim. Count=7. Still local. Wait=9. No acceptance.",
                   retained="Claim. Still local. No acceptance.",
                   omissions=(" Wait=9.", " Count=7."))
    assert bind(fixture) == [fixture[1]]


@pytest.mark.parametrize("support", ["partial", "contradicted", "unclear"])
def test_partial_original_stays_blocked(support):
    parent, _, output, omissions = case()
    with pytest.raises(ValueError, match="partial source support"):
        bind_report_split(parent, original_support=support, outputs=[output], omissions=omissions)


@pytest.mark.parametrize("support,independent", [("unclear", False), ("unsupported", False), ("supported", True)])
def test_declared_unknown_or_independently_useful_qualifier_cannot_be_removed(support, independent):
    parent, written, output, omissions = case()
    output = output.model_copy(update={"qualifiers": [ReportQualifier(
        text="Count=7.", source_support=support, independently_useful=independent)]})
    with pytest.raises(ValueError, match="dropped a qualifier"):
        bind_report_split(parent, original_support="supported", outputs=[output], omissions=omissions)


def test_missing_or_stale_full_rendered_scope_stays_blocked():
    parent, _, output, omissions = case()
    output = output.model_copy(update={"scope_segments": []})
    with pytest.raises(ValueError, match="verification does not cover"):
        bind_report_split(parent, original_support="supported", outputs=[output], omissions=omissions)


def test_empty_text_not_runtime_derived():
    parent, _, output, _ = case()
    payload = output.model_dump(mode="json")
    payload["text"] = ""
    with pytest.raises(ValidationError):
        ReportOutputProposal.model_validate(payload)


def test_projected_shared_payload_preserves_exact_final_scope_and_still_requires_final_judgment():
    parent, written, output, omissions = case()
    prepared = _prepared(parent)
    plan = validate_separated_assimilation_decision(prepared, _classified_report_decision(parent, output, omissions[0]))
    payload = final_scope_payload(prepared, plan["points"][0])
    assert payload["knowledge_items"][0]["statement"] == written.render_statement()
    rows = final_scope_verification_rows(payload, [{"content": "Complete immutable fixture source", "kind": "session"}])
    assert rows[0]["scope_text"] == report_output_scope_text(written)
    assert rows[0]["update_context"]["predecessors"][0]["statement"] == parent.render_statement()
    with pytest.raises(ValueError):
        prove_supplied_final_scope(payload=payload, judgment=CandidateVerificationDecision(points=[]))


def test_candidate_prompt_requires_exact_projection_no_rewrite():
    from harness_mem.autonomous.provider import _build_assimilation_prompt
    prompt = _build_assimilation_prompt({"maintenance_candidates": [{}]})
    assert "including all punctuation and whitespace" in prompt
    assert "Do not paraphrase, insert connectors, trim, reorder" in prompt


def test_multiple_outputs_exact_remainder_and_proposal_order():
    parent, written, output, omissions = case()
    first = "Compatibility stays local."
    second = " No natural acceptance."
    # Typed outputs trim edge whitespace; retain an explicit exact space within
    # the first output instead using a split whose parts are both single lines.
    parent = parent.model_copy(update={"text": "Compatibility stays local.Count=7.No natural acceptance."})
    outputs = []
    for title, text in [("Local constraint", first), ("Evidence limit", second.strip())]:
        report = parent.model_copy(update={"topic_title": title, "text": text})
        outputs.append(output.model_copy(update={"topic_title": title, "text": text,
            "topic_judgment": output.topic_judgment.model_copy(update={"successor_title": title}),
            "scope_segments": [output.scope_segments[0].model_copy(update={"text": report_output_scope_text(report)})]}))
    omissions = [ReportOmission(text="Count=7.", classification="temporary_context")]
    # Both outputs happen to be contiguous, so retain the legacy successful path.
    assert len(bind_report_split(parent, original_support="supported", outputs=outputs, omissions=omissions)) == 2
    # Force one noncontiguous output while still preserving the complete remainder.
    parent = parent.model_copy(update={"text": "Compatibility Count=7.stays local.No natural acceptance."})
    assert len(bind_report_split(parent, original_support="supported", outputs=outputs, omissions=omissions)) == 2
    with pytest.raises(ValueError, match="exact temporary-omission projection"):
        bind_report_split(parent, original_support="supported", outputs=list(reversed(outputs)), omissions=omissions)


@pytest.mark.parametrize("relationship", ["drops_applicable_meaning", "unclear"])
def test_exact_projection_does_not_override_final_whole_meaning_rejection(relationship):
    parent, written, output, omissions = case()
    prepared = _prepared(parent)
    plan = validate_separated_assimilation_decision(prepared, _classified_report_decision(parent, output, omissions[0]))
    payload = final_scope_payload(prepared, plan["points"][0])
    target = payload["targets"][0]
    judgment = CandidateVerificationDecision.model_validate({"points": [{
        "candidate_index": 0, "semantic_support": "supported", "source_use": "reusable_knowledge",
        "future_scope": "durable", "reason": "Fixture final judgment refuses preservation.",
        "scope_segments": [{"text": report_output_scope_text(written), "source_support": "supported",
            "source_use": "reusable_knowledge", "future_scope": "durable", "content_role": "claim", "standalone": True}],
        "update_meaning_judgment": {"relationship": relationship, "predecessor_statements": [target["statement"]],
            "predecessor_versions": [target["version"]], "successor_statements": [written.render_statement()],
            "predecessor_conditions": [], "basis": "The whole change may remove useful evidence limits."}
    }]})
    with pytest.raises(ValueError, match="final knowledge scope judgment rejected"):
        prove_supplied_final_scope(payload=payload, judgment=judgment)


def test_unknown_final_scope_does_not_become_durable_after_exact_projection():
    parent, written, output, omissions = case()
    prepared = _prepared(parent)
    plan = validate_separated_assimilation_decision(prepared, _classified_report_decision(parent, output, omissions[0]))
    payload = final_scope_payload(prepared, plan["points"][0])
    judgment = CandidateVerificationDecision.model_validate({"points": [{
        "candidate_index": 0, "semantic_support": "supported", "source_use": "unclear", "future_scope": "unclear",
        "reason": "Fixture final scope has an unknown required qualifier.",
        "scope_segments": [{"text": report_output_scope_text(written), "source_support": "unclear",
            "source_use": "unclear", "future_scope": "unclear", "content_role": "qualifier", "standalone": False}]
    }]})
    with pytest.raises(ValueError, match="final knowledge scope judgment rejected"):
        prove_supplied_final_scope(payload=payload, judgment=judgment)
