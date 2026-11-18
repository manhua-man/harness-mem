"""Trusted report revisions use shared normalization and canonical ownership."""
import copy

import pytest

from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.commands.knowledge_assimilation import commit_shared_knowledge_change
from harness_mem.commands.separated_assimilation import (
    final_scope_payload, final_scope_verification_rows, judged_update_payload,
    validate_separated_assimilation_decision,
)
from harness_mem.core.schemas.source_report import bind_report_split
from test_dream_stage4_contract import backend as backend, _output, _run
from test_report_preservation_paths import manual_case
from test_report_original_inventory import native_vote, expand
from test_shared_maintenance_proposals import _prepared, _report_fixture, _original_report_classification

MODE = "source_backed_same_topic_revision"


def revision(parent, prepared):
    text = "Compatibility stays limited. Ran one check."
    output, written = _output(parent, parent.render_title(), text)
    prepared.manifest["report_revision_modes"] = {"candidate": MODE}
    decision = AssimilationDecision.model_validate({"points": [{
        "candidate_id": "candidate", "disposition": "refine", "matched_truth_handles": ["T1"],
        "report_outputs": [output.model_dump(mode="json")], "reason": "Revise this same source account.",
        "report_original_classification": _original_report_classification(parent, []).model_dump(mode="json")} ]})
    return decision, output, written


def test_shared_normalizer_defaults_to_literal_and_trusted_mode_is_bound():
    parent, _retained, _proposal, _omission = _report_fixture()
    prepared = _prepared(parent, support="partial")
    decision, output, written = revision(parent, prepared)
    with pytest.raises(ValueError):
        bind_report_split(parent, original_support="supported", outputs=[output])
    assert bind_report_split(parent, original_support="partial", outputs=[output], mode=MODE) == [written]
    plan = validate_separated_assimilation_decision(prepared, decision)
    payload = final_scope_payload(prepared, plan["points"][0])
    assert plan["points"][0]["report_split"]["mode"] == MODE
    assert payload["report_preservation_inventory"]["mode"] == "full_revision"
    assert prepared.manifest["verified_candidates"][0]["semantic_support"] == "partial"
    assert written.source_revision == parent.source_revision
    assert written.exchange_indexes == parent.exchange_indexes


def test_trusted_capability_keeps_complete_strict_literal_subcase():
    from test_shared_maintenance_proposals import _decision

    parent, _retained, output, omission = _report_fixture()
    prepared = _prepared(parent)
    prepared.manifest["report_revision_modes"] = {"candidate": MODE}
    decision = _decision(output, omission)
    decision.points[0].report_original_classification = _original_report_classification(parent, [omission])
    plan = validate_separated_assimilation_decision(prepared, decision)
    assert plan["points"][0]["report_split"]["mode"] == "literal_projection"
    payload = final_scope_payload(prepared, plan["points"][0])
    assert payload["report_preservation_inventory"]["mode"] == "literal_projection"


@pytest.mark.parametrize("fault", ["foreign_account", "changed_revision", "group", "topic", "unsupported", "omission", "knowledge_bypass"])
def test_trusted_revision_rejects_authority_or_output_bypasses(fault):
    parent, _retained, _proposal, omission = _report_fixture()
    prepared = _prepared(parent)
    decision, _output_proposal, _written = revision(parent, prepared)
    point = decision.points[0]
    if fault in {"foreign_account", "changed_revision"}:
        key = "session_id" if fault == "foreign_account" else "source_revision"
        prepared.manifest["current_truth"][0]["source_report"][key] = "other"
    elif fault == "group":
        target = copy.deepcopy(prepared.manifest["current_truth"][0])
        target.update(handle="T2", id="other")
        prepared.manifest["current_truth"].append(target)
        prepared.truth_by_handle["T2"] = "other"
        point.matched_truth_handles.append("T2")
    elif fault == "topic":
        point.report_outputs[0].topic_judgment.predecessor_title = "Unrelated account"
    elif fault == "unsupported":
        point.report_outputs[0].source_support = "partial"
    elif fault == "omission":
        point.report_omissions = [omission]
    else:
        point.report_outputs = []
        point.canonical_title = parent.render_title()
        point.canonical_statement = parent.render_statement() + " Extra proposed correction."
        point.topic_path = ["compatibility"]
    with pytest.raises(ValueError):
        validate_separated_assimilation_decision(prepared, decision)


@pytest.mark.parametrize("lost_old_meaning", [False, True])
def test_shared_revision_independent_final_then_canonical_readback(backend, lost_old_meaning, monkeypatch):
    import test_report_preservation_paths as fixture_owner

    capture = fixture_owner._capture_report
    source_prefix = "The source-only diagnosis succeeded. "

    def capture_truncated_report(value, text):
        complete, ref = capture(value, source_prefix + text)
        return complete.model_copy(update={"text": text}), ref

    # The immutable native source contains the omitted diagnosis; only the
    # legacy stored body is truncated. The source reference/digest is intact.
    monkeypatch.setattr(fixture_owner, "_capture_report", capture_truncated_report)
    root, candidate, old, _literal, prepared, _old_plan, _old_payload, _old_manifest, source = manual_case(backend)
    prepared.manifest["report_revision_modes"] = {candidate.id: MODE}
    output, written = _output(old.source_report, "Local cache evidence boundary",
        source_prefix + "Cache stays local. Count=7. Natural startup remains unverified.")
    decision = AssimilationDecision.model_validate({"points": [{
        "candidate_id": candidate.id, "disposition": "refine", "matched_truth_handles": list(prepared.truth_by_handle),
        "report_outputs": [output.model_dump(mode="json")], "reason": "Revise the complete scoped report.",
        "report_original_classification": _original_report_classification(old.source_report, []).model_dump(mode="json")} ]})
    plan = validate_separated_assimilation_decision(prepared, decision)
    point = plan["points"][0]
    payload = final_scope_payload(prepared, point)
    rows = final_scope_verification_rows(payload, [{"kind": "source_report", "role": "assistant",
        "content": source_prefix + old.source_report.text}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    native = native_vote(manifest)
    if lost_old_meaning:
        native["points"][0]["update_meaning_judgment"]["report_preservation"]["units"][0]["verdict"] = "lost"
    final = expand(manifest, native)
    stamped, blocked = judged_update_payload(payload, final, rows)
    store = backend.structured_store.knowledge_store
    if lost_old_meaning:
        assert blocked is not None
        assert _run(store.get_entry(old.id, project_name="demo")) == old
        return
    assert blocked is None
    for key in ("report_preservation_inventory", "update_meaning_judgment", "retained_conditions", "undecided_state"):
        if key in stamped:
            point[key] = stamped[key]
    point["final_scope_judgment"] = final.model_dump(mode="json")
    result = _run(commit_shared_knowledge_change(backend, candidate=candidate, point=point,
        project_root=root, source_refs=[source], expected_predecessor_entries=[old]))
    assert _run(store.get_entry(old.id, project_name="demo")) is None
    current = _run(store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].source_report == written
    assert current[0].id in result["truth_ids"]
    assert written.text in backend.structured_store._canonical.get_payload_json("knowledge_entries", current[0].id)
    assert len(_run(store.list_sources(current[0].id))) == 1
