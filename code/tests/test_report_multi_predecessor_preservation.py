"""Consolidation must preserve every original report, not one representative."""
import copy
import hashlib

import pytest

from harness_mem.core.schemas.source_report import (
    SourceReport,
    bind_report_preservation_inventories,
    bind_report_preservation_inventory,
    report_preservation_block,
    report_preservation_digest,
    validate_report_preservation_inventory,
)


def segment(text):
    return {"text": text, "source_use": "reusable_knowledge", "future_scope": "durable",
        "standalone": True, "content_role": "claim", "source_support": "supported"}


def endpoints(*, literal=False):
    reports = [SourceReport(speaker="assistant", period="2026-10-19T08:15:13Z",
        session_id="native-session", source_id="native-source", source_revision=f"revision-{index}",
        exchange_indexes=[index + 1], text=body) for index, body in enumerate((
            "The cache works offline. Live mode remains unverified.",
            "The archive works offline. Restore remains unverified."))]
    if literal:
        reports[1] = reports[1].model_copy(update={"text": reports[0].text})
    successor = reports[0].model_copy(update={"source_revision": "complete-revision",
        "exchange_indexes": [1, 2], "text": reports[0].text if literal else
        "The cache and archive work offline. Live mode and restore remain unverified."})
    targets = [{"id": f"old-{index}", "version": f"version-{index}",
        "source_report": report.model_dump(mode="json"), "title": report.render_title(),
        "statement": report.render_statement()} for index, report in enumerate(reports)]
    items = [{"title": successor.render_title(), "statement": successor.render_statement(),
        "source_report": successor.model_dump(mode="json")}]
    inventories = []
    mode = "literal_projection" if literal else "full_revision"
    for target, report in zip(targets, reports):
        first, boundary = report.text.split(". ")
        classification = {"scope_segments": [segment(first + ". "), segment(boundary)],
            "claim_units": [{"first_segment": index, "end_segment_exclusive": index + 1,
                "standalone": True, "source_support": "supported", "source_use": "reusable_knowledge",
                "future_scope": "durable"} for index in range(2)]}
        inventories.append(bind_report_preservation_inventory(owner="candidate", target=target,
            items=items, omissions=[], classification=classification, mode=mode))
    return targets, items, inventories


def bound(*, literal=False):
    targets, items, originals = endpoints(literal=literal)
    inventory = bind_report_preservation_inventories(owner="candidate", targets=targets,
        items=items, inventories=originals,
        expected_mode="literal_projection" if literal else "full_revision")
    return targets, items, originals, inventory


def final_vote(inventory, items):
    body = items[0]["source_report"]["text"]
    return {"owner_candidate_id": "candidate", "inventory_complete": True,
        "inventory_sha256": report_preservation_digest(inventory),
        "units": [{"unit_index": index, "unit_sha256": report_preservation_digest(unit),
            "verdict": "preserved", "successor_spans": [{"successor_index": 0,
                "char_start": 0, "char_end": len(body),
                "text_sha256": hashlib.sha256(body.encode()).hexdigest()}]}
            for index, unit in enumerate(inventory["units"])],
        "omissions": [{"omission_index": index,
            "omission_sha256": report_preservation_digest(omission),
            "affected_units": omission["affected_units"],
            **{key: "preserved" for key in ("claim", "evidence", "causality", "boundary", "permission", "scope")}}
            for index, omission in enumerate(inventory["omissions"])]}


@pytest.mark.parametrize("literal", [False, True])
def test_all_originals_revalidate_and_receive_independent_final_unit_votes(literal):
    targets, items, originals, inventory = bound(literal=literal)
    assert inventory["predecessor_inventories"] == originals
    assert len(inventory["units"]) == sum(len(row["units"]) for row in originals)
    assert {row["predecessor_id"] for row in inventory["units"]} == {"old-0", "old-1"}
    offset = len(originals[0]["units"])
    assert all(row["unit_index"] >= offset for row in final_vote(inventory, items)["units"][offset:])
    for omission in inventory["omissions"]:
        original = originals[omission["predecessor_index"]]
        old = original["omissions"][omission["original_omission_index"]]
        assert omission["affected_units"] == [
            index + (offset if omission["predecessor_index"] else 0) for index in old["affected_units"]]
    validate_report_preservation_inventory(inventory, owner="candidate", targets=targets, items=items)
    assert report_preservation_block(inventory, final_vote(inventory, items), items) is None


def test_single_predecessor_keeps_the_original_v1_format_and_vote_contract():
    targets, items, originals = endpoints()
    inventory = bind_report_preservation_inventories(owner="candidate", targets=targets[:1],
        items=items, inventories=originals[:1], expected_mode="full_revision")
    assert inventory == originals[0]
    assert inventory is not originals[0]
    assert inventory["contract"] == "report-original-preservation-v1"
    validate_report_preservation_inventory(inventory, owner="candidate", targets=targets[:1], items=items)
    assert report_preservation_block(inventory, final_vote(inventory, items), items) is None


@pytest.mark.parametrize("fault", ["missing_target", "missing_inventory", "duplicate_target",
    "swapped_inventory", "nested_inventory", "no_successor", "wrong_mode"])
def test_group_cannot_drop_repeat_or_borrow_a_predecessor(fault):
    targets, items, originals, inventory = bound()
    kwargs = {"owner": "candidate", "targets": targets, "items": items, "inventories": originals}
    if fault == "missing_target":
        kwargs["targets"] = targets[:1]
    elif fault == "missing_inventory":
        kwargs["inventories"] = originals[:1]
    elif fault == "duplicate_target":
        kwargs.update(targets=[targets[0], targets[0]], inventories=[originals[0], originals[0]])
    elif fault == "swapped_inventory":
        kwargs["inventories"] = list(reversed(originals))
    elif fault == "nested_inventory":
        kwargs["inventories"] = [originals[0], inventory]
    elif fault == "no_successor":
        kwargs["items"] = []
    else:
        kwargs["expected_mode"] = "literal_projection"
    with pytest.raises(ValueError):
        bind_report_preservation_inventories(**kwargs)


@pytest.mark.parametrize("field,value", [("speaker", "user"), ("period", "other-period"),
    ("session_id", "other-session"), ("source_id", "other-source")])
def test_same_revision_or_body_cannot_mask_a_foreign_account(field, value):
    targets, items, originals = endpoints()
    targets[1]["source_report"][field] = value
    with pytest.raises(ValueError, match="account_changed"):
        bind_report_preservation_inventories(owner="candidate", targets=targets,
            items=items, inventories=originals)


@pytest.mark.parametrize("fault", ["version", "body", "exchanges", "revision", "target_id",
    "source_account", "owner", "omission", "claim", "segment", "dropped_original", "dropped_unit",
    "dropped_omission", "swapped_originals", "successor_body", "successor_account"])
def test_every_original_version_body_index_and_omission_is_bound_to_actual_endpoints(fault):
    targets, items, _originals, inventory = bound()
    owner = "candidate"
    if fault == "version":
        targets[1]["version"] = "new-version"
    elif fault == "body":
        targets[1]["source_report"]["text"] += " Extra original condition."
    elif fault == "exchanges":
        targets[1]["source_report"]["exchange_indexes"] = [3]
    elif fault == "revision":
        targets[1]["source_report"]["source_revision"] = "another-revision"
    elif fault == "target_id":
        targets[1]["id"] = "replaced-original"
    elif fault == "source_account":
        targets[1]["source_report"]["session_id"] = "another-account"
    elif fault == "owner":
        owner = "another-candidate"
    elif fault == "omission":
        inventory["predecessor_inventories"][1]["omissions"][0]["start"] += 1
    elif fault == "claim":
        inventory["predecessor_inventories"][1]["claim_units"] = []
    elif fault == "segment":
        inventory["predecessor_inventories"][1]["segments"][0]["end"] += 1
    elif fault == "dropped_original":
        inventory["predecessor_inventories"].pop()
    elif fault == "dropped_unit":
        inventory["units"].pop()
    elif fault == "dropped_omission":
        inventory["omissions"].pop()
    elif fault == "swapped_originals":
        inventory["predecessor_inventories"].reverse()
    elif fault == "successor_body":
        items[0]["source_report"]["text"] = "Only the cache works offline."
    else:
        items[0]["source_report"]["speaker"] = "user"
    with pytest.raises(ValueError):
        validate_report_preservation_inventory(inventory, owner=owner, targets=targets, items=items)


@pytest.mark.parametrize("fault", ["first_only", "missing_unit", "duplicate_unit", "borrowed_unit_hash",
    "partial_unit", "lost_unit", "disposable_durable", "missing_span", "wrong_span_body",
    "missing_omission", "duplicate_omission", "borrowed_omission_hash", "lost_evidence",
    "unclear_boundary", "wrong_affected_units", "incomplete"])
def test_partial_or_first_predecessor_only_final_support_never_passes_the_group(fault):
    _targets, items, originals, inventory = bound()
    proof = final_vote(inventory, items)
    offset = len(originals[0]["units"])
    omission_offset = len(originals[0]["omissions"])
    if fault == "first_only":
        proof = final_vote(originals[0], items)
    elif fault == "missing_unit":
        proof["units"].pop()
    elif fault == "duplicate_unit":
        proof["units"][offset] = copy.deepcopy(proof["units"][0])
    elif fault == "borrowed_unit_hash":
        proof["units"][offset]["unit_sha256"] = proof["units"][0]["unit_sha256"]
    elif fault in {"partial_unit", "lost_unit"}:
        proof["units"][offset]["verdict"] = "partial" if fault == "partial_unit" else "lost"
    elif fault == "disposable_durable":
        proof["units"][offset].update(verdict="disposable", successor_spans=[])
    elif fault == "missing_span":
        proof["units"][offset]["successor_spans"] = []
    elif fault == "wrong_span_body":
        proof["units"][offset]["successor_spans"][0]["text_sha256"] = "0" * 64
    elif fault == "missing_omission":
        proof["omissions"].pop()
    elif fault == "duplicate_omission":
        proof["omissions"][omission_offset] = copy.deepcopy(proof["omissions"][0])
    elif fault == "borrowed_omission_hash":
        proof["omissions"][omission_offset]["omission_sha256"] = proof["omissions"][0]["omission_sha256"]
    elif fault == "lost_evidence":
        proof["omissions"][omission_offset]["evidence"] = "lost"
    elif fault == "unclear_boundary":
        proof["omissions"][omission_offset]["boundary"] = "unclear"
    elif fault == "wrong_affected_units":
        proof["omissions"][omission_offset]["affected_units"] = originals[1]["omissions"][0]["affected_units"]
    else:
        proof["inventory_complete"] = False
    assert report_preservation_block(inventory, proof, items) is not None


def test_mutated_nested_or_flat_inventory_cannot_reuse_a_rehashed_positive_vote():
    _targets, items, _originals, inventory = bound()
    inventory["predecessor_inventories"][1]["units"][0]["sha256"] = "0" * 64
    assert report_preservation_block(inventory, final_vote(inventory, items), items) is not None


def test_existing_native_final_vote_transport_covers_all_flattened_originals():
    from harness_mem.autonomous.models import NativeFinalScopeDecision
    from harness_mem.commands.separated_assimilation import final_scope_verification_rows
    from test_report_original_inventory import full_revision_fixture, native_vote

    payload, _manifest, _classification = full_revision_fixture()
    targets, items, _originals, inventory = bound()
    payload.update(candidate_id="candidate", targets=targets, knowledge_items=items,
        report_preservation_inventory=inventory)
    rows = final_scope_verification_rows(payload, [{"kind": "session", "role": "assistant",
        "content": "The cache works offline. The archive works offline. Live mode and restore remain unverified."}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    native = native_vote(manifest)
    verified = NativeFinalScopeDecision.model_validate(native).as_verification(manifest)
    preservation = verified.points[0].update_meaning_judgment.report_preservation
    assert report_preservation_block(inventory, preservation.model_dump(mode="json"), items) is None
    native["points"][0]["update_meaning_judgment"]["report_preservation"]["units"].pop()
    with pytest.raises(ValueError, match="complete original inventory"):
        NativeFinalScopeDecision.model_validate(native).as_verification(manifest)
