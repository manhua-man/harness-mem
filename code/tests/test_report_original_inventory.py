"""Original report meaning is audited separately from successor support."""
import copy
import hashlib

import pytest

from test_report_literal_projection import case
from test_shared_maintenance_proposals import _prepared, _decision
from test_native_final_scope_transport import native_payload, segment
from harness_mem.autonomous.models import NativeFinalScopeDecision, AssimilationDecision, UpdateMeaningJudgment, SourceClassificationPoint
from harness_mem.commands.separated_assimilation import (
    validate_separated_assimilation_decision, final_scope_payload, final_scope_verification_rows,
    judged_update_payload, prove_supplied_final_scope, final_scope_proof,
)
from harness_mem.core.schemas.source_report import report_preservation_digest
from harness_mem.core.schemas.source_report import SourceReport, bind_report_preservation_inventory, validate_report_preservation_inventory
from harness_mem.commands.separated_assimilation import target_version


def fixture(*, diagnostic=False):
    first = "The source-only diagnosis succeeded. "
    receipt = "Count=7. "
    last = "Natural startup remains unverified."
    parent, written, output, omissions = case(original=first + receipt + last,
        retained=(receipt + last if diagnostic else first + last), omissions=(first if diagnostic else receipt,))
    classification = {"candidate_index": 0, "semantic_support": "supported", "future_scope": "unclear",
        "source_use": "reusable_knowledge", "reason": "Complete original evidence and qualifiers are partitioned.",
        "scope_segments": [segment(first, temporary=diagnostic), segment(receipt, temporary=True), segment(last)],
        "claim_units": [{"first_segment": 0, "end_segment_exclusive": 3, "standalone": True,
            "source_support": "supported", "source_use": "reusable_knowledge", "future_scope": "durable"}]}
    prepared = _prepared(parent)
    decision = _decision(output, omissions[0])
    # The existing manual typed proposal can supply complete original source
    # classification. It remains input to a separate final judgment.
    decision.points[0].report_original_classification = SourceClassificationPoint.model_validate(classification)
    decision = AssimilationDecision.model_validate(decision.model_dump(mode="json"))
    plan = validate_separated_assimilation_decision(prepared, decision)
    payload = final_scope_payload(prepared, plan["points"][0])
    rows = final_scope_verification_rows(payload, [{"kind": "session", "role": "assistant",
        "content": "Complete original immutable report: " + parent.text}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    return prepared, plan, payload, manifest, classification


def native_vote(manifest):
    response = native_payload(manifest)
    for point in response["points"]:
        row = manifest["candidates"][point["candidate_index"]]
        inventory = row["update_context"]["report_preservation_inventory"]
        statement = row["update_context"]["successors"][0]["source_report"]["text"]
        votes = []
        for index, unit in enumerate(inventory["units"]):
            disposable = (unit.get("future_scope") == "session_only" and
                any(omission["start"] <= unit["start"] and unit["end"] <= omission["end"]
                    for omission in inventory["omissions"]))
            votes.append({"unit_index": index, "verdict": "disposable" if disposable else "preserved",
                "successor_spans": [] if disposable else [{"successor_index": 0,
                    "char_start": 0, "char_end": len(statement)}]})
        point["update_meaning_judgment"]["report_preservation"] = {"inventory_complete": True,
            "units": votes, "omissions": [{"omission_index": index,
                **{key: "not_applicable" for key in ("claim", "evidence", "causality", "boundary", "permission", "scope")}}
                for index in range(len(inventory["omissions"]))]}
    return response


def expand(manifest, response):
    return NativeFinalScopeDecision.model_validate(response).as_verification(manifest)


def test_actual_bad_shape_without_original_inventory_vote_is_rejected():
    _prepared, _plan, payload, manifest, _classification = fixture(diagnostic=True)
    old_native_shape = native_payload(manifest)
    # This is the old structurally positive shape, not recovered native prose.
    decision = expand(manifest, old_native_shape)
    _stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
    assert blocked == "final_report_original_inventory_unproved"
    with pytest.raises(ValueError):
        prove_supplied_final_scope(payload=payload, judgment=decision)


def test_disposable_statistics_pass_only_with_independent_complete_original_vote():
    _prepared, _plan, payload, manifest, classification = fixture()
    original = payload["report_preservation_inventory"]
    assert original["claim_units"] == classification["claim_units"]
    assert original["units"][0]["first_segment"] == 0 and original["units"][0]["end_segment_exclusive"] == 3
    assert original["omissions"][0]["affected_units"] == [0, 2]
    decision = expand(manifest, native_vote(manifest))
    stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
    assert blocked is None
    assert prove_supplied_final_scope(payload=payload, judgment=decision) == final_scope_proof(stamped)
    assert stamped["update_meaning_judgment"]["report_preservation"]["inventory_sha256"] == report_preservation_digest(original)
    # The new proof and metadata change the existing canonical proof binding.
    changed = copy.deepcopy(stamped)
    changed["report_preservation_inventory"]["units"][0]["future_scope"] = "session_only"
    assert final_scope_proof(changed) != final_scope_proof(stamped)


@pytest.mark.parametrize("fault", ["missing", "incomplete", "missing_unit", "swapped_unit", "negative_unit",
    "missing_omission", "negative_evidence", "unclear_boundary", "durable_disposable", "span_owner"])
def test_missing_negative_incomplete_or_borrowed_final_votes_cannot_pass(fault):
    _prepared, _plan, payload, manifest, _classification = fixture()
    response = native_vote(manifest)
    vote = response["points"][0]["update_meaning_judgment"]["report_preservation"]
    if fault == "missing":
        response["points"][0]["update_meaning_judgment"].pop("report_preservation")
    elif fault == "incomplete":
        vote["inventory_complete"] = False
    elif fault == "missing_unit":
        vote["units"].pop()
    elif fault == "swapped_unit":
        vote["units"][0], vote["units"][1] = vote["units"][1], vote["units"][0]
    elif fault == "negative_unit":
        vote["units"][0]["verdict"] = "lost"
    elif fault == "missing_omission":
        vote["omissions"] = []
    elif fault == "negative_evidence":
        vote["omissions"][0]["evidence"] = "lost"
    elif fault == "unclear_boundary":
        vote["omissions"][0]["boundary"] = "unclear"
    elif fault == "durable_disposable":
        vote["units"][0].update(verdict="disposable", successor_spans=[])
    else:
        vote["units"][0]["successor_spans"][0]["successor_index"] = 1
    try:
        decision = expand(manifest, response)
    except ValueError:
        assert fault in {"missing_unit", "swapped_unit", "missing_omission", "span_owner"}
    else:
        assert judged_update_payload(payload, decision, manifest["candidates"])[1] is not None


@pytest.mark.parametrize("fault", ["owner", "old_version", "old_body", "unit", "omission", "output", "clear_claims", "clear_omissions"])
def test_complete_vote_is_bound_to_the_frozen_original_and_actual_final_body(fault):
    _prepared, _plan, payload, manifest, _classification = fixture()
    decision = expand(manifest, native_vote(manifest))
    changed = copy.deepcopy(payload)
    if fault == "owner":
        changed["candidate_id"] = "another-owner"
    elif fault == "old_version":
        changed["targets"][0]["version"] = "stale"
    elif fault == "old_body":
        changed["targets"][0]["source_report"]["text"] += " Changed original."
    elif fault == "unit":
        changed["report_preservation_inventory"]["units"][0]["sha256"] = "c" * 64
    elif fault == "omission":
        changed["report_preservation_inventory"]["omissions"][0]["start"] += 1
    elif fault == "clear_claims":
        changed["report_preservation_inventory"]["claim_units"] = []
    elif fault == "clear_omissions":
        changed["report_preservation_inventory"]["omissions"] = []
    else:
        changed["knowledge_items"][0]["statement"] += " Changed final."
    assert judged_update_payload(changed, decision, manifest["candidates"])[1] is not None


def test_optional_new_fields_do_not_rewrite_older_meaning_bytes():
    _prepared, _plan, payload, manifest, _classification = fixture()
    old = expand(manifest, native_payload(manifest)).points[0].update_meaning_judgment.model_dump(mode="json")
    assert "report_preservation" not in old
    assert UpdateMeaningJudgment.model_validate(old).model_dump(mode="json") == old
    assert hashlib.sha256(str(old).encode()).hexdigest() == hashlib.sha256(str(UpdateMeaningJudgment.model_validate(old).model_dump(mode="json")).encode()).hexdigest()


def test_every_output_agrees_on_every_original_unit_and_omission_but_basis_can_differ():
    _prepared, _plan, payload, _manifest, _classification = fixture()
    target = payload["targets"][0]
    report = SourceReport.model_validate(target["source_report"]).model_copy(update={
        "text": "Diagnosis succeeded.Count=7.Natural remains unverified."})
    target.update(source_report=report.model_dump(mode="json"), statement=report.render_statement(), title=report.render_title())
    target["version"] = target_version(target)
    items = []
    for index, body in enumerate(("Diagnosis succeeded.", "Natural remains unverified.")):
        written = report.model_copy(update={"topic_title": "Report topic " + str(index), "text": body})
        items.append({**payload["knowledge_items"][0], "title": written.render_title(),
            "statement": written.render_statement(), "source_report": written.model_dump(mode="json")})
    payload["knowledge_items"] = items
    original = {"scope_segments": [segment("Diagnosis succeeded."), segment("Count=7.", temporary=True),
        segment("Natural remains unverified.")], "claim_units": [{"first_segment": 0,
        "end_segment_exclusive": 3, "standalone": True, "source_support": "supported",
        "source_use": "reusable_knowledge", "future_scope": "durable"}]}
    payload["report_preservation_inventory"] = bind_report_preservation_inventory(owner=payload["candidate_id"],
        target=target, items=items, omissions=[{"text": "Count=7."}], classification=original)
    rows = final_scope_verification_rows(payload, [{"kind": "session", "content": report.text}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    response = native_vote(manifest)
    response["points"][1]["update_meaning_judgment"]["basis"] = "An independently worded explanation of the same full original preservation judgment."
    assert judged_update_payload(payload, expand(manifest, response), rows)[1] is None
    response["points"][1]["update_meaning_judgment"]["report_preservation"]["omissions"][0]["scope"] = "preserved"
    # Both individual votes are positive, but their semantic omission roles differ.
    assert judged_update_payload(payload, expand(manifest, response), rows)[1] == "final_update_meaning_incomplete"


def full_revision_fixture():
    _prepared, _plan, payload, _manifest, _classification = fixture()
    target = payload["targets"][0]
    before = SourceReport.model_validate(target["source_report"]).model_copy(update={
        "text": "Cache must stay local in offline mode."})
    after = before.model_copy(update={"text": "Cache must remain local when offline."})
    target.update(source_report=before.model_dump(mode="json"), title=before.render_title(), statement=before.render_statement())
    target["version"] = target_version(target)
    item = {**payload["knowledge_items"][0], "source_report": after.model_dump(mode="json"),
        "title": after.render_title(), "statement": after.render_statement()}
    payload["knowledge_items"] = [item]
    classification = {"scope_segments": [segment(before.text)], "claim_units": [{"first_segment": 0,
        "end_segment_exclusive": 1, "standalone": True, "source_support": "supported",
        "source_use": "reusable_knowledge", "future_scope": "durable"}]}
    payload["report_preservation_inventory"] = bind_report_preservation_inventory(owner=payload["candidate_id"],
        target=target, items=[item], omissions=[], classification=classification, mode="full_revision")
    rows = final_scope_verification_rows(payload, [{"kind": "session", "role": "assistant", "content": before.text}])
    return payload, {"contract_version": "final-knowledge-scope-v1", "candidates": rows}, classification


def test_full_revision_keeps_all_original_units_and_audits_deterministic_old_changes():
    payload, manifest, _classification = full_revision_fixture()
    inventory = payload["report_preservation_inventory"]
    assert inventory["mode"] == "full_revision" and inventory["omissions"]
    assert all(row["operation"] in {"replace", "delete"} and row["affected_units"] == [0, 1]
        for row in inventory["omissions"])
    assert any(row["successor_ranges"] for row in inventory["omissions"])
    validate_report_preservation_inventory(inventory, owner=payload["candidate_id"], targets=payload["targets"],
        items=payload["knowledge_items"], expected_mode="full_revision")
    judgment = expand(manifest, native_vote(manifest))
    assert judged_update_payload(payload, judgment, manifest["candidates"])[1] is None
    assert prove_supplied_final_scope(payload=payload, judgment=judgment)


@pytest.mark.parametrize("fault", ["mode", "clear_old_changes", "changed_old_range", "changed_new_range", "missing_vote", "evidence_lost"])
def test_full_revision_cannot_erase_or_exchange_original_change_audit(fault):
    payload, manifest, _classification = full_revision_fixture()
    response = native_vote(manifest)
    payload = copy.deepcopy(payload)
    if fault == "missing_vote":
        response["points"][0]["update_meaning_judgment"].pop("report_preservation")
    elif fault == "evidence_lost":
        response["points"][0]["update_meaning_judgment"]["report_preservation"]["omissions"][0]["evidence"] = "lost"
    elif fault == "mode":
        with pytest.raises(ValueError, match="mode_changed"):
            validate_report_preservation_inventory(payload["report_preservation_inventory"], owner=payload["candidate_id"],
                targets=payload["targets"], items=payload["knowledge_items"], expected_mode="literal_projection")
        return
    elif fault == "clear_old_changes":
        payload["report_preservation_inventory"]["omissions"] = []
    elif fault == "changed_old_range":
        payload["report_preservation_inventory"]["omissions"][0]["start"] += 1
    else:
        changed = next(row for row in payload["report_preservation_inventory"]["omissions"] if row["successor_ranges"])
        changed["successor_ranges"][0]["char_end"] += 1
    judgment = expand(manifest, response)
    assert judged_update_payload(payload, judgment, manifest["candidates"])[1] is not None


def test_literal_projection_stays_strict_and_cannot_default_to_full_revision():
    payload, _manifest, classification = full_revision_fixture()
    with pytest.raises(ValueError):
        bind_report_preservation_inventory(owner=payload["candidate_id"], target=payload["targets"][0],
            items=payload["knowledge_items"], omissions=[], classification=classification)
