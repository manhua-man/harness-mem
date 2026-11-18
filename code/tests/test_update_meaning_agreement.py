"""Semantic consensus ignores only explanation prose; all truth gates remain.

All providers are pure test doubles and all canonical stores/sources are under
pytest tmp_path. No native model, Hook, live store or user source is touched.
"""
import copy
import hashlib
import json

import pytest

from test_dream_stage4_contract import backend as backend, _publish, _result, _run
from test_native_final_scope_transport import fixture_manifest, native_payload
from harness_mem.autonomous.models import (
    AssimilationDecision, CandidateVerificationDecision, NativeFinalScopeDecision, UpdateMeaningJudgment,
)
from harness_mem.autonomous.provider import verification_point_receipts
from harness_mem.commands.dream import dream_once
from harness_mem.commands.dream_assimilation import _scope_decision_for_outputs
from harness_mem.commands.separated_assimilation import judged_update_payload, prove_supplied_final_scope
from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.mcp.distill_handlers import _copy_update_meaning
from harness_mem.read_knowledge import search_current_knowledge


def native_decision(manifest):
    payload = native_payload(manifest)
    for index, point in enumerate(payload["points"]):
        successors = manifest["candidates"][index]["update_context"]["successors"]
        proof = point["update_meaning_judgment"]
        proof["condition_spans"] = [dict(successor_index=number, char_start=0, char_end=len(row["statement"]))
                                    for number, row in enumerate(successors)]
        statement = successors[-1]["statement"]
        start = statement.index("selection")
        proof["undecided_span"] = dict(successor_index=len(successors) - 1, char_start=start, char_end=len(statement) - 1)
        proof["basis"] = f"Independent explanation {index} checks all original conditions and the undecided state."
    return NativeFinalScopeDecision.model_validate(payload).as_verification(manifest)


def fixture_decision():
    manifest, payloads = fixture_manifest()
    return manifest, payloads[0], native_decision(manifest)


def test_native_independent_explanations_pass_semantic_consensus_and_complete_scope():
    manifest, payload, decision = fixture_decision()
    before = copy.deepcopy(decision.model_dump())
    first, second = [point.update_meaning_judgment for point in decision.points]
    assert first.basis != second.basis
    assert first.agrees_with(second) and second.agrees_with(first)
    assert first.model_dump(exclude={"basis"}) == second.model_dump(exclude={"basis"})
    stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
    assert blocked is None
    assert stamped["update_meaning_judgment"]["basis"] == first.basis
    assert prove_supplied_final_scope(payload=stamped, judgment=decision)
    assert _scope_decision_for_outputs(decision.points, first).model_dump() == before
    assert decision.model_dump() == before


def test_manual_summary_keeps_schema_and_every_original_output_explanation():
    manifest, payload, decision = fixture_decision()
    before = copy.deepcopy(decision.model_dump())
    supplied = CandidateVerificationDecision.model_validate(before)
    plan = dict(disposition="refine")
    _copy_update_meaning(plan, supplied, payload=payload)
    assert plan["update_meaning_judgment"]["basis"] == supplied.points[0].update_meaning_judgment.basis
    assert supplied.model_dump() == before
    assert supplied.points[0].update_meaning_judgment.basis != supplied.points[1].update_meaning_judgment.basis
    assert set(plan["update_meaning_judgment"]) == {
        "relationship", "predecessor_conditions", "predecessor_statements", "predecessor_versions",
        "undecided_state", "successor_statements", "basis",
    }
    assert UpdateMeaningJudgment.model_validate(plan["update_meaning_judgment"]).agrees_with(supplied.points[1].update_meaning_judgment)
    stamped, blocked = judged_update_payload({**payload, **plan}, supplied, manifest["candidates"])
    assert blocked is None and prove_supplied_final_scope(payload=stamped, judgment=supplied)


@pytest.mark.parametrize("field,change", [
    ("relationship", "drops_applicable_meaning"), ("relationship", "unclear"),
    ("predecessor_conditions", "remove"), ("predecessor_conditions", "reverse"),
    ("predecessor_conditions", "add"), ("predecessor_statements", "reverse"),
    ("predecessor_statements", "different"), ("predecessor_versions", "reverse"),
    ("predecessor_versions", "different"), ("successor_statements", "reverse"),
    ("successor_statements", "different"), ("undecided_state", None), ("undecided_state", "Signing"),
])
def test_only_basis_is_excluded_every_predicate_and_order_disagreement_blocks(field, change):
    manifest, payload, decision = fixture_decision()
    first, second = [point.update_meaning_judgment for point in decision.points]
    if change == "reverse":
        value = list(reversed(getattr(second, field)))
    elif change == "remove":
        value = list(getattr(second, field))[1:]
    elif change == "add":
        value = [*getattr(second, field), "offline"]
    elif change == "different":
        value = ["different", *getattr(second, field)[1:]]
    else:
        value = change
    altered = second.model_copy(update={field: value}, deep=True)
    decision.points[1].update_meaning_judgment = altered
    assert not first.agrees_with(altered)
    assert judged_update_payload(payload, decision, manifest["candidates"])[1] == "final_update_meaning_incomplete"
    plan = {"disposition": "refine"}
    with pytest.raises(ValueError, match="final_update_meaning_incomplete"):
        _copy_update_meaning(plan, decision, payload=payload)
    assert "update_meaning_judgment" not in plan
    with pytest.raises(ValueError):
        _scope_decision_for_outputs(decision.points, first)


@pytest.mark.parametrize("field,value", [
    ("predecessor_conditions", ["condition absent from both actual outputs"]),
    ("predecessor_statements", ["a different actual predecessor"]),
    ("predecessor_versions", ["wrong-current-version"]),
    ("successor_statements", ["an unrelated successor"]),
    ("undecided_state", "a state absent from actual outputs"),
    ("relationship", "unclear"),
])
def test_all_outputs_agreeing_on_invalid_binding_or_vote_still_block(field, value):
    manifest, payload, decision = fixture_decision()
    bad = decision.points[0].update_meaning_judgment.model_copy(update={field: value}, deep=True)
    decision.points[0].update_meaning_judgment = bad
    decision.points[1].update_meaning_judgment = bad.model_copy(update={"basis": "A different explanation still has the same invalid endpoint or vote."}, deep=True)
    assert decision.points[0].update_meaning_judgment.agrees_with(decision.points[1].update_meaning_judgment)
    assert judged_update_payload(payload, decision, manifest["candidates"])[1] == "final_update_meaning_incomplete"


@pytest.mark.parametrize("missing", ["first", "second", "both", "row"])
def test_missing_or_incomplete_output_proof_is_not_filled_from_another_output(missing):
    manifest, payload, decision = fixture_decision()
    if missing == "row":
        decision.points.pop()
    else:
        for index, point in enumerate(decision.points):
            if missing == "both" or (missing == "first" and index == 0) or (missing == "second" and index == 1):
                point.update_meaning_judgment = None
    assert judged_update_payload(payload, decision, manifest["candidates"])[1] == "final_update_meaning_incomplete"
    assert decision.points[0].update_meaning_judgment is None or not decision.points[0].update_meaning_judgment.agrees_with(None)


@pytest.mark.parametrize("issue", ["mixed", "unsupported", "unclear", "missing_partition"])
def test_semantic_consensus_never_overrides_independent_final_source_and_scope(issue):
    manifest, payload, decision = fixture_decision()
    if issue == "missing_partition":
        decision.points[0].scope_segments = []
    else:
        part = decision.points[0].scope_segments[0]
        if issue == "mixed":
            part.source_use, part.future_scope, part.content_role = "task_context", "session_only", "temporary_context"
        elif issue == "unsupported":
            part.source_support = "unsupported"
        else:
            part.source_use, part.future_scope = "unclear", "unclear"
    stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
    assert blocked is None
    with pytest.raises(ValueError):
        prove_supplied_final_scope(payload=stamped, judgment=decision)


def test_content_free_receipt_binds_each_original_basis_digest_without_prose():
    _manifest, _payload, decision = fixture_decision()
    receipts = verification_point_receipts(decision)
    bases = [point.update_meaning_judgment.basis for point in decision.points]
    assert bases[0] != bases[1]
    for point, receipt in zip(decision.points, receipts):
        assert receipt["update_meaning"]["basis_sha256"] == hashlib.sha256(point.update_meaning_judgment.basis.encode()).hexdigest()
        assert "basis" not in receipt["update_meaning"]
    assert all(basis not in json.dumps(receipts) for basis in bases)
    assert receipts[0]["update_meaning"]["basis_sha256"] != receipts[1]["update_meaning"]["basis_sha256"]


FIRST = "Caching is allowed only offline."
SECOND = "Signing stays required; selection remains undecided."
ORIGINAL = FIRST + " " + SECOND + " Trial completed today."


class TwoOutputProvider:
    name = "isolated-two-output-consensus"
    def __init__(self, *, invalid_authority=False):
        self.phases = []
        self.final_decision = None
        self.invalid_authority = invalid_authority

    def assimilate(self, manifest, **kwargs):
        self.phases.append("assimilate")
        candidate = manifest["verified_candidates"][0]
        return _result(AssimilationDecision.model_validate(dict(points=[dict(
            candidate_id=candidate["candidate_id"], disposition="refine",
            matched_truth_handles=[manifest["current_truth"][0]["handle"]],
            knowledge_items=[dict(title="Offline caching", statement=FIRST, topic_path=["cache"],
                                  claim_kind="source_report" if self.invalid_authority else "implementation_fact"),
                             dict(title="Signing decision", statement=SECOND, topic_path=["signing"], claim_kind="implementation_fact")],
            reason="Retain all standing conditions and the undecided state without the trial receipt.",
        )])))

    def verify(self, manifest, **kwargs):
        self.phases.append("verify")
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            self.final_decision = native_decision(manifest)
            return _result(self.final_decision)
        points = []
        for row in manifest["candidates"]:
            points.append(dict(candidate_index=row["candidate_index"], semantic_support="supported", future_scope="unclear",
                               source_use="reusable_knowledge", reason="Keep both complete source-supported standing rules and remove only trial progress.",
                               scope_segments=[dict(text=row["title"] + "\n" + FIRST + " " + SECOND,
                                   content_role="claim", source_support="supported", source_use="reusable_knowledge", future_scope="durable", standalone=True),
                                   dict(text=" Trial completed today.", content_role="temporary_context", source_support="supported",
                                        source_use="task_context", future_scope="session_only", standalone=True)]))
        return _result(CandidateVerificationDecision.model_validate(dict(points=points)))


def test_native_two_output_consensus_reaches_dream_plan_canonical_commit_and_ordinary_search(backend):
    entry = KnowledgeEntry(id="agreement-original", project_name="demo", title="Cache policy", statement=ORIGINAL, module_path=["cache"])
    root, _path, _original = _publish(backend, entry)
    provider = TwoOutputProvider()
    run = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert provider.phases == ["verify", "assimilate", "verify"]
    assert provider.final_decision.points[0].update_meaning_judgment.basis != provider.final_decision.points[1].update_meaning_judgment.basis
    store = backend.structured_store.knowledge_store
    assert _run(store.get_entry(entry.id, project_name="demo", project_root=root)) is None
    current = _run(store.list_entries("demo", project_root=root))
    assert {row.statement for row in current} == {FIRST, SECOND}
    assert all("Trial" not in row.statement for row in current)
    assert run.resolution_status == "resolved"
    assert any(item.final_action == "applied" and item.result.get("truth_change") == "refine" for item in run.items)
    offline = _run(search_current_knowledge(backend, project_name="demo", query="offline", limit=10))
    undecided = _run(search_current_knowledge(backend, project_name="demo", query="undecided", limit=10))
    assert {row.statement for row in offline} == {FIRST}
    assert {row.statement for row in undecided} == {SECOND}


@pytest.mark.parametrize("failure", ["missing_source", "report_authority"])
def test_two_output_approval_cannot_bypass_real_source_or_report_authority(backend, failure):
    entry = KnowledgeEntry(id="agreement-blocked", project_name="demo", title="Cache policy", statement=ORIGINAL, module_path=["cache"])
    root, path, original = _publish(backend, entry)
    if failure == "missing_source":
        # Dream intentionally permits updated repository bytes at an unchanged
        # safe locator, subject to fresh semantic verification. Missing original
        # evidence instead has no bytes to supply to that verifier.
        path.unlink()
    provider = TwoOutputProvider(invalid_authority=failure == "report_authority")
    run = _run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.model_dump() for row in current] == [row.model_dump() for row in original]
    assert not any(item.final_action == "applied" and item.result.get("truth_change") in {"refine", "replace", "deleted"} for item in run.items)
