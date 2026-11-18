"""Manual final judging stamps accepted conditions only after common proof."""
import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from harness_mem.autonomous.models import NativeFinalScopeDecision
from harness_mem.commands.knowledge_assimilation import _require_retained_meaning
from harness_mem.commands.separated_assimilation import (
    final_scope_proof, final_scope_verification_rows, prove_supplied_final_scope, target_version,
)
from harness_mem.core.schemas.source_report import SourceReport, source_report_snapshot
from harness_mem.mcp.distill_handlers import _copy_update_meaning
from test_add_condition_final_contract import condition_fixture, expand
from test_native_final_scope_transport import fixture_manifest, native_payload


def accept(point, decision):
    """The public consumer's order: original proof, then stamped propagation."""
    proof = prove_supplied_final_scope(payload=point, judgment=decision)
    _copy_update_meaning(point, decision, payload=copy.deepcopy(point))
    return proof


def test_valid_manual_add_retains_conditions_and_matches_canonical_final_bytes():
    manifest, payloads, native = condition_fixture()
    point = copy.deepcopy(payloads[0])
    proof = accept(point, expand(manifest, native))
    assert point["retained_conditions"] == payloads[0]["retained_conditions"]
    assert point["undecided_state"] == payloads[0]["undecided_state"]
    assert point["update_meaning_judgment"]["predecessor_statements"] == []
    assert proof == final_scope_proof(point)
    _require_retained_meaning(point["knowledge_items"], point)


def test_raw_only_manual_add_copies_independently_discovered_condition_inventory():
    manifest, payloads, native = condition_fixture()
    point = copy.deepcopy(payloads[0])
    point.pop("retained_conditions")
    point.pop("undecided_state")
    decision = expand(manifest, native)
    point["update_meaning_judgment"] = decision.points[0].update_meaning_judgment.model_dump(mode="json")
    point["update_meaning_judgment"]["basis"] = "Untrusted assimilator proposal is not final approval."
    proof = accept(point, decision)
    assert point["retained_conditions"] == ["only offline"]
    assert point["undecided_state"] == "selection remains undecided"
    assert proof == final_scope_proof(point)
    _require_retained_meaning(point["knowledge_items"], point)


@pytest.mark.parametrize("failure", ["proposal_only", "erase_declared", "erase_undecided", "different_output", "partial"])
def test_manual_add_cannot_wash_declared_obligations_before_judging(failure):
    manifest, payloads, native = condition_fixture()
    decision = expand(manifest, native)
    point = copy.deepcopy(payloads[0])
    if failure == "proposal_only":
        point["update_meaning_judgment"] = decision.points[0].update_meaning_judgment.model_dump(mode="json")
        for verdict in decision.points:
            verdict.update_meaning_judgment = None
    elif failure == "partial":
        decision.points[0].semantic_support = "partial"
    else:
        for verdict in decision.points:
            if failure == "erase_declared":
                verdict.update_meaning_judgment.predecessor_conditions = []
            elif failure == "erase_undecided":
                verdict.update_meaning_judgment.undecided_state = None
            else:
                verdict.update_meaning_judgment.successor_statements[0] += " Foreign text."
    before = copy.deepcopy(point)
    with pytest.raises(ValueError, match="rejected"):
        accept(point, decision)
    assert point == before
    if failure != "partial":
        with pytest.raises(ValueError, match="rejected"):
            _copy_update_meaning(point, decision, payload=copy.deepcopy(point))
        assert point == before


def test_foreign_owner_cannot_supply_manual_add_meaning():
    manifest, payloads, native = condition_fixture(owners=2)
    decision = expand(manifest, native)
    other = decision.model_copy(update={"points": [
        row.model_copy(update={"candidate_index": index}) for index, row in enumerate(decision.points[2:])
    ]})
    point = copy.deepcopy(payloads[0])
    before = copy.deepcopy(point)
    with pytest.raises(ValueError, match="rejected"):
        accept(point, other)
    assert point == before


def test_ordinary_manual_add_keeps_null_meaning_and_original_proof():
    manifest, payloads = fixture_manifest(disposition="add")
    point = payloads[0]
    point["targets"] = []
    before = copy.deepcopy(point)
    decision = NativeFinalScopeDecision.model_validate(native_payload(manifest)).as_verification(manifest)
    assert accept(point, decision) == final_scope_proof(before)
    assert point == before


@pytest.mark.parametrize("empty_predecessors", [False, True])
def test_manual_refine_still_requires_complete_nonempty_bound_predecessors(empty_predecessors):
    manifest, payloads = fixture_manifest()
    point = payloads[0]
    decision = NativeFinalScopeDecision.model_validate(native_payload(manifest)).as_verification(manifest)
    if empty_predecessors:
        point["targets"] = []
        before = copy.deepcopy(point)
        with pytest.raises(ValueError, match="rejected"):
            accept(point, decision)
        assert point == before
    else:
        assert accept(point, decision) == final_scope_proof(point)
        assert point["update_meaning_judgment"]["predecessor_versions"]


def test_manual_report_scope_and_attribution_still_bind_exact_rendered_output():
    report = SourceReport(speaker="assistant", period="2024-01-01", session_id="fixture-session", source_id="fixture-source",
        source_revision="sha256:" + "a" * 64, exchange_indexes=[1], text="Only offline behavior was reported.")
    target = dict(id="report-old", title=report.render_title(), statement=report.render_statement(),
        topic_path=["reports"], source_report=source_report_snapshot(report))
    target["version"] = target_version(target)
    point = dict(candidate_id="report-owner", disposition="replace", targets=[target], knowledge_items=[dict(
        title=report.render_title(), statement=report.render_statement(), topic_path=["reports"],
        claim_kind="source_report", source_report=source_report_snapshot(report))])
    manifest = dict(contract_version="final-knowledge-scope-v1", candidates=final_scope_verification_rows(point, []))
    decision = NativeFinalScopeDecision.model_validate(native_payload(manifest)).as_verification(manifest)
    assert accept(point, decision) == final_scope_proof(point)
    point["knowledge_items"][0]["source_report"]["speaker"] = "user"
    before = copy.deepcopy(point)
    with pytest.raises(ValueError):
        accept(point, decision)
    assert point == before


@pytest.mark.parametrize("clear_declared", [False, True])
def test_public_manual_consumer_uses_original_payload_before_stamping(monkeypatch, clear_declared):
    from harness_mem.commands import knowledge_assimilation as knowledge
    from harness_mem.commands import separated_assimilation as shared
    from harness_mem.mcp.distill_handlers import _consume_supplied_final_scope

    manifest, payloads, native = condition_fixture()
    point = copy.deepcopy(payloads[0])
    decision = expand(manifest, native)
    if clear_declared:
        for verdict in decision.points:
            verdict.update_meaning_judgment.predecessor_conditions = []
    evidence = NS(verification_reason_codes=[])
    saved = []

    async def get_candidate(_identity):
        return NS(id=point["candidate_id"])

    async def list_evidence(_identity):
        return [evidence]

    async def save_evidence(value):
        saved.append(copy.deepcopy(value.verification_reason_codes))

    async def uncommitted(*_a, **_k):
        return False

    async def prepare(*_a, **_k):
        return NS()

    monkeypatch.setattr(knowledge, "is_committed_knowledge_point", uncommitted)
    monkeypatch.setattr(shared, "prepare_separated_assimilation", prepare)
    monkeypatch.setattr(shared, "final_scope_payload", lambda _prepared, value: copy.deepcopy(value))
    backend = NS(structured_store=NS(knowledge_store=NS(get_candidate=get_candidate,
        list_evidence=list_evidence, save_evidence=save_evidence)))
    before = copy.deepcopy(point)
    result = asyncio.run(_consume_supplied_final_scope(backend, project_name="fixture", project_root="/isolated",
        candidate_ids=[point["candidate_id"]], plan={"points": [point]},
        contract={point["candidate_id"]: decision}))
    if clear_declared:
        assert result["reason_codes"] == ["final_scope_judgment_rejected"]
        assert not saved and point == before
    else:
        assert result is None and len(saved) == 1
        assert final_scope_proof(point) in evidence.verification_reason_codes
        assert point["retained_conditions"] == before["retained_conditions"]
        _require_retained_meaning(point["knowledge_items"], point)
