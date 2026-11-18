"""Isolated contract fixtures for shared maintenance proposals; no native calls."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.models import AssimilationDecision, DREAM_SOURCE_RECHECK_CONTRACT
from harness_mem.autonomous.provider import _build_assimilation_prompt, _build_verification_prompt
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    final_scope_payload,
    final_scope_verification_rows,
    target_version,
    validate_separated_assimilation_decision,
    _bound_maintenance_classification,
)
from harness_mem.core.schemas.source_report import (
    SourceReport, ReportOutputProposal, ReportOmission, bind_report_split, report_output_scope_text,
)


def _report_fixture():
    parent = SourceReport(speaker="assistant", period="2026-10-20T00:00:00Z", session_id="session",
                          source_id="source", source_revision="revision", exchange_indexes=[1],
                          topic_title="Scoped compatibility", text="Compatibility remains limited. Ran one check.")
    retained = parent.model_copy(update={"text": "Compatibility remains limited."})
    proposal = ReportOutputProposal(
        topic_title=retained.render_title(), text=retained.text, exchange_indexes=[1],
        source_support="supported", source_use="reusable_knowledge", future_scope="durable",
        qualifiers=[], topic_judgment={"relationship": "same_topic", "predecessor_title": parent.render_title(),
                                    "successor_title": retained.render_title(), "basis": "Same compatibility account."},
        scope_segments=[{"text": report_output_scope_text(retained), "source_use": "reusable_knowledge",
                         "future_scope": "durable", "standalone": True, "content_role": "claim",
                         "source_support": "supported"}],
    )
    omission = ReportOmission(text=" Ran one check.", classification="temporary_context")
    return parent, retained, proposal, omission


def _prepared(parent, *, support="supported"):
    target = {"id": "entry", "title": parent.render_title(), "statement": parent.render_statement(),
              "topic_path": ["compatibility"], "source_report": parent.model_dump(mode="json")}
    target["version"] = target_version(target)
    return SeparatedPreparedAssimilation(
        project_name="demo", project_root="/demo", candidate_ids=("candidate",),
        eligible_candidate_ids=("candidate",), automatic_points=(),
        answer_status_by_candidate={"candidate": "ANSWERED"}, truth_by_handle={"T1": "entry"},
        manifest={"verified_candidates": [{"candidate_id": "candidate", "kind": "memory",
                   "statement": parent.render_statement(), "semantic_support": support,
                   "source_report": parent.model_dump(mode="json")}],
                  "current_truth": [{"handle": "T1", **target}]},
    )


def _decision(proposal, omission):
    return AssimilationDecision.model_validate({"points": [{"candidate_id": "candidate", "disposition": "refine",
        "matched_truth_handles": ["T1"], "report_outputs": [proposal.model_dump(mode="json")],
        "report_omissions": [omission.model_dump(mode="json")], "reason": "Retain the scoped compatibility account."}]})


def _original_report_classification(parent, omissions):
    """Inventory the complete fixture original, including crossing claim units."""
    from harness_mem.autonomous.models import SourceClassificationPoint

    ranges = sorted((parent.text.index(item.text), parent.text.index(item.text) + len(item.text))
                    for item in omissions)
    parts, cursor = [], 0
    for start, end in ranges:
        if cursor < start:
            parts.append((parent.text[cursor:start], False))
        parts.append((parent.text[start:end], True))
        cursor = end
    if cursor < len(parent.text):
        parts.append((parent.text[cursor:], False))
    return SourceClassificationPoint.model_validate({
        "candidate_index": 0, "semantic_support": "supported", "future_scope": "unclear",
        "source_use": "reusable_knowledge", "reason": "Complete fixture source claims and temporary receipts are partitioned.",
        "scope_segments": [{"text": text, "source_use": "task_context" if temporary else "reusable_knowledge",
            "future_scope": "session_only" if temporary else "durable", "standalone": not temporary,
            "content_role": "temporary_context" if temporary else "claim", "source_support": "supported"}
            for text, temporary in parts],
        "claim_units": [{"first_segment": 0, "end_segment_exclusive": len(parts), "standalone": True,
            "source_support": "supported", "source_use": "reusable_knowledge", "future_scope": "durable"}],
    })


def _classified_report_decision(parent, proposal, omission):
    decision = _decision(proposal, omission)
    decision.points[0].report_original_classification = _original_report_classification(parent, [omission])
    return decision


def test_one_report_output_retains_bound_authority_and_covers_original():
    parent, retained, proposal, omission = _report_fixture()
    assert bind_report_split(parent, original_support="supported", outputs=[proposal], omissions=[omission]) == [retained]


@pytest.mark.parametrize("support", ["partial", "contradicted", "unclear"])
def test_one_report_output_never_upgrades_partial_original(support):
    parent, _retained, proposal, omission = _report_fixture()
    with pytest.raises(ValueError, match="partial source support"):
        bind_report_split(parent, original_support=support, outputs=[proposal], omissions=[omission])


def test_single_report_output_still_requires_complete_original_coverage():
    parent, _retained, proposal, _omission = _report_fixture()
    with pytest.raises(ValueError, match="discarded original"):
        bind_report_split(parent, original_support="supported", outputs=[proposal])


def test_report_proposal_normalizes_through_existing_assimilation_and_final_payload():
    parent, retained, proposal, omission = _report_fixture()
    prepared = _prepared(parent)
    plan = validate_separated_assimilation_decision(prepared, _classified_report_decision(parent, proposal, omission))
    point = plan["points"][0]
    assert point["disposition"] == "refine"
    assert point["report_split"]["original_support"] == "supported"
    assert len(point["knowledge_items"]) == 1
    assert point["knowledge_items"][0]["statement"] == retained.render_statement()
    payload = final_scope_payload(prepared, point)
    assert payload["knowledge_items"][0]["source_report"] == retained.model_dump(mode="json")
    rows = final_scope_verification_rows(payload, [{"content": "Complete immutable source", "kind": "session"}])
    assert rows[0]["scope_text"] == report_output_scope_text(retained)
    assert rows[0]["update_context"]["predecessors"][0]["statement"] == parent.render_statement()
    assert rows[0]["update_context"]["predecessors"][0]["version"] == payload["targets"][0]["version"]
    assert rows[0]["update_context"]["successors"][0]["statement"] == retained.render_statement()
    assert rows[0]["update_context"]["proposed_update_meaning_judgment"] is None


def test_normal_validator_does_not_ignore_report_output_fields():
    parent, _retained, proposal, omission = _report_fixture()
    with pytest.raises(ValueError, match="partial source support"):
        validate_separated_assimilation_decision(_prepared(parent, support="partial"), _decision(proposal, omission))


def test_report_omissions_without_outputs_are_invalid():
    _parent, _retained, proposal, omission = _report_fixture()
    wire = _decision(proposal, omission).model_dump(mode="json")
    wire["points"][0]["report_outputs"] = []
    with pytest.raises(ValidationError, match="omissions require"):
        AssimilationDecision.model_validate(wire)


def test_final_rows_preserve_ordinary_scope_and_do_not_mutate_payload():
    payload = {"candidate_id": "candidate", "disposition": "replace",
               "knowledge_items": [{"title": "Rule", "statement": "Keep qualifiers.", "topic_path": ["rules"]}],
               "targets": [{"id": "entry", "title": "Old", "statement": "Old qualified rule.", "version": "v1"}]}
    before = deepcopy(payload)
    rows = final_scope_verification_rows(payload, [{"kind": "user_statement", "content": "Full user source"}])
    assert rows[0]["scope_text"] == "Rule\nKeep qualifiers."
    assert rows[0]["sources"][0]["content"] == "Full user source"
    assert payload == before


def test_source_classification_transport_has_no_edit_or_final_fields():
    assert DREAM_SOURCE_RECHECK_CONTRACT == "dream-source-recheck-v16"
    prompt = _build_verification_prompt({"contract_version": DREAM_SOURCE_RECHECK_CONTRACT, "candidates": []})
    assert "SourceClassificationDecision" in prompt
    assert "no edit, proposal or final-judgment fields" in prompt
    assert "may contain a temporary-context segment" in prompt
    assert "The existing assimilation owner proposes outputs" in prompt


def test_shared_assimilation_maintenance_prompt_keeps_partial_original_untrusted():
    prompt = _build_assimilation_prompt({"maintenance_candidates": [{"semantic_support": "partial"}]})
    assert "no_write, handoff, defer and reject require matched_truth_handles=[]" in prompt
    assert "Do not copy a compared truth handle into a non-writing point" in prompt
    assert "partial or mixed original is not a verified durable claim" in prompt
    assert "Partial original report support cannot authorize" in prompt
    assert "independently judged by the existing final verifier" in prompt


def _ordinary_maintenance():
    snapshot = {"id": "entry", "title": "ProjectX continuing rule",
                "statement": "ProjectX keeps its scope. TemporaryCLI ran once.",
                "topic_path": ["rules"], "source_report": None}
    snapshot["version"] = target_version(snapshot)
    prepared = SeparatedPreparedAssimilation(
        project_name="demo", project_root="/demo", candidate_ids=("candidate",),
        eligible_candidate_ids=("candidate",), automatic_points=(),
        answer_status_by_candidate={"candidate": "ANSWERED"}, truth_by_handle={"T1": "entry"},
        manifest={"final_scope_required": True,
            "verified_candidates": [{"candidate_id": "candidate", "kind": "memory", "statement": snapshot["statement"]}],
            "current_truth": [{"handle": "T1", **snapshot}],
            "maintenance_candidates": [{"candidate_id": "candidate", "target_snapshot": snapshot,
                "scope_verification": {"candidate_index": 0, "semantic_support": "partial", "future_scope": "unclear",
                    "source_use": "unclear", "reason": "Mixed original needs a final proposal.",
                    "scope_segments": [{"text": snapshot["title"] + "\n" + snapshot["statement"],
                        "content_role": "claim", "source_support": "supported", "source_use": "reusable_knowledge",
                        "future_scope": "durable", "standalone": True}]}}]},
    )
    return prepared


def test_exact_bound_existing_maintenance_can_propose_without_all_original_identifiers():
    prepared = _ordinary_maintenance()
    assert _bound_maintenance_classification(prepared, "candidate", ["entry"])
    decision = AssimilationDecision.model_validate({"points": [{"candidate_id": "candidate", "disposition": "refine",
        "matched_truth_handles": ["T1"], "knowledge_items": [{"title": "ProjectX rule", "statement": "ProjectX keeps its scope.",
            "topic_path": ["rules"], "claim_kind": "design_requirement"}], "reason": "Remove only temporary processing details."}]})
    point = validate_separated_assimilation_decision(prepared, decision)["points"][0]
    assert "TemporaryCLI" not in point["knowledge_items"][0]["statement"]
    assert point.get("final_scope_judgment") is None  # Proposal success is no final write authority.


@pytest.mark.parametrize("mutation", ["no_final_gate", "changed_version", "missing_partition", "wrong_target"])
def test_source_candidates_cannot_bypass_specificity_with_unbound_maintenance(mutation):
    prepared = _ordinary_maintenance()
    item = prepared.manifest["maintenance_candidates"][0]
    targets = ["entry"]
    if mutation == "no_final_gate":
        prepared.manifest["final_scope_required"] = False
    elif mutation == "changed_version":
        item["target_snapshot"]["version"] = "stale"
    elif mutation == "missing_partition":
        item["scope_verification"]["scope_segments"] = []
    else:
        targets = ["different-entry"]
    assert not _bound_maintenance_classification(prepared, "candidate", targets)


def test_nonwriting_report_outputs_are_not_silently_ignored():
    _parent, _retained, proposal, omission = _report_fixture()
    wire = _decision(proposal, omission).model_dump(mode="json")
    wire["points"][0]["disposition"] = "no_write"
    with pytest.raises(ValidationError, match="targeted refine or replace"):
        AssimilationDecision.model_validate(wire)


def test_report_confirmation_plan_uses_independent_final_attributed_scope(tmp_path):
    from harness_mem.autonomous.models import CandidateVerificationPoint, OutputVerification
    from harness_mem.commands.dream_assimilation import (
        DreamAssimilationCandidate, prepare_dream_assimilation, build_dream_maintenance_plan,
    )
    from harness_mem.core.schemas.knowledge import KnowledgeEntry

    parent, _retained, _proposal, _omission = _report_fixture()
    entry = KnowledgeEntry(id="report-entry", project_name="demo", title=parent.render_title(),
                           statement=parent.render_statement(), module_path=["reports"], source_report=parent)
    original = CandidateVerificationPoint(candidate_index=0, semantic_support="supported", future_scope="durable",
        source_use="reusable_knowledge", reason="The original account has durable support.",
        scope_segments=[{"text": parent.text, "source_use": "reusable_knowledge", "future_scope": "durable",
                         "source_support": "supported", "content_role": "claim", "standalone": True}])
    candidate = DreamAssimilationCandidate(candidate_id="confirm-report", entry=entry, sources=(),
        semantic_support="supported", future_scope="durable", verification_reason=original.reason,
        source_excerpts=(), scope_verification=original, verification_contract=DREAM_SOURCE_RECHECK_CONTRACT)
    prepared = prepare_dream_assimilation(project_name="demo", project_root=tmp_path, run_id="run",
                                         signal_kind="stale", candidates=[candidate])
    assert build_dream_maintenance_plan(prepared)[0]["disposition"] == "no_write"
    final = OutputVerification(semantic_support="supported", future_scope="durable", source_use="reusable_knowledge",
        reason="The exact rendered account and authority were independently checked.",
        scope_segments=[{"text": report_output_scope_text(parent), "source_use": "reusable_knowledge", "future_scope": "durable",
                         "source_support": "supported", "content_role": "claim", "standalone": True}])
    from dataclasses import replace
    candidate = replace(candidate, scope_verification=original.model_copy(update={"output_verifications": [final]}))
    prepared = replace(prepared, candidates=(candidate,))
    plan = build_dream_maintenance_plan(prepared)[0]
    assert plan["disposition"] == "confirm"
    assert plan["final_scope_judgment"]["points"][0]["scope_segments"][0]["text"] == report_output_scope_text(parent)
    final_mixed_payload = {**final.model_dump(), "scope_segments": [{
        "text": report_output_scope_text(parent), "source_use": "task_context",
        "future_scope": "session_only", "standalone": True,
        "content_role": "temporary_context", "source_support": "supported",
    }]}
    # Revalidate typed segments while preserving a point-level durable claim;
    # the complete final partition must still reject confirmation.
    final_mixed = OutputVerification.model_validate(final_mixed_payload)
    candidate = replace(candidate, scope_verification=original.model_copy(
        update={"output_verifications": [final_mixed]}))
    rejected = build_dream_maintenance_plan(replace(prepared, candidates=(candidate,)))[0]
    assert rejected["disposition"] == "no_write"
    assert rejected["reason"] == "Dream final title and body verification did not establish complete durable support."
