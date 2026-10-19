"""Attributed reports cannot become external facts through current-memory writes."""

import asyncio
from datetime import datetime, timezone

import pytest

from harness_mem.autonomous.models import AgentExtractionDecision
from harness_mem.autonomous.provider import expand_agent_extraction_decision
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation, validate_separated_assimilation_decision,
    _validate_apply_points,
)
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _report(**updates):
    return SourceReport(**{
        "speaker": "assistant", "period": "that session (date unknown)",
        "session_id": "discussion-1", "source_id": "source-1", "source_revision": "revision-1",
        "exchange_indexes": [1],
        "text": "In the Iris discussion, the observed sample was not rollout evidence.",
        **updates,
    })


def _point(disposition="add", targets=()):
    return {
        "disposition": disposition, "matched_truth_ids": list(targets),
        "knowledge_items": [{"title": "Sample boundary", "statement": "Rollout was approved.",
                             "topic_path": ["evidence"], "claim_kind": "implementation_fact"}],
        "reason": "Retain the supported report without elevating its authority.",
        "verified_at": datetime.now(timezone.utc),
    }


def _source(kind="source_report"):
    return ProjectKnowledgeSourceRef(
        label="Retained source", kind=kind, digest="a" * 64,
        target="file:///fixture/transcripts.sqlite#source_id=source-1&source_revision=revision-1&exchange=1&role=assistant",
    )


def test_report_extraction_binds_real_speaker_without_user_statement_relabel():
    compact = AgentExtractionDecision.model_validate({
        "review": {"summary": "A bounded diagnostic observation was discussed.",
                   "final_request": "Keep the evidence boundary", "actual_result": "Reported only"},
        "points": [{"kind": "memory", "statement": _report().text,
                    "evidence_basis": "source_report", "report_role": "assistant", "exchange_indexes": [1]}],
    })
    decision = expand_agent_extraction_decision(compact, manifest={
        "semantic_decision_exchanges": [{"exchange_index": 1, "content_sha256": "a" * 64}],
    })
    candidate = decision.candidates[0]
    assert candidate.evidence_basis == "source_report"
    assert candidate.verification_refs[0].role == "assistant"
    assert candidate.verification_refs[0].kind == "source_report"


def test_hermes_json_contract_does_not_omit_the_authorized_report_kind():
    from harness_mem.autonomous.executors.host_structured_cli import _hermes_output_contract
    assert "source_report" in _hermes_output_contract(AssimilationDecision)
    assert "report_role" in _hermes_output_contract(AgentExtractionDecision)


def test_legacy_fact_payload_roundtrips_without_new_metadata():
    row = KnowledgeEntry(project_name="demo", module_path=["facts"], title="Fact", statement="A verified fact.")
    assert "source_report" not in row.to_dict()
    assert KnowledgeEntry.from_dict(row.to_dict()).to_dict() == row.to_dict()


def test_untrusted_report_rewrite_cannot_strip_attribution_or_change_verified_content(tmp_path):
    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            report = _report()
            candidate = KnowledgeCandidate(project_name="demo", candidate_type="memory", statement=report.text, source_report=report)
            result = await record_assimilation_result(
                backend, candidate=candidate, point=_point(), project_root=tmp_path, source_refs=[_source()],
            )
            row = await backend.structured_store.knowledge_store.get_entry(result[0], project_name="demo")
            assert row.source_report == report
            assert row.statement == report.render_statement()
            assert "Rollout was approved" not in row.statement
            assert row.title.startswith("Source report — ")
            assert KnowledgeEntry.from_dict(row.to_dict()).source_report == report
            return row
        finally:
            await backend.close()
    row = asyncio.run(exercise())
    assert "not independently established current fact or user approval" in row.statement


@pytest.mark.parametrize("disposition", ["refine", "replace", "confirm"])
def test_report_cannot_target_an_existing_verified_fact(tmp_path, disposition):
    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            store = backend.structured_store.knowledge_store
            fact = KnowledgeCandidate(project_name="demo", candidate_type="memory", statement="The actual rollout requires a signed approval.")
            fact_point = _point()
            fact_point["knowledge_items"][0]["statement"] = fact.statement
            ids = await record_assimilation_result(backend, candidate=fact, point=fact_point, project_root=tmp_path, source_refs=[_source("repository")])
            before = (await store.get_entry(ids[0], project_name="demo")).to_dict()
            report = _report()
            candidate = KnowledgeCandidate(project_name="demo", candidate_type="memory", statement=report.text, source_report=report)
            point = _point(disposition, ids)
            if disposition == "confirm":
                point["knowledge_items"] = []
            with pytest.raises(ValueError, match="source.report.*(fact|authority)|authority.*boundary"):
                await record_assimilation_result(backend, candidate=candidate, point=point, project_root=tmp_path, source_refs=[_source()])
            assert (await store.get_entry(ids[0], project_name="demo")).to_dict() == before
        finally:
            await backend.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("incoming_report", [True, False])
@pytest.mark.parametrize("disposition", ["confirm", "replace", "refine"])
def test_provider_and_serialized_apply_plan_both_preflight_authority(incoming_report, disposition):
    report = _report()
    candidate = {"candidate_id": "C1", "statement": report.text}
    current = {"handle": "T1", "statement": report.render_statement()}
    metadata = report.model_dump(mode="json", exclude={"text"})
    (candidate if incoming_report else current)["source_report"] = metadata
    prepared = SeparatedPreparedAssimilation(
        project_name="demo", project_root="", candidate_ids=("C1",), eligible_candidate_ids=("C1",),
        automatic_points=(), answer_status_by_candidate={"C1": "ANSWERED"}, truth_by_handle={"T1": "K1"},
        manifest={"verified_candidates": [candidate], "current_truth": [current]},
    )
    item = _point()["knowledge_items"]
    decision = AssimilationDecision.model_validate({"points": [{
        "candidate_id": "C1", "disposition": disposition, "matched_truth_handles": ["T1"],
        "knowledge_items": [] if disposition == "confirm" else item,
        "reason": "An attempted cross-authority target must fail before a write.",
    }]})
    with pytest.raises(ValueError, match="source.report|authority"):
        validate_separated_assimilation_decision(prepared, decision)
    serialized = {
        "candidate_id": "C1", "answer_status": "ANSWERED", "disposition": disposition,
        "matched_truth_ids": ["K1"], "knowledge_items": [] if disposition == "confirm" else item,
        "reason": "A serialized answer status must not bypass the source report boundary.",
    }
    with pytest.raises(ValueError, match="source.report|authority"):
        _validate_apply_points(prepared, [serialized])


def test_report_metadata_cannot_be_removed_from_its_stored_statement():
    report = _report()
    with pytest.raises(ValueError, match="attribution"):
        KnowledgeEntry(project_name="demo", module_path=["scope"], title="A current fact",
                       statement=report.text, source_report=report)


def test_dream_cannot_upgrade_or_merge_an_attributed_report(tmp_path):
    from harness_mem.commands.dream_assimilation import (
        DreamAssimilationCandidate, prepare_dream_assimilation, validate_dream_assimilation_decision,
    )
    report = _report()
    row = KnowledgeEntry(project_name="demo", module_path=["scope"], title=report.render_title(),
                         statement=report.render_statement(), source_report=report)
    candidate = DreamAssimilationCandidate(
        candidate_id="D1", entry=row, sources=(), semantic_support="contradicted", future_scope="durable",
        verification_reason="Recheck the report against its source, not external actuality.", source_excerpts=(),
    )
    prepared = prepare_dream_assimilation(project_name="demo", project_root=tmp_path,
                                         run_id="D-run", signal_kind="conflict", candidates=[candidate])
    decision = AssimilationDecision.model_validate({"points": [{
        "candidate_id": "D1", "disposition": "replace", "matched_truth_handles": ["T1"],
        "knowledge_items": _point()["knowledge_items"], "reason": "Attempt to turn the report into a fact.",
    }]})
    with pytest.raises(ValueError, match="source.report authority"):
        validate_dream_assimilation_decision(prepared, decision)
