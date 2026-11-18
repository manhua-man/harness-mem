"""Point-local final proof rejection; no native calls or current-memory writes."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from test_native_final_scope_transport import fixture_manifest, native_payload
from test_report_original_inventory import fixture as report_fixture, native_vote
from harness_mem.autonomous.models import NativeFinalScopeDecision, verification_scope_status
from harness_mem.commands.separated_assimilation import (
    bind_final_scope_judgment, defer_blocked_final_scope, judged_update_payload,
)


def rejected(point):
    assert point.semantic_support == "partial"
    assert point.future_scope == point.source_use == "unclear"
    assert point.reason.startswith("native_final_point_proof_invalid:")
    assert point.scope_segments == point.claim_units == []
    assert point.update_meaning_judgment is None
    assert point.literal_edit_contract is None
    assert verification_scope_status(point, "Any final output") != "source_scope_durable"


@pytest.mark.parametrize("fault", ["range", "leading_space", "no_context", "unbound_report_inventory"])
def test_internal_proof_fault_is_negative_and_other_owner_is_unchanged(fault):
    manifest, payloads = fixture_manifest(outputs=[" A local condition remains."], owners=2)
    payload = native_payload(manifest)
    # Keep a valid literal range on both owners before corrupting only owner 1.
    for point in payload["points"]:
        text = manifest["candidates"][point["candidate_index"]]["statement"]
        start = text.index("A local")
        point["update_meaning_judgment"]["condition_spans"][0]["char_start"] = start
    proof = payload["points"][1]["update_meaning_judgment"]
    if fault == "range":
        proof["condition_spans"][0]["char_end"] = 99999
    elif fault == "leading_space":
        proof["condition_spans"][0]["char_start"] -= 1
    elif fault == "no_context":
        manifest["candidates"][1].pop("update_context")
    else:
        proof["report_preservation"] = {"inventory_complete": True, "units": [], "omissions": []}
    native = NativeFinalScopeDecision.model_validate(payload)
    original = native.model_dump(mode="json")
    with pytest.raises(ValueError):
        native.as_verification(manifest)
    decision = native.as_verification(manifest, isolate_invalid_points=True)
    rejected(decision.points[1])
    only_valid = copy.deepcopy(manifest)
    only_valid["candidates"] = only_valid["candidates"][:1]
    expected = NativeFinalScopeDecision(points=native.points[:1]).as_verification(only_valid)
    assert decision.points[0] == expected.points[0]
    assert native.model_dump(mode="json") == original  # No repair or range trimming.
    blocked = bind_final_scope_judgment(manifest["candidates"], decision)
    assert set(blocked) == {"owner-1"}
    assert judged_update_payload(payloads[0], decision, manifest["candidates"])[1] is None
    assert judged_update_payload(payloads[1], decision, manifest["candidates"])[1] is not None
    # The existing common owner removes all writable payload and target access.
    plan = {"points": [{**item, "matched_truth_ids": [target["id"] for target in item["targets"]]}
                       for item in payloads]}
    safe = defer_blocked_final_scope(plan, blocked)
    assert safe["points"][0]["disposition"] == "refine"
    assert safe["points"][1]["disposition"] == "defer"
    assert safe["points"][1]["knowledge_items"] == safe["points"][1]["matched_truth_ids"] == []


def test_one_bad_output_defers_its_whole_same_owner_replacement():
    manifest, payloads = fixture_manifest()
    payload = native_payload(manifest)
    payload["points"][1]["update_meaning_judgment"]["condition_spans"][0]["char_end"] = 99999
    decision = NativeFinalScopeDecision.model_validate(payload).as_verification(manifest, isolate_invalid_points=True)
    assert decision.points[0].semantic_support == "supported"
    rejected(decision.points[1])
    blocked = bind_final_scope_judgment(manifest["candidates"], decision)
    assert set(blocked) == {payloads[0]["candidate_id"]}
    assert judged_update_payload(payloads[0], decision, manifest["candidates"])[1] is not None
    safe = defer_blocked_final_scope({"points": payloads}, blocked)
    assert safe["points"][0]["disposition"] == "defer"
    assert safe["points"][0]["knowledge_items"] == safe["points"][0]["matched_truth_ids"] == []


@pytest.mark.parametrize("fault", ["unit_inventory", "inventory_binding"])
def test_report_inventory_fault_is_local_and_does_not_borrow_other_proof(fault):
    _prepared, _plan, _payload, report, _classification = report_fixture()
    native = native_vote(report)
    ordinary, _payloads = fixture_manifest(outputs=["Independent local condition."])
    ordinary["candidates"][0]["candidate_index"] = 1
    report["candidates"].extend(ordinary["candidates"])
    other = native_payload(ordinary)["points"][0]
    native["points"].append(other)
    if fault == "unit_inventory":
        native["points"][0]["update_meaning_judgment"]["report_preservation"]["units"].pop()
    else:
        report["candidates"][0]["update_context"]["report_preservation_inventory"]["units"][0]["sha256"] = "a" * 64
    response = NativeFinalScopeDecision.model_validate(native)
    with pytest.raises(ValueError):
        response.as_verification(report)
    actual = response.as_verification(report, isolate_invalid_points=True)
    rejected(actual.points[0])
    assert actual.points[1].semantic_support == "supported"
    assert actual.points[1].update_meaning_judgment is not None


@pytest.mark.parametrize("fault", ["missing", "duplicate", "foreign_index", "missing_owner", "wrong_scope", "wrong_contract"])
def test_outer_candidate_identity_and_bound_header_stay_globally_strict(fault):
    manifest, _payloads = fixture_manifest()
    payload = native_payload(manifest)
    if fault == "missing":
        payload["points"].pop()
    elif fault == "duplicate":
        payload["points"][1]["candidate_index"] = 0
    elif fault == "foreign_index":
        payload["points"][1]["candidate_index"] = 99
    elif fault == "missing_owner":
        manifest["candidates"][0].pop("owner_candidate_id")
    elif fault == "wrong_scope":
        manifest["candidates"][0]["scope_text"] += "Forged bound header."
    else:
        manifest["contract_version"] = "unbound-contract"
    response = NativeFinalScopeDecision.model_validate(payload)
    with pytest.raises(ValueError):
        response.as_verification(manifest, isolate_invalid_points=True)


def test_bad_native_json_shape_is_not_a_point_local_projection_failure():
    manifest, _payloads = fixture_manifest()
    payload = native_payload(manifest)
    payload["points"][1]["update_meaning_judgment"]["condition_spans"][0]["char_end"] = "99"
    with pytest.raises(ValidationError):
        NativeFinalScopeDecision.model_validate_json(json.dumps(payload))
    with pytest.raises(ValidationError):
        NativeFinalScopeDecision.model_validate_json('{"points": [')


def test_exact_local_report_0006_replay_preserves_point_zero_and_rejects_point_one():
    directory = Path(__file__).resolve().parents[2] / ".tmp/automatic-repair-20261021/report-retry/native-calls"
    if not (directory / "0006-result.json").is_file():
        pytest.skip("Exact local native receipt is not distributed as a source fixture.")
    result = json.loads((directory / "0006-result.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "0006-manifest.json").read_text(encoding="utf-8"))
    assert result["decision_schema"] == "NativeFinalScopeDecision"
    response = NativeFinalScopeDecision.model_validate(result["normalized_decision"])
    original = response.model_dump(mode="json")
    with pytest.raises(ValueError, match="not an exact canonical single-line condition"):
        response.as_verification(manifest)
    actual = response.as_verification(manifest, isolate_invalid_points=True)
    rejected(actual.points[1])
    one = copy.deepcopy(manifest)
    one["candidates"] = one["candidates"][:1]
    expected = NativeFinalScopeDecision(points=response.points[:1]).as_verification(one)
    assert actual.points[0] == expected.points[0]
    assert actual.points[0].semantic_support == "supported"
    assert actual.points[0].update_meaning_judgment is not None
    assert response.model_dump(mode="json") == original
    assert set(bind_final_scope_judgment(manifest["candidates"], actual)) == {
        manifest["candidates"][1]["owner_candidate_id"]}
