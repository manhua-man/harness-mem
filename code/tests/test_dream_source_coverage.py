"""Applied-group coverage recovery uses isolated native-shaped fixtures only."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_stage4_contract import _result
from harness_mem.autonomous.models import AutonomousDecision, AssimilationDecision, CandidateVerificationDecision
from harness_mem.autonomous.models import NativeSourceCoverageExtractionDecision, NativeSourceCoverageVerificationDecision
from harness_mem.autonomous.provider import (
    expand_agent_extraction_decision, expand_source_coverage_verification_decision,
    source_coverage_inventory_enabled,
)
from harness_mem.commands.dream import _scope_fingerprint, dream_once
from harness_mem.commands.dream_source_coverage import run_applied_source_coverage
from harness_mem.core.schemas.knowledge import AssimilationDecision as StoredDecision, KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.dream_run import DreamItem, DreamRun
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.session_distill import SessionDistillJob


def run(value):
    return asyncio.run(value)


@pytest.fixture
def coverage(captured):
    backend, root, snapshot, rendering, sources = captured
    source = snapshot.source
    job = SessionDistillJob(id="completed-original", idempotency_key="completed-original",
        project_name="demo", project_root=str(root), client=source.client, session_id=source.session_id,
        source_id=source.id, source_revision=source.source_revision, status="completed", phase="done",
        expected_chunk_count=source.chunk_count, completed_chunk_count=source.chunk_count,
        structural_audit={"coverage": "complete", "expected_chunks": source.chunk_count,
                          "completed_chunks": source.chunk_count},
        completion_disposition="promoted", promotion_summary={"readback": {
            "verified": True, "source_revision": source.source_revision}})
    ledger = backend.transcript_store
    with ledger._lock:
        ledger._distill._upsert_job_locked(job)
        ledger._conn.commit()
    entry = KnowledgeEntry(id="narrow-successor", project_name="demo", module_path=["daily-entry"],
                           title="Daily entry rule", statement="Preserve explicit corrections.")
    store = backend.structured_store.knowledge_store
    fixture = KnowledgeCandidate(id="fixture", project_name="demo", candidate_type="memory", statement="Fixture.")
    refs = [ProjectKnowledgeSourceRef(label="Original user", target=value.locator,
                                     kind=value.source_kind, digest=value.content_sha256) for value in sources]
    run(store.save_candidate(fixture))
    run(store.apply_current_change(candidate_before=fixture, candidate_after=fixture.model_copy(update={"status": "assimilated"}),
        decision=StoredDecision(id="fixture-publish", project_name="demo", candidate_id=fixture.id,
            disposition="add", canonical_truth_ids=[entry.id], reason="Isolated fixture."),
        added_entries=[entry], predecessor_entries=[], source_refs_by_entry={entry.id: refs}))
    run(store.cleanup_candidate(fixture.id))
    other = KnowledgeCandidate(id="unrelated-pending", project_name="demo", candidate_type="memory",
                               statement="Do not retire this pending candidate.")
    run(store.save_candidate(other))
    from harness_mem.core.schemas.knowledge import KnowledgeEvidence
    run(store.save_evidence(KnowledgeEvidence(project_name="demo", candidate_id=other.id,
        distill_job_id=job.id, evidence_basis="transcript", verification_outcome="unverified")))
    item = DreamItem(source_kind="knowledge_stale", source_id="retired-predecessor",
        proposed_action="replace", final_action="applied", reason="An earlier narrowed replacement.",
        result={"truth_change": "refine", "truth_ids": [entry.id]})
    checkpoint = {"target_ids": [item.source_id], "slice_count": 4, "max_slices": 24,
                  "completed_signal_indexes": [0], "verification": {},
                  "maintenance_scope": {"trigger_id": "original-trigger", "dispatch_generation": "original-generation"}}
    notes = ["dream target snapshots: " + json.dumps([{"entry_id": item.source_id, "fingerprint": "a" * 64}])]
    return backend, root, job, entry, item, checkpoint, notes


class CoverageProvider:
    name = "source-coverage-fixture"
    def __init__(self, *, final_failure=False, role="user", no_candidate=False, confirm=False):
        self.calls, self.bindings = [], []
        self.final_failure, self.role = final_failure, role
        self.no_candidate, self.confirm = no_candidate, confirm
        self.task_budget_binding = object()

    def bind_task_budget(self, binding, **kwargs):
        assert binding is self.task_budget_binding
        self.bindings.append(kwargs)

    def extraction_decision(self, manifest, review, points):
        """Exercise the same typed transport expansion as the native provider."""
        if not source_coverage_inventory_enabled(manifest):
            return AutonomousDecision.model_validate({"semantic_review": review, "candidates": points})
        windows = manifest["source_coverage"]["inventory_input"]["windows"]
        compact = [{"kind": point["kind"], "statement": point["content"],
            "evidence_basis": point["evidence_basis"], "exchange_indexes": [
                ref["exchange_index"] for ref in point["verification_refs"]]} for point in points]
        inventory = self.source_inventory(windows, compact)
        native = NativeSourceCoverageExtractionDecision.model_validate({
            "review": {"summary": review["session_summary"], "final_request": review["final_user_request"],
                "actual_result": review["final_outcome"], "contradictions": [], "unfinished": [],
                "no_candidate_reason": "The complete isolated source has no omitted durable claim." if not points else None},
            "points": compact, "inventory": inventory})
        decision = expand_agent_extraction_decision(native, manifest=manifest)
        if self.role != "user":
            # A corrupt fake result still crosses the actual production gate.
            for candidate in decision.candidates:
                for ref in candidate.verification_refs:
                    ref.role = self.role
        return decision

    def source_inventory(self, windows, points):
        inventory = []
        for index, window in enumerate(windows):
            links = [i for i, point in enumerate(points) if window["exchange_index"] in point["exchange_indexes"]]
            inventory.append({"w": index, "spans": [{"s": 0, "e": len(window["text"]),
                "d": "extract" if links else "temporary", "p": links}]})
        return inventory

    def decide(self, manifest, **kwargs):
        kwargs["heartbeat"]()
        self.calls.append("decide")
        scope = manifest["candidate_validation_feedback"]["source_coverage"]
        assert scope["current_successors"][0]["statement"] == "Preserve explicit corrections."
        assert "permanent" in scope["instruction"]
        assert len(manifest["semantic_decision_exchanges"]) == 78
        window = next(row for row in manifest["semantic_decision_exchanges"] if row["exchange_index"] == 47)
        assert "do not add acceptance rituals" in window["content"]
        review = {"session_summary": "Review the original source for a scoped missing daily-entry constraint.",
                  "final_user_request": "Repair the daily entry.", "final_outcome": "Source coverage reviewed.",
                  "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
                  "evidence_status": "answered", "promotion_decision": "promote"}
        if self.no_candidate:
            review.update(promotion_decision="no_promotion", evidence_status="not_applicable",
                          zero_candidate_challenge=manifest["zero_candidate_challenge_template"])
        points = [] if self.no_candidate else [{"kind": "memory", "category": "knowledge", "confidence": .8,
            "content": "During this daily-entry repair, do not add acceptance rituals.",
            "evidence_basis": "user_statement", "verification_refs": [{"kind": "user_statement", "role": self.role,
                "exchange_index": 47, "content_sha256": window["content_sha256"]}]}]
        return _result(self.extraction_decision(manifest, review, points))

    def verify(self, manifest, **kwargs):
        kwargs["heartbeat"]()
        final = manifest["contract_version"] == "final-knowledge-scope-v1"
        self.calls.append("final_verify" if final else "candidate_verify")
        if not final:
            assert manifest["source_coverage"]["predecessor_text_available"] is False
        else:
            assert any(row.get("kind") == "runtime_maintenance_scope_not_source_evidence"
                       for row in manifest["session_context"])
        points = []
        for row in manifest["candidates"]:
            text = row.get("scope_text", row["statement"])
            points.append({"candidate_index": row["candidate_index"],
                "semantic_support": "unsupported" if final and self.final_failure else "supported",
                "future_scope": "durable", "source_use": "standing_decision",
                "reason": "Exact original source supports the scoped independent omitted requirement.",
                "scope_segments": [{"text": text, "source_use": "standing_decision", "future_scope": "durable",
                    "standalone": True, "content_role": "claim", "source_support":
                    "unsupported" if final and self.final_failure else "supported"}]})
        if not final and source_coverage_inventory_enabled(manifest):
            inventory = manifest["source_coverage"]["inventory"]
            native = NativeSourceCoverageVerificationDecision.model_validate({"points": points,
                "audit": [{"w": row["w"], "span_index": index, "verdict": "supported"}
                    for row in inventory["windows"] for index in range(len(row["spans"]))]})
            return _result(expand_source_coverage_verification_decision(native, manifest=manifest))
        return _result(CandidateVerificationDecision.model_validate({"points": points}))

    def assimilate(self, manifest, **kwargs):
        kwargs["heartbeat"]()
        self.calls.append("assimilate")
        candidate = manifest["verified_candidates"][0]
        return _result(AssimilationDecision.model_validate({"points": [{
            "candidate_id": candidate["candidate_id"], "disposition": "confirm" if self.confirm else "add",
            "matched_truth_handles": [manifest["current_truth"][0]["handle"]] if self.confirm else [],
            "knowledge_items": [] if self.confirm else [{"title": "Scoped daily-entry repair",
                "statement": "During this daily-entry repair, do not add acceptance rituals.",
                "topic_path": ["daily-entry"], "claim_kind": "design_requirement"}],
            "reason": "Keep this original scoped constraint independently of the valid narrow rule."}]}))


async def _cover(data, provider, *, boundary=None):
    backend, root, _job, _entry, item, checkpoint, notes = data
    async def persist():
        pass
    return await run_applied_source_coverage(backend, project_name="demo", project_root=root,
        run_id="original-run", checkpoint=checkpoint, notes=notes, items=[item], provider=provider,
        persist=persist, boundary=boundary)


def test_fully_durable_successor_still_extracts_missing_original_source_claim(coverage):
    backend, root, job, entry, item, checkpoint, notes = coverage
    provider = CoverageProvider()
    job_before = job.to_dict()
    pending_before = run(backend.structured_store.knowledge_store.get_candidate("unrelated-pending")).to_dict()
    assert run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"], checkpoint["source_coverage"]
    rows = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert {row.statement for row in rows} == {entry.statement, "During this daily-entry repair, do not add acceptance rituals."}
    assert checkpoint["source_coverage"][item.source_id]["status"] == "applied"
    assert checkpoint["target_ids"] == [item.source_id] and checkpoint["completed_signal_indexes"] == [0]
    assert checkpoint["maintenance_scope"]["dispatch_generation"] == "original-generation"
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    assert run(backend.structured_store.knowledge_store.get_candidate("unrelated-pending")).to_dict() == pending_before
    assert all(row["phase"] == "dream" for row in provider.bindings)
    assert all(row["slice_id"].startswith("source-coverage:original-run:") for row in provider.bindings[:-1])
    assert not any(row["slice_id"].startswith("source-decide:") for row in provider.bindings)
    metadata = json.dumps(checkpoint)
    assert "acceptance rituals" not in metadata and entry.statement not in metadata
    calls = list(provider.calls)
    assert run(_cover(coverage, provider)) is False
    assert provider.calls == calls


@pytest.mark.parametrize("failure", ("final", "role", "source", "root", "receipt"))
def test_scope_role_source_and_independent_final_failure_never_restore(coverage, monkeypatch, failure):
    backend, root, job, entry, item, checkpoint, _notes = coverage
    provider = CoverageProvider(final_failure=failure == "final", role="assistant" if failure == "role" else "user")
    if failure == "source":
        monkeypatch.setattr(backend.transcript_store, "reconstruct_raw", lambda *_a, **_k: b"changed")
    elif failure == "root":
        real = backend.transcript_store.get_revision
        monkeypatch.setattr(backend.transcript_store, "get_revision", lambda *a, **k: real(*a, **k).model_copy(update={"project_root": str(root / "wrong")}))
    elif failure == "receipt":
        real = backend.transcript_store.list_distill_jobs
        monkeypatch.setattr(backend.transcript_store, "list_distill_jobs", lambda **k: [row.model_copy(update={"structural_audit": {}}) for row in real(**k)])
    if failure == "role":
        from harness_mem.autonomous.provider import ProviderError
        with pytest.raises(ProviderError):
            run(_cover(coverage, provider))
    else:
        run(_cover(coverage, provider))
    rows = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [(row.id, row.statement) for row in rows] == [(entry.id, entry.statement)]
    assert checkpoint["source_coverage"][item.source_id]["status"] in {"failed", "no_write"}


@pytest.mark.parametrize("mode", ("no_candidate", "confirm"))
def test_no_candidate_or_confirmation_does_not_claim_missing_constraint_repaired(coverage, mode):
    provider = CoverageProvider(**{mode: True})
    run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert state["status"] == "no_write"
    assert "acceptance rituals" not in json.dumps(state)


def test_candidate_checkpoint_slice_resumes_without_reextracting_or_retiring_old_pending(coverage):
    class Slice(Exception):
        pass
    count = [0]
    async def boundary():
        count[0] += 1
        if count[0] == 2:
            raise Slice()
    provider = CoverageProvider()
    with pytest.raises(Slice):
        run(_cover(coverage, provider, boundary=boundary))
    assert provider.calls == ["decide", "candidate_verify"]
    assert coverage[-2]["source_coverage"][coverage[4].source_id]["status"] == "candidates_verified"
    run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"], coverage[-2]["source_coverage"][coverage[4].source_id].get("reason_code")
    assert coverage[-2]["source_coverage"][coverage[4].source_id]["status"] == "applied"


def test_original_run_manifest_processed_counts_and_account_survive_coverage(coverage):
    backend, root, _job, entry, item, checkpoint, notes = coverage
    original_ids = [item.source_id] + [f"untouched-{index}" for index in range(22)]
    checkpoint.update(version="dream-slices-v3", target_ids=original_ids, max_slices=24,
        signals=[{"kind": "stale", "target_ids": original_ids, "proposed_action": "replace", "risk": "medium", "reason": "Original frozen group."}],
        completed_signal_indexes=[0], unresolved_scope={}, unresolved_fingerprints={})
    old = DreamRun(id="original-run", project_name="demo", status="continuing",
                  started_at=datetime.now(timezone.utc), items=[item], notes=notes, continuation=checkpoint)
    run(backend.structured_store.save_dream_run(old))
    provider = CoverageProvider()
    provider.bind_task_budget = None
    provider.task_budget_binding = None
    result = run(dream_once(backend, project_name="demo", project_root=root, source="agent",
                          semantic_provider=provider, resume_run_id=old.id))
    assert result.id == old.id and result.continuation["target_ids"] == original_ids
    assert result.continuation["completed_signal_indexes"] == [0]
    assert len(result.items) == 1 and result.items[0].source_id == item.source_id
    assert result.handling_summary["processed"] == 1
    assert result.continuation["maintenance_scope"] == checkpoint["maintenance_scope"]
    assert result.continuation["source_coverage"][item.source_id]["status"] == "applied"
    assert result.continuation["max_slices"] == 24
    assert _scope_fingerprint(run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo"))) == _scope_fingerprint(entry)


def test_crash_after_truth_commit_recovers_readback_without_another_model_or_write(coverage, monkeypatch):
    import harness_mem.commands.separated_assimilation as owner
    real_apply = owner.apply_separated_assimilation
    class CommittedCrash(Exception):
        pass
    async def crash(*args, **kwargs):
        await real_apply(*args, **kwargs)
        raise CommittedCrash()
    monkeypatch.setattr(owner, "apply_separated_assimilation", crash)
    provider = CoverageProvider()
    with pytest.raises(CommittedCrash):
        run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert state["status"] == "committing"
    assert state["commit_bindings"]
    before = list(provider.calls)
    monkeypatch.setattr(owner, "apply_separated_assimilation", lambda *a, **k: pytest.fail("committed action was replayed"))
    assert run(_cover(coverage, provider))
    assert state["status"] == "applied" and state["reason_code"] == "source_coverage_commit_recovered"
    assert provider.calls == before
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 2


def test_partial_final_failure_is_not_washed_out_by_one_committed_claim(coverage):
    class Partial(CoverageProvider):
        def decide(self, manifest, **kwargs):
            result = super().decide(manifest, **kwargs)
            first = result.decision.candidates[0]
            second = first.model_copy(update={"content": "During this daily-entry repair, preserve explicit corrections."})
            decision = self.extraction_decision(manifest, result.decision.semantic_review.model_dump(mode="json"),
                [first.model_dump(mode="json"), second.model_dump(mode="json")])
            return _result(decision)

        def assimilate(self, manifest, **kwargs):
            result = super().assimilate(manifest, **kwargs)
            first = result.decision.points[0]
            second = first.model_copy(update={"candidate_id": manifest["verified_candidates"][1]["candidate_id"],
                "knowledge_items": [first.knowledge_items[0].model_copy(update={
                    "title": "Scoped correction wording", "statement": "During this daily-entry repair, preserve explicit corrections."})]})
            return _result(result.decision.model_copy(update={"points": [first, second]}))

        def verify(self, manifest, **kwargs):
            result = super().verify(manifest, **kwargs)
            if manifest["contract_version"] != "final-knowledge-scope-v1":
                return result
            second = result.decision.points[1]
            rejected = second.model_copy(update={"semantic_support": "partial", "future_scope": "unclear",
                "source_use": "unclear", "scope_segments": [second.scope_segments[0].model_copy(update={
                    "future_scope": "unclear", "source_use": "unclear", "source_support": "unsupported"})]})
            return _result(result.decision.model_copy(update={"points": [result.decision.points[0], rejected]}))
    provider = Partial()
    run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert state["status"] == "unresolved"
    assert {row["status"] for row in state["candidate_outcomes"]} == {"assimilated", "deferred"}
    assert len(state["commit_bindings"]) == 1 and state["commit_bindings"][0]["status"] == "applied"
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 2
    calls = list(provider.calls)
    assert run(_cover(coverage, provider)) is False
    assert provider.calls == calls


def test_unknown_usage_failure_stops_original_attempt_without_new_account_or_retry(coverage):
    from harness_mem.autonomous.provider import ProviderError
    class Unknown(CoverageProvider):
        def verify(self, manifest, **kwargs):
            self.calls.append("unknown_candidate_verify")
            raise ProviderError("Fixture invocation has unknown usage", kind="unrecoverable",
                                failure_reason="remaining_not_demonstrable")
    provider = Unknown()
    binding = provider.task_budget_binding
    with pytest.raises(ProviderError):
        run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert state["status"] == "failed" and state["reason_code"] == "remaining_not_demonstrable"
    assert provider.task_budget_binding is binding
    assert provider.calls == ["decide", "unknown_candidate_verify"]
    assert run(_cover(coverage, provider)) is False
    assert provider.calls == ["decide", "unknown_candidate_verify"]
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 1


@pytest.mark.parametrize("change", ("update", "delete"))
def test_add_guard_checks_bound_successor_in_same_canonical_transaction(coverage, monkeypatch, change):
    backend, _root, _job, entry, item, checkpoint, _notes = coverage
    structured = backend.structured_store
    real = structured.apply_canonical_payload_transaction
    raced = []
    def race(*, idempotency_key, mutations):
        if not raced and any(row["collection"] == "knowledge_entries" and row["operation"] == "upsert"
                             and row["entity_id"] != entry.id for row in mutations):
            raced.append(True)
            concurrent = {"operation": "delete" if change == "delete" else "upsert",
                "collection": "knowledge_entries", "entity_id": entry.id, "project_name": "demo",
                "expected_sha256": structured.record_payload_sha256("knowledge_entries", entry.id)}
            if change == "update":
                concurrent["payload"] = entry.model_copy(update={"statement": "A concurrent owner changed this rule."}).to_dict()
            real(idempotency_key="independent-concurrent-owner", mutations=[concurrent])
            # The check is inside this exact canonical transaction, not merely
            # in worker.unchanged() or a preflight read in apply_current_change.
            assert any(row["operation"] == "assert" and row["entity_id"] == entry.id for row in mutations)
        return real(idempotency_key=idempotency_key, mutations=mutations)
    monkeypatch.setattr(structured, "apply_canonical_payload_transaction", race)
    run(_cover(coverage, CoverageProvider()))
    assert raced
    rows = run(structured.knowledge_store.list_entries("demo"))
    assert [row.statement for row in rows] == ([] if change == "delete" else ["A concurrent owner changed this rule."])
    state = checkpoint["source_coverage"][item.source_id]
    assert state["status"] == "failed"
    assert state["reason_code"] == "source_coverage_context_changed_before_commit"
