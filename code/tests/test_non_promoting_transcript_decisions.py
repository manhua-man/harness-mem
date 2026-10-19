"""Non-promotion decisions must not require admitting transcript as truth."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import sqlite3

import pytest
import pytest_asyncio

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.knowledge_assimilation import resolve_separated_review
from harness_mem.commands.separated_assimilation import (
    admit_separated_candidate,
    apply_separated_assimilation,
    prepare_interactive_assimilation,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import EvidenceRef
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


PROJECT = "non-promoting-test"
STATEMENT = "Preserve original sources before changing policy."
REASON = "This is a one-off discussion, not a new durable policy."


@pytest_asyncio.fixture
async def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    value = LocalMemoryBackend(tmp_path / "data")
    await value.init()
    try:
        yield value
    finally:
        await value.close()


async def _candidate(
    backend, *, disposition="no_write", basis="transcript", name="point", padding="",
    ref_shape="chunk", user_text=STATEMENT, assistant_text="Understood.", statement=None,
):
    assistant = assistant_text + padding
    rendering = f"User: {user_text}\n\nAssistant: {assistant}"
    native = "\n".join(json.dumps({
        "type": "response_item",
        "payload": {"type": "message", "role": role, "content": [{
            "type": "input_text" if role == "user" else "output_text", "text": text,
        }]},
    }) for role, text in [("user", user_text), ("assistant", assistant)]) + "\n"
    snapshot = await persist_session_snapshot(
        backend,
        Observation(session_id=name, client="codex", raw_content=rendering,
                    content_type="transcript", timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": PROJECT}),
        project_name=PROJECT, project_root="", client="codex", session_id=name,
        source_kind="jsonl", source_uri=(backend.data_dir / f"{name}.jsonl").as_uri(),
        source_text=native, parser_version="codex-jsonl-v1", capture_config=MergedConfig(),
    )
    job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert job is not None
    chunk = backend.transcript_store.list_chunks(job.source_id, source_revision=job.source_revision)[0]
    ref = (EvidenceRef(kind="transcript", chunk_index=chunk.chunk_index, content_sha256=chunk.content_sha256)
           if basis == "transcript" else EvidenceRef(
               kind="user_statement", exchange_index=1, role="user",
               content_sha256=render_distill_exchange_windows(rendering, [1])[0]["content_sha256"],
           ))
    if basis == "transcript" and ref_shape == "exchange":
        ref = EvidenceRef(kind="transcript", exchange_index=1,
            content_sha256=render_distill_exchange_windows(rendering, [1])[0]["content_sha256"])
    candidate, _ = await admit_separated_candidate(
        backend, candidate_id=name, project_name=PROJECT, candidate_type="memory",
        statement=statement or user_text, distill_job_id=job.id, evidence_basis=basis,
        verification_outcome="verified", verification_refs=[ref],
        assimilation_disposition=disposition, assimilation_reason=REASON,
        canonical_title="Source preservation", topic_path=["Review boundaries"],
    )
    return candidate, job


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["no_write", "reject"])
async def test_exchange_transcript_ref_can_close_only_non_promotion(backend, disposition):
    candidate, _ = await _candidate(backend, disposition=disposition, ref_shape="exchange")
    plan = await _plan(backend, candidate.id)
    evidence = (await backend.structured_store.knowledge_store.list_evidence(candidate.id))[0]
    assert plan["points"][0]["disposition"] == disposition, evidence.verification_reason_codes
    assert plan["points"][0]["answer_status"] == "NOT_APPLICABLE"
    result = await _apply(backend, plan)
    assert result["promoted"] == 0
    assert await backend.structured_store.knowledge_store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_exchange_transcript_ref_and_semantic_tags_cannot_bypass_truth_gate(backend):
    candidate, _ = await _candidate(backend, disposition="add", ref_shape="exchange")
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    evidence.verification_outcome = "verified"
    evidence.verification_reason_codes += [
        "semantic_support_verified", "future_utility_verified", "source_statement_verified",
    ]
    await store.save_evidence(evidence)
    plan = await _plan(backend, candidate.id)
    assert plan["points"][0]["answer_status"] == "PARTIAL"
    assert plan["points"][0]["disposition"] == "defer"
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["changed_digest", "ambiguous_location"])
async def test_exchange_transcript_non_promotion_checks_exact_reference(backend, fault):
    candidate, _ = await _candidate(backend, ref_shape="exchange")
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    if fault == "changed_digest":
        evidence.verification_refs[0].content_sha256 = "0" * 64
    else:
        evidence.verification_refs[0].chunk_index = 0
    await store.save_evidence(evidence)
    plan = await _plan(backend, candidate.id)
    assert plan["points"][0]["answer_status"] != "NOT_APPLICABLE"
    assert plan["points"][0]["disposition"] == (
        "reject" if fault == "changed_digest" else "defer"
    )
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_qualified_user_choice_retains_the_attributed_alternative(backend):
    qualified = (
        "Raven 输出默认预演；助手建议改成默认执行并明确该建议尚未批准，"
        "该备选不替代用户决定。"
    )
    candidate, _ = await _candidate(
        backend, disposition="add", basis="user_statement", user_text="Raven 输出默认预演。",
        assistant_text="建议改成默认执行，但这个建议尚未批准。", statement=qualified,
    )
    plan = await _plan(backend, candidate.id)
    assert plan["points"][0]["answer_status"] == "ANSWERED"
    result = await _apply(backend, plan)
    assert result["promoted"] == 1
    entries = await backend.structured_store.knowledge_store.list_entries(PROJECT)
    assert len(entries) == 1 and entries[0].statement == qualified
    evidence = (await backend.structured_store.knowledge_store.list_evidence(candidate.id))[0]
    assert evidence.evidence_basis == "user_statement"
    assert evidence.verification_refs[0].role == "user"
    # This tests representation/source binding, not an LLM's semantic judgment.
    # The current choice is user-authored; the alternative remains explicitly
    # assistant-authored. Standalone transcript promotion stays blocked above.


async def _plan(backend, *candidate_ids):
    return await prepare_interactive_assimilation(
        backend, project_name=PROJECT, project_root="", candidate_ids=candidate_ids,
    )


async def _apply(backend, plan):
    return await apply_separated_assimilation(
        backend, project_name=PROJECT, project_root="",
        candidate_ids=plan["candidate_ids"], plan=plan,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition,final_status,count", [
    ("no_write", "assimilated", "no_write"), ("reject", "rejected", "rejected"),
])
async def test_explicit_non_promoting_transcript_decision_finishes_without_knowledge(
    backend, disposition, final_status, count,
):
    candidate, _ = await _candidate(backend, disposition=disposition)
    plan = await _plan(backend, candidate.id)

    # Regression: valid raw refs + explicit no_write/reject used to become defer.
    assert plan["points"][0]["disposition"] == disposition
    assert plan["points"][0]["answer_status"] == "NOT_APPLICABLE"
    assert plan["provider_candidate_ids"] == []
    result = await _apply(backend, plan)
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    assert result[count] == 1
    assert result["promoted"] == result["deferred"] == result["conflict"] == 0
    assert result["points"][0]["answer_status"] == "NOT_APPLICABLE"
    assert not result["points"][0]["canonical_truth_ids"]
    assert result["points"][0]["handoff_id"] is None
    assert (await store.get_candidate(candidate.id)).status == final_status
    assert evidence.verification_outcome == "not_applicable"
    assert "transcript_refs_current" in evidence.verification_reason_codes
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["no_write", "reject"])
@pytest.mark.parametrize("fault", ["missing_ref", "changed_ref", "missing_job", "missing_revision", "damaged_raw", "damaged_chunk"])
async def test_non_promoting_decision_still_requires_complete_current_sources(backend, disposition, fault):
    candidate, job = await _candidate(backend, disposition=disposition)
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    if fault == "missing_ref":
        evidence.verification_refs = []
        await store.save_evidence(evidence)
    elif fault == "changed_ref":
        evidence.verification_refs[0].content_sha256 = "0" * 64
        await store.save_evidence(evidence)
    elif fault == "missing_job":
        evidence.distill_job_id = "not-a-real-job"
        await store.save_evidence(evidence)
    else:
        # Damage only this isolated test store; never touch frozen/live evidence.
        with sqlite3.connect(backend.transcript_store.db_path) as db:
            if fault == "missing_revision":
                db.execute("DELETE FROM transcript_source_revisions WHERE source_id=?", (job.source_id,))
            elif fault == "damaged_raw":
                db.execute("UPDATE transcript_source_revisions SET raw_bytes=? WHERE source_id=?",
                           (b"changed without a matching digest", job.source_id))
            else:
                row = db.execute("SELECT id,data FROM transcript_chunks WHERE source_id=?", (job.source_id,)).fetchone()
                value = json.loads(row[1])
                value["raw_content"] = "Changed raw body with the old chunk digest."
                db.execute("UPDATE transcript_chunks SET data=? WHERE id=?", (json.dumps(value), row[0]))
    plan = await _plan(backend, candidate.id)
    point = plan["points"][0]
    assert point["answer_status"] in {"PARTIAL", "UNANSWERED", "STALE"}
    assert point["answer_status"] != "NOT_APPLICABLE"
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["add", "refine", "replace", "confirm"])
async def test_transcript_truth_writes_and_confirmation_are_still_blocked(backend, disposition):
    candidate, _ = await _candidate(backend, disposition=disposition)
    result = await _apply(backend, await _plan(backend, candidate.id))
    assert result["deferred"] == 1
    assert result["points"][0]["answer_status"] == "PARTIAL"
    assert result["promoted"] == result["confirmed"] == 0
    assert await backend.structured_store.knowledge_store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_trusted_user_statement_write_is_unchanged(backend):
    candidate, _ = await _candidate(backend, disposition="add", basis="user_statement")
    result = await _apply(backend, await _plan(backend, candidate.id))
    entries = await backend.structured_store.knowledge_store.list_entries(PROJECT)
    assert result["promoted"] == 1
    assert result["points"][0]["answer_status"] == "ANSWERED"
    assert len(entries) == 1 and entries[0].statement == STATEMENT


@pytest.mark.asyncio
async def test_non_promotion_does_not_close_other_work_or_historical_handoffs(backend):
    closed, job = await _candidate(backend)
    unresolved, _ = await _candidate(backend, name="unresolved", disposition="defer")
    handoff = TaskHandoff(project_name=PROJECT, task_id="old-unfinished-task",
                          summary="The missing-label follow-up is not resolved.", status="pending",
                          context={"distill_job_id": job.id})
    await backend.structured_store.save_task_handoff(handoff)
    result = await _apply(backend, await _plan(backend, closed.id, unresolved.id))
    assert result["no_write"] == 1
    assert result["deferred"] == 1
    assert (await backend.structured_store.get_task_handoff(handoff.id)).status == "pending"
    assert await backend.structured_store.knowledge_store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_damaged_source_between_prepare_and_apply_cannot_use_cached_non_promotion(backend):
    candidate, _ = await _candidate(backend)
    plan = await _plan(backend, candidate.id)
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    evidence.verification_refs[0].content_sha256 = hashlib.sha256(b"different source").hexdigest()
    await store.save_evidence(evidence)
    with pytest.raises(ValueError, match="Answer Gate|eligible"):
        await _apply(backend, plan)
    assert (await store.get_candidate(candidate.id)).status == "pending"
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_not_applicable_transcript_cannot_later_be_written_through_review(backend):
    candidate, _ = await _candidate(backend)
    # Keep the candidate pending to challenge a second, writing consumer.
    await _plan(backend, candidate.id)
    with pytest.raises(ValueError, match="requires verified evidence"):
        await resolve_separated_review(backend, candidate_id=candidate.id,
                                       disposition="add", reason="Attempt to turn non-promotion into truth.",
                                       knowledge_items=[{"title": "Forged", "statement": STATEMENT,
                                                         "topic_path": ["Policies"]}])
    assert await backend.structured_store.knowledge_store.list_entries(PROJECT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["add", "refine", "replace", "confirm"])
async def test_caller_cannot_change_an_automatic_non_promotion_into_a_write(backend, disposition):
    candidate, _ = await _candidate(backend)
    plan = await _plan(backend, candidate.id)
    plan["points"][0]["disposition"] = disposition
    plan["points"][0]["knowledge_items"] = [{"title": "Forged", "statement": STATEMENT,
                                             "topic_path": ["Policies"]}]
    with pytest.raises(ValueError, match="Answer Gate"):
        await _apply(backend, plan)
    assert await backend.structured_store.knowledge_store.list_entries(PROJECT) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_reason", "short_reason", "truth_ids", "truth_selections", "conflict", "contradicted"])
async def test_non_promotion_requires_an_explicit_unambiguous_discard(backend, fault):
    candidate, _ = await _candidate(backend)
    store = backend.structured_store.knowledge_store
    if fault == "missing_reason":
        candidate.assimilation_reason = None
    elif fault == "short_reason":
        candidate.assimilation_reason = "skip"
    elif fault == "truth_ids":
        candidate.assimilation_target_ids = ["an-existing-truth-target"]
    elif fault == "truth_selections":
        candidate.assimilation_targets = [{"title": "Do not erase this dependency"}]
    elif fault == "conflict":
        candidate.status = "conflict"
    else:
        evidence = (await store.list_evidence(candidate.id))[0]
        evidence.verification_outcome = "contradicted"
        evidence.verification_reason_codes = ["claim_conflicts"]
        await store.save_evidence(evidence)
    await store.save_candidate(candidate)
    plan = await _plan(backend, candidate.id)
    assert plan["points"][0]["answer_status"] in {"PARTIAL", "CONTRADICTED"}
    assert plan["points"][0]["disposition"] != "no_write"
    assert await store.list_entries(PROJECT) == []


@pytest.mark.asyncio
async def test_legacy_scope_reason_cannot_hide_missing_references(backend):
    candidate, _ = await _candidate(backend)
    store = backend.structured_store.knowledge_store
    evidence = (await store.list_evidence(candidate.id))[0]
    evidence.verification_refs = []
    evidence.verification_reason_codes = ["session_only_not_durable"]
    await store.save_evidence(evidence)
    point = (await _plan(backend, candidate.id))["points"][0]
    assert point["answer_status"] == "UNANSWERED"
    assert point["disposition"] == "defer"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_other_chunk", "damaged_other_chunk"])
async def test_valid_cited_chunk_does_not_replace_complete_source_validation(backend, fault):
    candidate, job = await _candidate(backend, padding="x" * 40_000)
    chunks = backend.transcript_store.list_chunks(job.source_id, source_revision=job.source_revision)
    assert len(chunks) > 1
    assert (await backend.structured_store.knowledge_store.list_evidence(candidate.id))[0].verification_refs[0].chunk_index == 0
    with sqlite3.connect(backend.transcript_store.db_path) as db:
        if fault == "missing_other_chunk":
            db.execute("DELETE FROM transcript_chunks WHERE id=?", (chunks[-1].id,))
        else:
            value = chunks[-1].to_dict()
            value["raw_content"] = "Changed uncited chunk."
            db.execute("UPDATE transcript_chunks SET data=? WHERE id=?", (json.dumps(value), chunks[-1].id))
    point = (await _plan(backend, candidate.id))["points"][0]
    assert point["answer_status"] == "PARTIAL"
    assert point["disposition"] == "defer"
