"""Isolated handoff continuation contracts; no model or installed store access."""
from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from harness_mem.commands import source_handoff_recovery as owner
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEvidence
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.core.schemas.task_handoff import TaskHandoff
from test_dream_source_coverage import coverage as coverage
from test_dream_complete_user_context import captured as captured
from test_dream_stage4_contract import _result


def run(value):
    return asyncio.run(value)


class Value(SimpleNamespace):
    def to_dict(self):
        return {key: value for key, value in vars(self).items() if key != "to_dict"}


class Canonical:
    def __init__(self):
        self.rows = {}
        self.transactions = {}

    def get_payload_json(self, collection, identity):
        value = self.rows.get((collection, identity))
        return json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else None

    def get_payload(self, collection, identity):
        return self.rows.get((collection, identity))

    def apply_payload_transaction(self, *, idempotency_key, mutations):
        from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
        for mutation in mutations:
            raw = self.get_payload_json(mutation["collection"], mutation["entity_id"])
            actual = hashlib.sha256(raw.encode()).hexdigest() if raw else None
            if actual != mutation["expected_sha256"]:
                raise CanonicalTransactionPreconditionError("Isolated fixture payload changed.")
        applied = []
        for mutation in mutations:
            if mutation["operation"] == "upsert":
                self.rows[mutation["collection"], mutation["entity_id"]] = mutation["payload"]
                raw = json.dumps(mutation["payload"], ensure_ascii=False, sort_keys=True)
                applied.append({"operation": "upsert", "collection": mutation["collection"],
                    "entity_id": mutation["entity_id"], "payload_sha256": hashlib.sha256(raw.encode()).hexdigest()})
        result = {"idempotency_key": idempotency_key, "mutations": applied}
        self.transactions[idempotency_key] = result
        return result

    def payload_transaction_result(self, key):
        return self.transactions.get(key)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    project, source_id, revision_id = "demo", "source", "sha256:" + "a" * 64
    scope = {"trigger_id": "session", "dispatch_generation": "original-generation"}
    report = SourceReport(speaker="assistant", period="2026-10-20", session_id="session",
        source_id=source_id, source_revision=revision_id, exchange_indexes=[1],
        text="The assistant described a reusable mechanism and retained its limits.")
    old = str(uuid5(NAMESPACE_URL,
        f"harness-mem:autonomous-knowledge-candidate:job:1:memory:{report.text}"))
    handoff = TaskHandoff(id="handoff", project_name=project, task_id="assimilation:" + old,
        summary=report.render_statement(), context={"candidate_id": old, "distill_job_id": "job",
                                                   "source_report": report.model_dump(mode="json")})
    refs = [{"kind": "source_report", "role": "assistant", "exchange_index": 1,
             "content_sha256": "b" * 64}]
    job = Value(id="job", status="completed", project_name=project, project_root=str(tmp_path),
        client="codex", session_id="session", source_id=source_id, source_revision=revision_id,
        expected_chunk_count=1, completed_chunk_count=1, output_candidate_ids=[old],
        promotion_summary={"readback": {"verified": True, "source_revision": revision_id},
            "points": [{"candidate_id": old, "disposition": "handoff", "handoff_id": handoff.id,
                "verification_outcome": "verified", "answer_status": "ANSWERED", "verification_refs": refs}]})
    origin = Value(id="origin", project_name=project, status="failed", completed_at="then",
        notes=["Hook session distill succeeded: job"], continuation={"maintenance_scope": scope})
    revision = Value(session_id="session", client="codex", project_root=str(tmp_path), raw_sha256="a" * 64)
    candidates, evidence, canonical = {}, {}, Canonical()
    canonical.rows["task_handoffs", handoff.id] = handoff.to_dict()

    async def get_candidate(identity):
        return candidates.get(identity)

    async def list_evidence(identity):
        return evidence.get(identity, [])

    async def list_entries(*args, **kwargs):
        return []

    async def get_run(identity):
        return origin if identity == origin.id else None

    async def get_handoff(identity):
        payload = canonical.get_payload("task_handoffs", identity)
        return TaskHandoff.from_dict(dict(payload)) if payload else None

    store = SimpleNamespace(get_candidate=get_candidate, list_evidence=list_evidence, list_entries=list_entries)
    backend = SimpleNamespace(data_dir=tmp_path,
        transcript_store=SimpleNamespace(get_distill_job=lambda identity: job if identity == job.id else None),
        structured_store=SimpleNamespace(knowledge_store=store, _canonical=canonical,
            get_dream_run=get_run, get_task_handoff=get_handoff))
    account = {"task_scope": owner.maintenance_task_scope("session", "original-generation"), "host_client": "codex",
        "bounds": {"max_calls": 64}, "calls": [{"call_id": "old", "status": "completed", "usage_exact": True, "usage": {"input_tokens": 1, "output_tokens": 1, "duration_seconds": 1.0}}]}
    monkeypatch.setattr(owner, "read_task_budget_receipt", lambda *args: account)
    monkeypatch.setattr(owner, "_source_report_context", lambda *args, **kwargs: (revision, "rendered", b"raw"))
    monkeypatch.setattr(owner, "render_distill_exchange_windows", lambda *args: [
        {"exchange_index": 1, "content_sha256": "b" * 64, "content": "native assistant"}])
    return SimpleNamespace(backend=backend, job=job, origin=origin, report=report, handoff=handoff,
        candidates=candidates, evidence=evidence, canonical=canonical, account=account, root=tmp_path, refs=refs, old=old)


def prepare(fixture, **overrides):
    args = dict(project_name="demo", project_root=fixture.root, run_id="carrier", origin_run_id="origin",
                source_job_id="job", handoff_ids=["handoff"])
    args.update(overrides)
    return run(owner.prepare_source_handoff_recovery(fixture.backend, **args))


def test_freezes_cleaned_report_without_recreating_workspace(fixture):
    manifest = prepare(fixture)
    binding = manifest["binding"]
    assert manifest["contract"] == owner.CONTRACT
    assert manifest["binding_sha256"] == owner._digest(binding)
    assert binding["maintenance_scope"] == fixture.origin.continuation["maintenance_scope"]
    assert binding["task_scope"] == fixture.account["task_scope"]
    assert binding["source_candidates"][0]["original_candidate_id"] == fixture.old
    assert binding["source_candidates"][0]["mode"] == "rehydrate_report"
    assert fixture.report.text not in json.dumps(manifest)
    assert fixture.candidates == {}
    assert fixture.canonical.transactions == {}


def retained(fixture, *, kind="rule"):
    candidate = KnowledgeCandidate(id="retained", project_name="demo", candidate_type=kind,
        statement="When updating：preserve every necessary qualifier.", status="assimilated")
    evidence = KnowledgeEvidence(project_name="demo", candidate_id=candidate.id, distill_job_id="job",
        evidence_basis="user_statement", verification_outcome="verified", verification_refs=[
            {"kind": "user_statement", "role": "user", "exchange_index": 1, "content_sha256": "b" * 64}])
    fixture.candidates[candidate.id], fixture.evidence[candidate.id] = candidate, [evidence]
    fixture.handoff.task_id = "assimilation:" + candidate.id
    fixture.handoff.context = {"candidate_id": candidate.id, "distill_job_id": "job"}
    fixture.handoff.summary = candidate.statement
    fixture.canonical.rows["task_handoffs", "handoff"] = fixture.handoff.to_dict()
    source_binding = {"source_job_id": "job", "source_id": fixture.job.source_id,
                      "source_revision": fixture.job.source_revision}
    fixture.origin.continuation["source_inventory_audit"] = {
        "task_scope": fixture.account["task_scope"], "source_coverage": {"source": {
            "binding": source_binding, "binding_sha256": owner._digest(source_binding),
            "candidate_ids": [candidate.id], "candidate_outcomes": [{"candidate_id": candidate.id,
                "handoff_id": "handoff", "disposition": "handoff", "truth_ids": []}]}}}
    return candidate, evidence


@pytest.mark.parametrize("kind", ["memory", "rule", "relation"])
def test_freezes_exact_retained_workspace_and_never_resets_terminal_candidate(fixture, kind):
    candidate, evidence = retained(fixture, kind=kind)
    manifest = prepare(fixture)
    row = manifest["binding"]["source_candidates"][0]
    assert row["mode"] == "retained_workspace"
    assert row["candidate_sha256"] == owner._digest(candidate.to_dict())
    assert row["evidence_sha256"] == owner._digest([evidence.to_dict()])
    assert candidate.status == "assimilated"


@pytest.mark.parametrize("mutation, error", [
    (lambda f: f.origin.continuation.pop("maintenance_scope"), "maintenance_scope_missing"),
    (lambda f: f.account.update(host_client="other"), "account_changed"),
    (lambda f: f.account["calls"][0].update(usage_exact=False), "usage_unknown_or_active"),
    (lambda f: f.account["calls"][0].update(status="running"), "usage_unknown_or_active"),
    (lambda f: f.job.promotion_summary["readback"].update(verified=False), "source_job_receipt_unproved"),
    (lambda f: f.job.promotion_summary["points"][0].update(verification_outcome="unverified"), "cleaned_candidate_unproved"),
    (lambda f: f.origin.notes.clear(), "origin_source_job_unproved"),
    (lambda f: f.refs[0].update(content_sha256="c" * 64), "report_source_digest_changed"),
    (lambda f: f.job.output_candidate_ids.clear(), "original_ordinal_missing"),
])
def test_preparation_fails_closed(fixture, mutation, error):
    mutation(fixture)
    with pytest.raises(ValueError, match=error):
        prepare(fixture)


def test_selection_is_finite_and_exact(fixture):
    with pytest.raises(ValueError, match="selection_invalid"):
        prepare(fixture, handoff_ids=["handoff", "handoff"])
    with pytest.raises(ValueError, match="carrier_identity_invalid"):
        prepare(fixture, run_id="origin")


def test_original_candidate_id_binds_exact_report_body(fixture):
    payload = fixture.canonical.rows["task_handoffs", "handoff"]
    changed = fixture.report.model_copy(update={"text": "Different plausible report."})
    payload["context"]["source_report"] = changed.model_dump(mode="json")
    payload["summary"] = changed.render_statement()
    with pytest.raises(ValueError, match="original_body_identity_changed"):
        prepare(fixture)


def test_original_account_cross_checks_are_mandatory(fixture):
    fixture.origin.continuation["task_budget"] = {"task_scope": "new-account"}
    with pytest.raises(ValueError, match="origin_account_mismatch"):
        prepare(fixture)


def test_frozen_call_prefix_cannot_be_replaced(fixture):
    manifest = prepare(fixture)
    fixture.account["calls"][0]["call_id"] = "replacement"
    with pytest.raises(ValueError, match="account_prefix_changed"):
        owner._account(fixture.backend, manifest["binding"])


def test_new_known_calls_extend_same_prefix(fixture):
    manifest = prepare(fixture)
    fixture.account["calls"].append({"call_id": "new", "status": "completed", "usage_exact": True, "usage": {"input_tokens": 1, "output_tokens": 1, "duration_seconds": 1.0}})
    assert owner._account(fixture.backend, manifest["binding"]) is fixture.account


def test_provider_adapter_preserves_actual_phase(fixture):
    calls = []
    provider = SimpleNamespace(bind_task_budget=lambda binding, **kwargs: calls.append((binding, kwargs)))
    wrapped = owner._RecoveryProvider(provider, phase="dream", prefix="recovery")
    wrapped.bind_task_budget("same-account", phase="source", slice_id="source-final-scope", retry_of="old")
    assert calls == [("same-account", {"phase": "dream", "slice_id": "recovery:source-final-scope", "retry_of": "old"})]


@pytest.mark.parametrize("status", ["failed", "cancelled", "retried"])
def test_known_terminal_costs_are_preserved_and_do_not_block_recovery(fixture, status):
    fixture.account["calls"][0]["status"] = status
    before = json.loads(json.dumps(fixture.account))
    manifest = prepare(fixture)
    assert owner._account(fixture.backend, manifest["binding"]) == before
    assert fixture.account == before


def test_async_carrier_bridges_thread_saves_and_restores_binding(fixture, monkeypatch):
    manifest = prepare(fixture)
    calls, saves, boundaries = [], [], []
    budget = SimpleNamespace(task_scope=fixture.account["task_scope"], host_client="codex", data_dir=fixture.root)
    provider = SimpleNamespace(task_budget_binding=budget, _budget_phase="dream", _budget_slice="carrier-slice",
        _budget_retry_of=None, _last_budget_call_id="previous",
        bind_task_budget=lambda binding, **kwargs: calls.append((binding, kwargs)))

    def attempt(backend, *, binding, state, provider, heartbeat, save):
        assert not asyncio._get_running_loop()
        heartbeat()
        save({"status": "no_write"})

    monkeypatch.setattr(owner, "_run_attempt", attempt)

    async def persist():
        saves.append(True)

    async def boundary():
        boundaries.append(True)

    checkpoint = {}
    result = run(owner.run_source_handoff_recovery(fixture.backend, project_name="demo",
        project_root=fixture.root, run_id="carrier", manifest=manifest, checkpoint=checkpoint,
        notes=[], provider=provider, persist=persist, boundary=boundary))
    assert result["worked"] is True and result["pending"] is False and result["status"] == "no_write"
    assert len(saves) == 2 and len(boundaries) == 1
    assert calls[-1][0] is budget and calls[-1][1]["slice_id"] == "carrier-slice"
    assert checkpoint["source_handoff_recovery"]["binding"] == manifest["binding"]


def test_close_handoff_checks_canonical_truth_and_is_idempotent(fixture):
    manifest = prepare(fixture)
    row = manifest["binding"]["source_candidates"][0]
    point = {"disposition": "no_write", "point_sha256": "a" * 64, "truth_ids": [], "truth_bindings": []}
    owner._close_handoff(fixture.backend, binding=manifest["binding"], row=row, proofs=[point])
    saved = fixture.canonical.rows["task_handoffs", "handoff"]
    assert saved["status"] == "done"
    assert saved["context"]["source_report"] == fixture.report.model_dump(mode="json")
    owner._close_handoff(fixture.backend, binding=manifest["binding"], row=row, proofs=[point])
    assert len(fixture.canonical.transactions) == 1
    with pytest.raises(ValueError, match="handoff_close_changed"):
        owner._close_handoff(fixture.backend, binding=manifest["binding"], row=row,
                             proofs=[{**point, "disposition": "add"}])


def test_terminal_proof_requires_a_real_terminal_carrier(fixture):
    with pytest.raises(ValueError, match="proof_carrier_not_terminal"):
        run(owner.read_source_handoff_recovery_proof(fixture.backend,
            run_id="not-a-run", origin_run_id="origin", source_job_id="job"))


@pytest.mark.parametrize("kind", ["memory", "rule"])
def test_retained_handoff_uses_real_common_owners_and_canonical_commit(coverage, monkeypatch, kind):
    """Exercise local immutable native fixture, normal admission and SQLite CAS."""
    from datetime import datetime, timezone
    from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
    from harness_mem.commands.knowledge_assimilation import record_assimilation_result
    from harness_mem.commands.separated_assimilation import admit_separated_candidate, _materialize_handoff
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.mcp.distill_projection import render_distill_exchange_windows

    backend, root, job, _entry, _item, _checkpoint, _notes = coverage
    store = backend.structured_store.knowledge_store
    rendering = backend.transcript_store.reconstruct(job.source_id, source_revision=job.source_revision)
    window = render_distill_exchange_windows(rendering, [47])[0]
    statement = "When repairing the daily entry：do not add acceptance rituals."
    old, _replay = run(admit_separated_candidate(backend, candidate_id="old-retained", project_name="demo",
        candidate_type=kind, statement=statement, distill_job_id=job.id, evidence_basis="user_statement",
        verification_outcome="verified", verification_refs=[{"kind": "user_statement", "role": "user",
            "exchange_index": 47, "content_sha256": window["content_sha256"]}],
        verification_reason_codes=["source_use_standing_decision", "future_scope_durable", "source_scope_durable",
                                   "semantic_support_verified", "autonomous_final_scope_required"]))
    point = {"disposition": "handoff", "reason": "Current-target discovery is incomplete; retain this exact source point."}
    run(record_assimilation_result(backend, candidate=old, point=point))
    evidence = run(store.list_evidence(old.id))
    handoff_id = run(_materialize_handoff(backend, candidate=old, evidence=evidence[0], point=point))
    source_binding = {"source_job_id": job.id, "source_id": job.source_id, "source_revision": job.source_revision}
    scope = {"trigger_id": "explicit-fixture", "dispatch_generation": "same-generation"}
    task_scope = owner.maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
    state = {"binding": source_binding, "binding_sha256": owner._digest(source_binding), "candidate_ids": [old.id],
        "candidate_outcomes": [{"candidate_id": old.id, "disposition": "handoff", "handoff_id": handoff_id}]}
    origin = DreamRun(id="failed-original", project_name="demo", trigger_source="agent", status="failed",
        completed_at=datetime.now(timezone.utc), continuation={"maintenance_scope": scope,
            "source_inventory_audit": {"task_scope": task_scope, "source_coverage": {"source": state}}})
    run(backend.structured_store.save_dream_run(origin))
    old_before, origin_before, job_before = old.to_dict(), origin.to_dict(), job.to_dict()
    account = {"task_scope": task_scope, "host_client": "codex", "bounds": {"max_calls": 64},
               "calls": [{"call_id": "original-call", "status": "completed", "usage_exact": True, "usage": {"input_tokens": 1, "output_tokens": 1, "duration_seconds": 1.0}}]}
    monkeypatch.setattr(owner, "read_task_budget_receipt", lambda *args: account)
    manifest = run(owner.prepare_source_handoff_recovery(backend, project_name="demo", project_root=root,
        run_id="recovery", origin_run_id=origin.id, source_job_id=job.id, handoff_ids=[handoff_id]))

    class Provider:
        task_budget_binding = SimpleNamespace(task_scope=task_scope, host_client="codex", data_dir=backend.data_dir)
        _budget_phase, _budget_slice, _budget_retry_of = "dream", "dream:recovery:1", None
        _last_budget_call_id = None

        def __init__(self):
            self.calls = []

        def bind_task_budget(self, *args, **kwargs):
            assert kwargs["phase"] == "dream"

        def decide(self, *args, **kwargs):
            raise AssertionError("Source extraction must not repeat.")

        def assimilate(self, manifest, **kwargs):
            kwargs["heartbeat"]()
            self.calls.append("assimilate")
            assert manifest["current_truth"] == []
            assert any("comparison_current_truth" in value["content"] for value in manifest["session_context"])
            candidate = manifest["verified_candidates"][0]
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": candidate["candidate_id"], "disposition": "add", "matched_truth_handles": [],
                "knowledge_items": [{"title": "Retained exact repair requirement", "statement": statement,
                    "topic_path": ["repair"], "claim_kind": "design_requirement"}],
                "reason": "Keep the source-supported independent requirement with its exact original qualifier."}]}))

        def verify(self, manifest, **kwargs):
            kwargs["heartbeat"]()
            assert manifest["contract_version"] == "final-knowledge-scope-v1"
            self.calls.append("final_verify")
            return _result(CandidateVerificationDecision.model_validate({"points": [{
                "candidate_index": row["candidate_index"], "semantic_support": "supported", "future_scope": "durable",
                "source_use": "standing_decision", "reason": "The exact original source supports this independent scoped requirement.",
                "scope_segments": [{"text": row.get("scope_text", row["statement"]), "source_use": "standing_decision",
                    "future_scope": "durable", "standalone": True, "content_role": "claim", "source_support": "supported"}]}
                for row in manifest["candidates"]]}))

    checkpoint, notes, provider = {}, [], Provider()

    async def persist():
        pass

    result = run(owner.run_source_handoff_recovery(backend, project_name="demo", project_root=root,
        run_id="recovery", manifest=manifest, checkpoint=checkpoint, notes=notes, provider=provider, persist=persist))
    assert result["status"] == "applied", result
    assert provider.calls == ["assimilate", "final_verify"]
    assert result["canonical_outcomes"][0]["candidate_id"] != old.id
    assert result["commit_bindings"][0]["status"] == "applied"
    assert run(store.get_candidate(old.id)).to_dict() == old_before
    assert run(backend.structured_store.get_dream_run(origin.id)).to_dict() == origin_before
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    assert run(backend.structured_store.get_task_handoff(handoff_id)).status == "done"
    carrier = DreamRun(id="recovery", project_name="demo", trigger_source="agent", status="completed",
        completed_at=datetime.now(timezone.utc), continuation=checkpoint)
    run(backend.structured_store.save_dream_run(carrier))
    proof = run(owner.read_source_handoff_recovery_proof(backend,
        run_id=carrier.id, origin_run_id=origin.id, source_job_id=job.id))
    assert proof["resolved"][0]["original_candidate_id"] == old.id
    assert proof["resolved"][0]["commit_bindings"][0]["transaction_sha256"]


@pytest.mark.parametrize("candidate_supported,final_supported", [(True, True), (False, True), (True, False)])
def test_cleaned_report_requires_fresh_native_verification_and_final_scope(
    coverage, monkeypatch, candidate_supported, final_supported,
):
    from datetime import datetime, timezone
    from harness_mem.autonomous.models import AssimilationDecision, CandidateVerificationDecision
    from harness_mem.commands.knowledge_assimilation import record_assimilation_result
    from harness_mem.commands.separated_assimilation import admit_separated_candidate, _materialize_handoff
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.mcp.distill_projection import render_distill_exchange_windows

    backend, root, job, _entry, _item, _checkpoint, _notes = coverage
    store = backend.structured_store.knowledge_store
    rendering = backend.transcript_store.reconstruct(job.source_id, source_revision=job.source_revision)
    window = render_distill_exchange_windows(rendering, [47])[0]
    statement = "Assistant interpretation 47."
    original_id = str(uuid5(NAMESPACE_URL,
        f"harness-mem:autonomous-knowledge-candidate:{job.id}:1:memory:{statement}"))
    old, _replay = run(admit_separated_candidate(backend, candidate_id=original_id, project_name="demo",
        candidate_type="memory", statement=statement, distill_job_id=job.id, evidence_basis="source_report",
        verification_outcome="verified", verification_refs=[{"kind": "source_report", "role": "assistant",
            "exchange_index": 47, "content_sha256": window["content_sha256"]}],
        verification_reason_codes=["source_use_reusable_knowledge", "future_scope_durable", "source_scope_durable",
                                   "semantic_support_verified", "autonomous_final_scope_required"]))
    assert old.source_report is not None
    original_report = old.source_report
    point = {"disposition": "handoff", "reason": "The current target page is incomplete; retain this exact report."}
    run(record_assimilation_result(backend, candidate=old, point=point))
    evidence = run(store.list_evidence(old.id))
    handoff_id = run(_materialize_handoff(backend, candidate=old, evidence=evidence[0], point=point))
    job.output_candidate_ids = [old.id]
    job.promotion_summary["points"] = [{"candidate_id": old.id, "disposition": "handoff", "handoff_id": handoff_id,
        "answer_status": "ANSWERED", "verification_outcome": "verified", "evidence_basis": "source_report",
        "verification_refs": [value.sanitized().to_dict() for value in evidence[0].verification_refs]}]
    with backend.transcript_store._lock:
        backend.transcript_store._distill._upsert_job_locked(job)
        backend.transcript_store._conn.commit()
    run(store.cleanup_candidate(old.id))
    assert run(store.get_candidate(old.id)) is None
    scope = {"trigger_id": job.session_id, "dispatch_generation": "same-natural-generation"}
    task_scope = owner.maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
    origin = DreamRun(id="natural-failed", project_name="demo", trigger_source="ide_hook", status="failed",
        completed_at=datetime.now(timezone.utc), notes=["Hook session distill succeeded: " + job.id],
        continuation={"maintenance_scope": scope})
    run(backend.structured_store.save_dream_run(origin))
    account = {"task_scope": task_scope, "host_client": "codex", "bounds": {"max_calls": 64},
               "calls": [{"call_id": "natural-old-call", "status": "completed", "usage_exact": True, "usage": {"input_tokens": 1, "output_tokens": 1, "duration_seconds": 1.0}}]}
    monkeypatch.setattr(owner, "read_task_budget_receipt", lambda *args: account)
    manifest = run(owner.prepare_source_handoff_recovery(backend, project_name="demo", project_root=root,
        run_id="natural-recovery", origin_run_id=origin.id, source_job_id=job.id, handoff_ids=[handoff_id]))

    class Provider:
        task_budget_binding = SimpleNamespace(task_scope=task_scope, host_client="codex", data_dir=backend.data_dir)
        _budget_phase, _budget_slice, _budget_retry_of = "dream", "dream:natural-recovery:1", None
        _last_budget_call_id = None

        def __init__(self):
            self.calls = []

        def bind_task_budget(self, *args, **kwargs):
            assert kwargs["phase"] == "dream"

        def decide(self, *args, **kwargs):
            raise AssertionError("Rehydration must not run source extraction.")

        def assimilate(self, manifest, **kwargs):
            self.calls.append("assimilate")
            assert manifest["current_truth"] == []
            candidate = manifest["verified_candidates"][0]
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": candidate["candidate_id"], "disposition": "add", "matched_truth_handles": [],
                "knowledge_items": [{"title": original_report.legacy_title(), "statement": original_report.render_statement(),
                    "topic_path": ["report"], "claim_kind": "source_report"}],
                "reason": "Retain the independent original account with its complete attribution boundary."}]}))

        def verify(self, manifest, **kwargs):
            kwargs["heartbeat"]()
            final = manifest["contract_version"] == "final-knowledge-scope-v1"
            self.calls.append("final_verify" if final else "candidate_verify")
            supported = final_supported if final else candidate_supported
            return _result(CandidateVerificationDecision.model_validate({"points": [{
                "candidate_index": row["candidate_index"], "semantic_support": "supported" if supported else "partial",
                "future_scope": "durable", "source_use": "reusable_knowledge",
                "reason": "The native assistant account supports this exact bounded report." if supported
                          else "Some claimed wording is not established by the native account.",
                "scope_segments": [{"text": row.get("scope_text", row["statement"]), "source_use": "reusable_knowledge",
                    "future_scope": "durable", "standalone": True, "content_role": "claim",
                    "source_support": "supported" if supported else "unclear"}]}
                for row in manifest["candidates"]]}))

    checkpoint, provider = {}, Provider()

    async def persist():
        pass

    result = run(owner.run_source_handoff_recovery(backend, project_name="demo", project_root=root,
        run_id="natural-recovery", manifest=manifest, checkpoint=checkpoint, notes=[], provider=provider, persist=persist))
    assert result["status"] == ("applied" if candidate_supported and final_supported else "unresolved"), result
    assert provider.calls[0] == "candidate_verify"
    assert run(store.get_candidate(old.id)) is None
    handoff = run(backend.structured_store.get_task_handoff(handoff_id))
    assert handoff.status == ("done" if candidate_supported and final_supported else "in_progress")
    if candidate_supported and final_supported:
        entry = run(store.get_entry(result["commit_bindings"][0]["truth_ids"][0], project_name="demo"))
        assert entry.source_report.same_account_source(original_report)
        assert entry.statement == original_report.render_statement()
    else:
        assert not result["commit_bindings"]


def enqueue_fixture(fixture, monkeypatch):
    from harness_mem.commands import dream_continuation
    from harness_mem import hook_background
    from harness_mem.core.schemas.dream_run import DreamRun

    structured = fixture.backend.structured_store
    canonical = fixture.canonical
    canonical.rows["dream_runs", "origin"] = fixture.origin.to_dict()
    staged, queued = [], []

    async def get_run(identity):
        if identity == fixture.origin.id:
            return fixture.origin
        payload = canonical.get_payload("dream_runs", identity)
        return DreamRun.from_dict(payload) if payload else None

    async def list_runs(project_name, **kwargs):
        values = [DreamRun.from_dict(payload) for (collection, identity), payload in canonical.rows.items()
                  if collection == "dream_runs" and identity != fixture.origin.id]
        return sorted(values, key=lambda value: value.started_at, reverse=True)[:kwargs.get("limit", 1)] or [fixture.origin]

    async def save_run(value):
        staged.append(value.id)
        canonical.rows["dream_runs", value.id] = value.to_dict()

    async def bound(backend, *, run_id, **kwargs):
        return await get_run(run_id), "original-generation", "session"

    async def source_account(backend, *, run, **kwargs):
        return run, "original-generation", "session"

    def dispatch(data_dir, **kwargs):
        queued.append(kwargs)
        return SimpleNamespace(spawned=True, coalesced=False)

    structured.get_dream_run, structured.list_dream_runs, structured.save_dream_run = get_run, list_runs, save_run
    structured._index = SimpleNamespace(upsert=lambda *args: None)
    monkeypatch.setattr(dream_continuation, "_bound_origin", bound)
    monkeypatch.setattr(dream_continuation, "_bound_source_account", source_account)
    monkeypatch.setattr(hook_background, "dispatch_bound_continuation", dispatch)
    return SimpleNamespace(get_run=get_run, staged=staged, queued=queued, canonical=canonical)


def enqueue(fixture):
    return owner.enqueue_source_handoff_recovery(fixture.backend, project_name="demo", project_root=fixture.root,
        config=SimpleNamespace(), host_client="codex", origin_run_id="origin", source_job_id="job", handoff_ids=["handoff"])


def test_enqueue_uses_real_run_pointer_and_original_task_generation(fixture, monkeypatch):
    data = enqueue_fixture(fixture, monkeypatch)
    original = fixture.origin.to_dict()
    result = run(enqueue(fixture))
    carrier = run(data.get_run(result["run_id"]))
    assert result["status"] == "queued" and result["generation"] == "original-generation"
    assert carrier.id not in {fixture.origin.id, fixture.job.id, fixture.handoff.id}
    assert carrier.status == "continuing" and carrier.trigger_source == "ide_hook"
    assert carrier.continuation["max_slices"] == 3
    assert carrier.continuation["maintenance_scope"] == fixture.origin.continuation["maintenance_scope"]
    assert data.queued[0]["resume_run_id"] == carrier.id
    assert data.queued[0]["trigger_id"] == "session"
    assert fixture.origin.to_dict() == original
    again = run(enqueue(fixture))
    assert again["run_id"] == result["run_id"]


def test_enqueue_preflight_rejection_never_leaves_a_continuing_shell(fixture, monkeypatch):
    from harness_mem.commands import dream_continuation
    data = enqueue_fixture(fixture, monkeypatch)

    async def refuse(*args, **kwargs):
        raise ValueError("continuation_not_authorized")

    monkeypatch.setattr(dream_continuation, "_bound_origin", refuse)
    monkeypatch.setattr(dream_continuation, "_bound_source_account", refuse)
    with pytest.raises(ValueError, match="continuation_not_authorized"):
        run(enqueue(fixture))
    assert not [payload for (collection, identity), payload in data.canonical.rows.items()
                if collection == "dream_runs" and identity != fixture.origin.id
                and payload.get("status") == "continuing"]
    assert data.queued == []


def test_concurrent_enqueue_cannot_overwrite_a_started_carrier(fixture, monkeypatch):
    from harness_mem import hook_background
    data = enqueue_fixture(fixture, monkeypatch)
    prepare_original = owner.prepare_source_handoff_recovery
    arrived = 0

    async def scenario():
        barrier = asyncio.Event()

        async def prepare_concurrently(*args, **kwargs):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                barrier.set()
            await barrier.wait()
            return await prepare_original(*args, **kwargs)

        def started(data_dir, **kwargs):
            data.queued.append(kwargs)
            payload = data.canonical.rows["dream_runs", kwargs["resume_run_id"]]
            payload["continuation"].update(slice_count=1, worker_progress="must survive duplicate enqueue")
            return SimpleNamespace(spawned=True, coalesced=False)

        monkeypatch.setattr(owner, "prepare_source_handoff_recovery", prepare_concurrently)
        monkeypatch.setattr(hook_background, "dispatch_bound_continuation", started)
        return await asyncio.gather(enqueue(fixture), enqueue(fixture), return_exceptions=True)

    results = run(scenario())
    assert any(isinstance(value, dict) and value.get("status") == "queued" for value in results)
    carriers = [payload for (collection, identity), payload in data.canonical.rows.items()
                if collection == "dream_runs" and identity != fixture.origin.id]
    assert len(carriers) == 1
    assert carriers[0]["continuation"].get("worker_progress") == "must survive duplicate enqueue"
    assert len(data.staged) <= 1  # A late scheduler must never replace this carrier's checkpoint.


@pytest.mark.parametrize("worker_progress", [False, True])
def test_enqueue_dispatch_failure_only_closes_its_unchanged_initial_carrier(fixture, monkeypatch, worker_progress):
    from harness_mem import hook_background
    data = enqueue_fixture(fixture, monkeypatch)
    apply = data.canonical.apply_payload_transaction

    def create_then_worker_advances(*, idempotency_key, mutations):
        result = apply(idempotency_key=idempotency_key, mutations=mutations)
        if worker_progress and idempotency_key.startswith("source-handoff-carrier-create:"):
            payload = data.canonical.rows["dream_runs", mutations[0]["entity_id"]]
            payload["continuation"].update(slice_count=1, worker_progress="newer canonical checkpoint")
        return result

    def dispatch_refused(*args, **kwargs):
        raise RuntimeError("Isolated dispatch failure.")

    monkeypatch.setattr(data.canonical, "apply_payload_transaction", create_then_worker_advances)
    monkeypatch.setattr(hook_background, "dispatch_bound_continuation", dispatch_refused)
    with pytest.raises(RuntimeError, match="Isolated dispatch failure"):
        run(enqueue(fixture))
    carriers = [payload for (collection, identity), payload in data.canonical.rows.items()
                if collection == "dream_runs" and identity != fixture.origin.id]
    assert len(carriers) == 1
    carrier = carriers[0]
    assert carrier["status"] == ("continuing" if worker_progress else "failed")
    if worker_progress:
        assert carrier["continuation"].get("worker_progress") == "newer canonical checkpoint"
    else:
        assert carrier["completed_at"] is not None


@pytest.fixture
def indexed_native_handoff(coverage, monkeypatch):
    """Real canonical store, real derived index, immutable native fixture source."""
    from datetime import datetime, timezone
    from harness_mem.commands import dream_continuation
    from harness_mem.commands.knowledge_assimilation import record_assimilation_result
    from harness_mem.commands.separated_assimilation import admit_separated_candidate, _materialize_handoff
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.mcp.distill_projection import render_distill_exchange_windows

    backend, root, job, _entry, _item, _checkpoint, _notes = coverage
    store = backend.structured_store.knowledge_store
    rendering = backend.transcript_store.reconstruct(job.source_id, source_revision=job.source_revision)
    window = render_distill_exchange_windows(rendering, [47])[0]
    statement = "Assistant interpretation 47."
    original_id = str(uuid5(NAMESPACE_URL,
        f"harness-mem:autonomous-knowledge-candidate:{job.id}:1:memory:{statement}"))
    old, _replay = run(admit_separated_candidate(backend, candidate_id=original_id, project_name="demo",
        candidate_type="memory", statement=statement, distill_job_id=job.id, evidence_basis="source_report",
        verification_outcome="verified", verification_refs=[{"kind": "source_report", "role": "assistant",
            "exchange_index": 47, "content_sha256": window["content_sha256"]}],
        verification_reason_codes=["source_use_reusable_knowledge", "future_scope_durable", "source_scope_durable",
                                   "semantic_support_verified", "autonomous_final_scope_required"]))
    point = {"disposition": "handoff", "reason": "The comparison page is incomplete; retain this original account."}
    run(record_assimilation_result(backend, candidate=old, point=point))
    evidence = run(store.list_evidence(old.id))
    handoff_id = run(_materialize_handoff(backend, candidate=old, evidence=evidence[0], point=point))
    job.output_candidate_ids = [old.id]
    job.promotion_summary["points"] = [{"candidate_id": old.id, "disposition": "handoff", "handoff_id": handoff_id,
        "answer_status": "ANSWERED", "verification_outcome": "verified", "evidence_basis": "source_report",
        "verification_refs": [value.sanitized().to_dict() for value in evidence[0].verification_refs]}]
    with backend.transcript_store._lock:
        backend.transcript_store._distill._upsert_job_locked(job)
        backend.transcript_store._conn.commit()
    run(store.cleanup_candidate(old.id))
    scope = {"trigger_id": job.session_id, "dispatch_generation": "same-native-generation"}
    task_scope = owner.maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
    origin = DreamRun(id="indexed-native-origin", project_name="demo", trigger_source="ide_hook", status="failed",
        completed_at=datetime.now(timezone.utc), notes=["Hook session distill verified: " + job.id],
        continuation={"maintenance_scope": scope})
    run(backend.structured_store.save_dream_run(origin))
    legacy_id = str(uuid5(NAMESPACE_URL, "harness-mem:source-handoff-carrier:" + owner._digest({
        "project": "demo", "origin": origin.id, "job": job.id, "handoffs": [handoff_id]})))
    legacy = DreamRun(id=legacy_id, project_name="demo", trigger_source="ide_hook", status="failed",
        completed_at=datetime.now(timezone.utc), notes=["source_handoff_carrier_dispatch_failed"])
    run(backend.structured_store.save_dream_run(legacy))
    canonical = backend.structured_store._canonical
    old_payload = canonical.get_payload_json("dream_runs", legacy_id)
    account = {"task_scope": task_scope, "host_client": "codex", "bounds": {"max_calls": 64},
        "calls": [{"call_id": f"known-{index}", "status": "completed", "usage_exact": True,
            "usage": {"input_tokens": 1, "output_tokens": 1, "duration_seconds": 1.0}} for index in range(15)]}
    monkeypatch.setattr(owner, "read_task_budget_receipt", lambda *args: account)

    async def auth_only(backend, *, run, **kwargs):
        assert kwargs["host_client"] == "codex"
        assert run.continuation["maintenance_scope"] == scope
        return run, scope["dispatch_generation"], scope["trigger_id"]

    def forbidden_payload_writer(*args, **kwargs):
        raise AssertionError("An index projection must not call save_dream_run.")

    monkeypatch.setattr(dream_continuation, "_bound_source_account", auth_only)
    monkeypatch.setattr(backend.structured_store, "save_dream_run", forbidden_payload_writer)

    async def enqueue_native():
        from harness_mem.config.merge import MergedConfig
        return await owner.enqueue_source_handoff_recovery(backend, project_name="demo", project_root=root,
            config=MergedConfig(), host_client="codex", origin_run_id=origin.id,
            source_job_id=job.id, handoff_ids=[handoff_id])

    return SimpleNamespace(backend=backend, root=root, job=job, origin=origin, legacy_id=legacy_id,
        legacy_payload=old_payload, canonical=canonical, account=account, enqueue=enqueue_native,
        job_before=job.to_dict(), origin_before=origin.to_dict())


def test_real_index_publishes_fresh_carrier_before_bound_resume_and_preserves_legacy(indexed_native_handoff, monkeypatch):
    from harness_mem import hook_background
    from harness_mem.commands.dream_continuation import _bound_origin
    from harness_mem.config.merge import MergedConfig
    data, dispatched = indexed_native_handoff, []

    # Dispatch is synchronous inside an async caller, so inspect the actual
    # SQLite projection directly there. Public async list is checked below.
    def dispatch_without_loop(data_dir, **kwargs):
        rows = data.backend.structured_store._index.list("dream_runs", "project_name = ?", ("demo",),
            order_by="started_at DESC", limit=1)
        assert rows[0]["id"] == kwargs["resume_run_id"]
        dispatched.append(kwargs)
        return SimpleNamespace(spawned=True, coalesced=False)

    monkeypatch.setattr(hook_background, "dispatch_bound_continuation", dispatch_without_loop)
    result = run(data.enqueue())
    assert result["run_id"] != data.legacy_id
    latest = run(data.backend.structured_store.list_dream_runs("demo", limit=1))
    assert latest[0].id == result["run_id"] and latest[0].status == "continuing"
    resumed, generation, trigger = run(_bound_origin(data.backend, project_name="demo", project_root=str(data.root),
        config=MergedConfig(), host_client="codex", run_id=result["run_id"]))
    assert resumed.id == latest[0].id and generation == "same-native-generation" and trigger == data.job.session_id
    raw_before = data.canonical.get_payload_json("dream_runs", resumed.id)
    assert run(data.enqueue())["run_id"] == resumed.id
    assert data.canonical.get_payload_json("dream_runs", resumed.id) == raw_before
    assert data.canonical.get_payload_json("dream_runs", data.legacy_id) == data.legacy_payload
    assert data.backend.transcript_store.get_distill_job(data.job.id).to_dict() == data.job_before
    assert run(data.backend.structured_store.get_dream_run(data.origin.id)).to_dict() == data.origin_before
    assert len(data.account["calls"]) == 15
    assert len(dispatched) == 2


@pytest.mark.parametrize("failure", ["dispatch", "initial_projection", "dispatch_after_progress"])
def test_real_index_tracks_failed_carrier_without_payload_save(indexed_native_handoff, monkeypatch, failure):
    from harness_mem import hook_background
    data = indexed_native_handoff
    dispatched = []
    index = data.backend.structured_store._index
    upsert = index.upsert
    projections = []

    def project(table, row):
        projections.append(dict(row))
        if failure == "initial_projection" and len(projections) == 1:
            raise RuntimeError("Isolated initial projection failure.")
        return upsert(table, row)

    def dispatch(*args, **kwargs):
        dispatched.append(kwargs)
        if failure == "dispatch_after_progress":
            identity = kwargs["resume_run_id"]
            raw = data.canonical.get_payload_json("dream_runs", identity)
            payload = json.loads(raw)
            payload["continuation"].update(slice_count=1, worker_progress="newer real canonical checkpoint")
            data.canonical.apply_payload_transaction(idempotency_key="isolated-started-worker", mutations=[{
                "operation": "upsert", "collection": "dream_runs", "entity_id": identity,
                "project_name": "demo", "payload": payload,
                "expected_sha256": hashlib.sha256(raw.encode()).hexdigest()}])
        raise RuntimeError("Isolated dispatch failure.")

    monkeypatch.setattr(index, "upsert", project)
    monkeypatch.setattr(hook_background, "dispatch_bound_continuation", dispatch)
    with pytest.raises(RuntimeError, match="Isolated"):
        run(data.enqueue())
    latest = run(data.backend.structured_store.list_dream_runs("demo", limit=1))
    assert latest[0].id != data.legacy_id
    expected_status = "continuing" if failure == "dispatch_after_progress" else "failed"
    assert latest[0].status == expected_status
    assert (latest[0].completed_at is None) == (failure == "dispatch_after_progress")
    indexed = index.get("dream_runs", latest[0].id)
    assert indexed["status"] == expected_status
    canonical = json.loads(data.canonical.get_payload_json("dream_runs", latest[0].id))
    assert canonical["status"] == expected_status
    assert canonical["continuation"]["slice_count"] == (1 if failure == "dispatch_after_progress" else 0)
    if failure == "dispatch_after_progress":
        assert canonical["continuation"]["worker_progress"] == "newer real canonical checkpoint"
    assert data.canonical.get_payload_json("dream_runs", data.legacy_id) == data.legacy_payload
    assert len(dispatched) == (0 if failure == "initial_projection" else 1)
    assert len(projections) == 2 and projections[-1]["status"] == expected_status
