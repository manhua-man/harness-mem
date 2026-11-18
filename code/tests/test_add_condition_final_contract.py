"""Condition-bearing add uses the existing final verifier, with no native I/O."""

import copy

import pytest

from harness_mem.autonomous.models import NativeFinalScopeDecision
from harness_mem.autonomous.provider import _build_verification_prompt
from harness_mem.commands.separated_assimilation import (
    final_scope_verification_rows,
    judged_update_payload,
    needs_update_meaning,
    prove_supplied_final_scope,
    update_meaning_block,
)
from test_native_final_scope_transport import fixture_manifest, native_payload


def condition_fixture(*, owners=1):
    _, payloads = fixture_manifest(disposition="add", owners=owners)
    rows = []
    for payload in payloads:
        payload.update(targets=[], retained_conditions=["only offline"],
                       undecided_state="selection remains undecided")
        for row in final_scope_verification_rows(payload, [{"content": "Complete synthetic source."}]):
            row["candidate_index"] = len(rows)
            rows.append(row)
    manifest = dict(contract_version="final-knowledge-scope-v1", candidates=rows)
    native = native_payload(manifest)
    for point, row in zip(native["points"], rows):
        context = row["update_context"]
        first, second = [item["statement"] for item in context["successors"]]
        condition_start = first.index("only offline")
        undecided_start = second.index("selection remains undecided")
        point["update_meaning_judgment"].update(
            condition_spans=[dict(successor_index=0, char_start=condition_start,
                                  char_end=condition_start + len("only offline"))],
            undecided_span=dict(successor_index=1, char_start=undecided_start,
                                char_end=undecided_start + len("selection remains undecided")),
            basis=f"Independent final output {point['candidate_index']} checks every source condition.",
        )
    return manifest, payloads, native


def expand(manifest, native):
    return NativeFinalScopeDecision.model_validate(native).as_verification(manifest)


def test_native_condition_add_binds_all_outputs_without_inventing_predecessors():
    manifest, payloads, native = condition_fixture(owners=2)
    decision = expand(manifest, native)
    for payload in payloads:
        stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
        assert blocked is None
        proof = stamped["update_meaning_judgment"]
        assert proof["predecessor_statements"] == proof["predecessor_versions"] == []
        assert stamped["retained_conditions"] == payload["retained_conditions"]
        assert stamped["undecided_state"] == payload["undecided_state"]
        assert update_meaning_block(stamped) is None
    # Single-owner supplied proof also follows the common final scope owner.
    one, payloads, native = condition_fixture()
    assert prove_supplied_final_scope(payload=payloads[0], judgment=expand(one, native))
    prompt = _build_verification_prompt(one, native_final_transport=True)
    assert "condition-bearing add" in prompt and "explicitly empty predecessors" in prompt


@pytest.mark.parametrize("change", ["missing", "incomplete", "drop", "unclear", "different_output"])
def test_add_cannot_use_missing_or_negative_or_foreign_endpoint_proof(change):
    manifest, payloads, native = condition_fixture()
    if change == "missing":
        native["points"][0]["update_meaning_judgment"] = None
    elif change == "incomplete":
        native["points"][0]["update_meaning_judgment"]["inventory_complete"] = False
    elif change in {"drop", "unclear"}:
        for point in native["points"]:
            point["update_meaning_judgment"]["relationship"] = (
                "drops_applicable_meaning" if change == "drop" else "unclear")
    decision = expand(manifest, native)
    if change == "different_output":
        for point in decision.points:
            point.update_meaning_judgment.successor_statements[0] += " Invented text."
    assert judged_update_payload(payloads[0], decision, manifest["candidates"])[1] == "final_update_meaning_incomplete"


@pytest.mark.parametrize("change", ["empty_inventory", "missing_undecided", "out_of_range", "foreign_owner"])
def test_native_condition_inventory_cannot_be_erased_or_forged(change):
    manifest, _, native = condition_fixture()
    proof = native["points"][0]["update_meaning_judgment"]
    if change == "empty_inventory":
        proof["condition_spans"] = []
    elif change == "missing_undecided":
        proof["undecided_span"] = None
    elif change == "out_of_range":
        proof["condition_spans"][0]["char_end"] = 100000
    else:
        for row in manifest["candidates"]:
            row["update_context"]["owner_candidate_id"] = "foreign-owner"
    with pytest.raises(ValueError):
        expand(manifest, native)


def test_proposal_judgment_cannot_replace_independent_null_verdict():
    manifest, payloads, native = condition_fixture()
    independent = expand(manifest, native)
    proposed = independent.points[0].update_meaning_judgment.model_dump(mode="json")
    payloads[0]["update_meaning_judgment"] = proposed
    assert update_meaning_block(payloads[0]) is None  # Structural validity alone.
    for point in native["points"]:
        point["update_meaning_judgment"] = None
    assert judged_update_payload(payloads[0], expand(manifest, native), manifest["candidates"])[1]


def test_canonical_empty_inventory_and_cross_owner_rows_cannot_erase_obligations():
    manifest, payloads, native = condition_fixture(owners=2)
    decision = expand(manifest, native)
    bad = decision.model_copy(deep=True)
    for point in bad.points:
        point.update_meaning_judgment.predecessor_conditions = []
    assert judged_update_payload(payloads[0], bad, manifest["candidates"])[1]
    rows = copy.deepcopy(manifest["candidates"])
    for row in rows[:2]:
        row["owner_candidate_id"] = "foreign-owner"
    assert judged_update_payload(payloads[0], decision, rows)[1]


def test_partial_final_output_defers_the_complete_add():
    manifest, payloads, native = condition_fixture()
    native["points"][1]["semantic_support"] = "partial"
    with pytest.raises(ValueError, match="rejected"):
        prove_supplied_final_scope(payload=payloads[0], judgment=expand(manifest, native))


@pytest.mark.parametrize("disposition", ["refine", "replace"])
def test_old_replacement_cannot_clear_predecessors_or_relabel_context_as_add(disposition):
    manifest, _ = fixture_manifest(disposition=disposition)
    native = native_payload(manifest)
    for row in manifest["candidates"]:
        row["update_context"]["predecessors"] = []
    with pytest.raises(ValueError, match="inventories"):
        expand(manifest, native)
    for row in manifest["candidates"]:
        row["update_context"]["disposition"] = "add"
    with pytest.raises(ValueError, match="obligations"):
        expand(manifest, native)


def test_ordinary_add_retains_null_context_and_proof():
    manifest, payloads = fixture_manifest(disposition="add")
    payloads[0]["targets"] = []
    assert not needs_update_meaning(payloads[0])
    assert all(row.get("update_context") is None for row in manifest["candidates"])
    decision = expand(manifest, native_payload(manifest))
    assert all(point.update_meaning_judgment is None for point in decision.points)
    assert judged_update_payload(payloads[0], decision, manifest["candidates"])[1] is None


def test_raw_only_add_still_requires_independent_whole_meaning():
    manifest, payloads, native = condition_fixture()
    payload = payloads[0]
    payload.pop("retained_conditions")
    payload.pop("undecided_state")
    payload["update_meaning_judgment"] = {}
    assert needs_update_meaning(payload)
    rows = final_scope_verification_rows(payload, [{"content": "Complete source."}])
    assert rows[0]["update_context"]["predecessors"] == []
    assert judged_update_payload(payload, None, rows)[1]
    decision = expand(manifest, native)
    assert judged_update_payload(payload, decision, rows)[1] is None


@pytest.mark.parametrize("only", ["conditions", "undecided"])
def test_each_declared_obligation_independently_requires_the_same_final_gate(only):
    _, payloads, _ = condition_fixture()
    payload = payloads[0]
    payload.pop("undecided_state" if only == "conditions" else "retained_conditions")
    rows = final_scope_verification_rows(payload, [{"content": "Complete source."}])
    assert needs_update_meaning(payload)
    assert rows[0]["update_context"]["predecessors"] == []
    assert judged_update_payload(payload, None, rows)[1]


def test_explicit_raw_only_empty_inventory_requires_an_independent_positive_vote():
    _, payloads, _ = condition_fixture()
    payload = payloads[0]
    payload.pop("retained_conditions")
    payload.pop("undecided_state")
    payload["update_meaning_judgment"] = {}
    rows = final_scope_verification_rows(payload, [{"content": "Complete source."}])
    manifest = dict(contract_version="final-knowledge-scope-v1", candidates=rows)
    native = native_payload(manifest)
    for point in native["points"]:
        point["update_meaning_judgment"]["condition_spans"] = []
    decision = expand(manifest, native)
    stamped, blocked = judged_update_payload(payload, decision, rows)
    assert blocked is None
    assert stamped["update_meaning_judgment"]["predecessor_conditions"] == []
    assert update_meaning_block(stamped) is None
    for point in native["points"]:
        point["update_meaning_judgment"]["inventory_complete"] = False
    assert judged_update_payload(payload, expand(manifest, native), rows)[1]


def test_final_prompt_separates_add_bindings_from_independent_meaning_audit():
    manifest, _, _ = condition_fixture()
    prompt = _build_verification_prompt(manifest, native_final_transport=True)
    assert "declared retained_conditions one-to-one in the same order" in prompt
    assert "Do not append the whole claim" in prompt
    assert "the declaration is not proof of completeness" in prompt
    assert "additional necessary condition is absent from the declared obligations" in prompt
    assert "do not certify inventory_complete: return false" in prompt
    assert "with drops_applicable_meaning or unclear" in prompt
    assert "For refine/replace, return condition_spans for ALL independently identified" in prompt
    assert "Return condition_spans for ALL independently identified applicable conditions and" not in prompt
    assert "Judge final title, body and report attribution together" in prompt
    assert "All normal complete final-scope, whole-update, report-authority and commit checks remain" in prompt


@pytest.mark.parametrize("change", ["whole_claim", "duplicate", "reordered"])
def test_add_declared_binding_still_rejects_extra_or_reordered_conditions(change):
    manifest, _, native = condition_fixture()
    if change == "reordered":
        # Two declared obligations remain ordered even when both spans are valid.
        for row in manifest["candidates"]:
            row["update_context"]["retained_conditions"].append("selection remains undecided")
        for point in native["points"]:
            proof = point["update_meaning_judgment"]
            proof["condition_spans"].insert(0, copy.deepcopy(proof["undecided_span"]))
    else:
        for point in native["points"]:
            proof = point["update_meaning_judgment"]
            span = copy.deepcopy(proof["condition_spans"][0])
            if change == "whole_claim":
                span["char_start"] = 0
            proof["condition_spans"].insert(0, span)
    with pytest.raises(ValueError, match="omits or changes declared condition obligations"):
        expand(manifest, native)


def test_add_undeclared_condition_cannot_pass_with_an_incomplete_inventory():
    manifest, payloads, native = condition_fixture()
    for point in native["points"]:
        proof = point["update_meaning_judgment"]
        proof["inventory_complete"] = False
        proof["relationship"] = "unclear"
        proof["basis"] = "Independent source audit found an undeclared necessary condition."
    decision = expand(manifest, native)
    assert judged_update_payload(payloads[0], decision, manifest["candidates"])[1] == "final_update_meaning_incomplete"
