"""One interrupted old contract is retried under the same isolated task account."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider, _cover
from test_terminal_source_coverage import terminal as terminal, invoke, run
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.commands.separated_assimilation import create_separated_candidates
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, dispatch_with_task_budget, read_task_budget_receipt, task_budget_receipt_path,
)
from harness_mem.autonomous.worker import _candidate_statement_from_arguments


@pytest.fixture
def interrupted(terminal, monkeypatch):
    backend, root, origin, carrier, job, provider, config, bindings = terminal
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    item = origin.items[0]
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=origin.id, item=item, checkpoint=origin.continuation, notes=origin.notes))
    binding = {**prepared["binding"], "contract": "dream-applied-source-coverage-v2"}
    coverage_job = prepared["job"]
    attempt = owner._digest(binding)
    window = prepared["packet"]["semantic_decision_exchanges"][0]
    arguments = [{"kind": "rule", "trigger": "本轮修复", "pattern": f"保留未提交的条件 {index}。",
        "evidence_basis": "user_statement", "verification_outcome": "unverified",
        "verification_refs": [{"kind": "user_statement", "role": "user",
            "exchange_index": window["exchange_index"], "content_sha256": window["content_sha256"]}]}
        for index in range(3)]
    identities = run(create_separated_candidates(backend, project_name="demo", distill_job_id=coverage_job.id,
        candidate_arguments=arguments, _attempt_namespace=f"source-coverage:{attempt}", _retire_prior_pending=False))
    state = {"status": "candidates_verified", "binding": binding, "binding_sha256": attempt,
        "candidate_ids": identities, "commit_bindings": [], "terminal_takeover_contract": owner.TERMINAL_TAKEOVER_CONTRACT}
    origin.continuation["source_coverage"] = {item.source_id: state,
        "other-failed": {"status": "failed", "reason_code": "source_coverage_original_user_source_unproved"}}
    origin.continuation["source_coverage_pending_ids"] = [item.source_id]
    reflection = ReflectionJob(id="interrupted-reflection", project_name="demo", project_root=str(root),
        kind="dream", status="completed", source="ide_hook", input_refs=[origin.id, job.id])
    backend.reflection_job_store.save(reflection)
    now = datetime.now(timezone.utc)
    closed = DreamRun(id="interrupted-carrier", project_name="demo", status="completed", trigger_source="ide_hook",
        started_at=now - timedelta(minutes=3), completed_at=now - timedelta(minutes=1),
        reflection_job_id=reflection.id, resolution_status="unresolved", continuation={
            "terminal_source_coverage_origin_run_id": origin.id,
            "maintenance_scope": dict(origin.continuation["maintenance_scope"]),
            "terminal_source_coverage": {f"{origin.id}:{item.source_id}": {"origin_run_id": origin.id,
                "predecessor_id": item.source_id, "status": "blocked", "reason": "terminal_coverage_runtime_changed"}}})
    run(backend.structured_store.save_dream_run(closed))
    claim = {"origin_run_id": origin.id, "predecessor_id": item.source_id,
        "source_binding_sha256": attempt, "runtime_fingerprint": "closed-old-runtime",
        "carrier_run_id": closed.id, "carrier_reflection_id": reflection.id, "status": "claimed"}
    origin.continuation["terminal_coverage_takeover"] = {"contract": owner.TERMINAL_TAKEOVER_CONTRACT,
        "slice_count": 1, "origin_fixed_sha256": owner._terminal_fixed(origin),
        "claims": {f"{closed.id}:1": claim}}
    receipts = []
    for phase, suffix in [("decide", "source-decide:" + coverage_job.id), ("candidate_verify", "source-verify")]:
        dispatch_with_task_budget(bindings[0], phase="dream", slice_id=f"source-coverage:{origin.id}:{attempt}:{suffix}",
            timeout_seconds=1, transport=lambda _bound: NativeDispatchResult(status="completed",
                input_tokens=20, output_tokens=5, duration_seconds=.01, usage_exact=True))
        native = {"status": "completed", "terminal": "completed", "model_dispatched": True,
            "unknown_response_usage_count": 0, "input_sha256": "a" * 64, "response_text_sha256": "b" * 64}
        receipt = {"attempt_id": attempt, "phase": phase, "source_job_id": coverage_job.id,
            "schema_valid": True, "host_client": "codex", "input_sha256": "a" * 64,
            "response_sha256": "b" * 64, "input_tokens": 20, "output_tokens": 5, "native_attempts": [native]}
        if phase == "candidate_verify":
            receipt["verification_points"] = [{"candidate_index": index,
                "scope_text_sha256": hashlib.sha256(_candidate_statement_from_arguments(arguments[index]).encode()).hexdigest()}
                for index in range(len(arguments))]
        receipts.append("dream source coverage receipt: " + json.dumps(receipt))
    origin.continuation["terminal_coverage_receipts"] = receipts
    run(backend.structured_store.save_dream_run(origin))
    # The existing new carrier uses the same original task rather than the
    # independent source account present in the generic terminal fixture.
    carrier.continuation["terminal_source_coverage_origin_run_id"] = origin.id
    carrier.continuation["maintenance_scope"] = dict(origin.continuation["maintenance_scope"])
    run(backend.structured_store.save_dream_run(carrier))
    current = backend.reflection_job_store.get(carrier.reflection_job_id)
    current.input_refs = [origin.id, job.id]
    backend.reflection_job_store.save(current)
    provider.bind_task_budget(bindings[0], phase="dream", slice_id=f"dream:{carrier.id}:1")
    return terminal, prepared, copy.deepcopy(state), copy.deepcopy(claim), identities, closed


def prove(data):
    terminal, prepared, _state, _claim, _identities, _closed = data
    backend, _root, origin, carrier, _job, _provider, config, _bindings = terminal
    return run(owner._prove_interrupted_retry(backend, origin=origin, item=origin.items[0], prepared=prepared,
        config=config, host_client="codex", active_carrier_id=carrier.id))


def test_interrupted_nomination_requires_fresh_dynamic_proof(interrupted):
    terminal, prepared, state, *_ = interrupted
    assert owner._interrupted_retryable(state)
    with pytest.raises(ValueError, match="interrupted_preflight_required"):
        owner._state_for_binding(state, prepared["binding"])
    proof = prove(interrupted)
    frozen = owner._state_for_binding(state, prepared["binding"], interrupted_proof=proof)
    assert frozen["candidate_ids"] == [] and frozen["commit_bindings"] == []
    history = frozen["previous_contract_attempts"][0]
    assert history["state_sha256"] == owner._digest(state)
    assert history["interrupted_adoption"]["candidates"] == proof["candidates"]
    assert terminal[2].continuation["source_coverage"][terminal[2].items[0].source_id] == state


def test_interrupted_retry_runs_fresh_complete_pipeline_preserves_old_workspace_and_account(interrupted):
    terminal, _prepared, old_state, old_claim, identities, _closed = interrupted
    backend, _root, origin, _carrier, job, provider, _config, bindings = terminal
    store = backend.structured_store.knowledge_store
    old_candidates = [run(store.get_candidate(identity)).to_dict() for identity in identities]
    job_before, fixed = job.to_dict(), owner._terminal_fixed(origin)
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    other_account = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    result = invoke(terminal)
    assert result["status"] == "applied" and result["worked"], result
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    saved = run(backend.structured_store.get_dream_run(origin.id))
    assert owner._terminal_fixed(saved) == fixed and saved.status == "failed"
    state = saved.continuation["source_coverage"][origin.items[0].source_id]
    assert state["binding"]["contract"] == owner.CONTRACT
    assert set(state["candidate_ids"]).isdisjoint(identities)
    assert state["previous_contract_attempts"][0]["state_sha256"] == owner._digest(old_state)
    assert saved.continuation["terminal_coverage_takeover"]["claims"]["interrupted-carrier:1"] == old_claim
    assert saved.continuation["terminal_coverage_takeover"]["slice_count"] == 2
    assert saved.continuation["source_coverage"]["other-failed"]["status"] == "failed"
    assert [run(store.get_candidate(identity)).to_dict() for identity in identities] == old_candidates
    current_account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert current_account["calls"][:len(account["calls"])] == account["calls"]
    assert len(current_account["calls"]) == len(account["calls"]) + 4
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == other_account
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    calls = list(provider.calls)
    invoke(terminal)
    assert provider.calls == calls


@pytest.mark.parametrize("fault", ["candidate_status", "candidate_text", "native_hash", "evidence_job",
    "evidence_role", "evidence_digest", "carrier_processing", "carrier_reason", "reflection_processing",
    "binding_context", "binding_successor", "commit", "promoted", "unknown", "active", "budget", "limit"])
def test_interrupted_refusals_make_no_new_claim_or_model_call(interrupted, fault):
    terminal, _prepared, state, _claim, identities, closed = interrupted
    backend, _root, origin, _carrier, _job, provider, _config, bindings = terminal
    store = backend.structured_store.knowledge_store
    current = origin.continuation["source_coverage"][origin.items[0].source_id]
    if fault.startswith("candidate_"):
        candidate = run(store.get_candidate(identities[0]))
        if fault == "candidate_status":
            candidate.status = "assimilated"
        else:
            candidate.statement += " Changed proposal."
        run(store.save_candidate(candidate))
    elif fault.startswith("evidence_"):
        evidence = run(store.list_evidence(identities[0]))[0]
        if fault == "evidence_job":
            evidence.distill_job_id = "other-job"
        elif fault == "evidence_role":
            evidence.verification_refs[0].role = "assistant"
        else:
            evidence.verification_refs[0].content_sha256 = "f" * 64
        run(store.save_evidence(evidence))
    elif fault == "native_hash":
        receipt = json.loads(origin.continuation["terminal_coverage_receipts"][-1].split(": ", 1)[1])
        receipt["verification_points"][0]["scope_text_sha256"] = "f" * 64
        origin.continuation["terminal_coverage_receipts"][-1] = "dream source coverage receipt: " + json.dumps(receipt)
    elif fault.startswith("carrier_"):
        if fault == "carrier_processing":
            closed.status = "processing"
        else:
            next(iter(closed.continuation["terminal_source_coverage"].values()))["reason"] = "provider_failed"
        run(backend.structured_store.save_dream_run(closed))
    elif fault == "reflection_processing":
        reflection = backend.reflection_job_store.get(closed.reflection_job_id)
        reflection.status = "processing"
        backend.reflection_job_store.save(reflection)
    elif fault.startswith("binding_"):
        field = "context_sha256" if fault == "binding_context" else "successor_sha256"
        current["binding"][field] = "changed"
        current["binding_sha256"] = owner._digest(current["binding"])
    elif fault == "commit":
        current["commit_bindings"] = [{"status": "committing", "truth_ids": ["new-truth"]}]
    elif fault == "promoted":
        current["result_status_counts"] = {"promoted": 1}
    elif fault in {"unknown", "active", "budget"}:
        path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
        account = json.loads(path.read_text())
        if fault == "unknown":
            account["calls"][-1]["usage_exact"] = False
        elif fault == "active":
            account["calls"][-1]["status"] = "reserved"
        else:
            account["calls"][-1]["usage"]["output_tokens"] = 128000
        path.write_text(json.dumps(account))
    elif fault == "limit":
        cp = origin.continuation
        claims = cp["terminal_coverage_takeover"]["claims"]
        while len(claims) < cp["max_slices"] - cp["slice_count"]:
            claims[f"spent:{len(claims)}"] = {"status": "failed"}
        cp["terminal_coverage_takeover"]["slice_count"] = len(claims)
    run(backend.structured_store.save_dream_run(origin))
    original = run(backend.structured_store.get_dream_run(origin.id)).to_dict()
    result = invoke(terminal)
    assert result["status"] == "blocked", result
    assert provider.calls == []
    assert run(backend.structured_store.get_dream_run(origin.id)).to_dict() == original
    assert state["binding"]["contract"] == "dream-applied-source-coverage-v2"


def test_contract_scope_uses_complete_original_task_not_successor_topic(coverage):
    class ScopeProvider(CoverageProvider):
        def decide(self, manifest, **kwargs):
            instruction = manifest["source_coverage"]["instruction"]
            assert "same original authored-user task and complete immutable source" in instruction
            assert "narrower subject must not exclude" in instruction
            assert "re-extract unrelated tasks" in instruction
            assert "permanent" in instruction and "does not itself prove human approval" in instruction
            assert "this group's existing subject" not in instruction
            return super().decide(manifest, **kwargs)

    provider = ScopeProvider()
    run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]


def test_same_current_contract_failure_cannot_nominate_another_retry(interrupted):
    _terminal, prepared, state, *_ = interrupted
    state["binding"] = prepared["binding"]
    state["binding_sha256"] = owner._digest(state["binding"])
    assert not owner._interrupted_retryable(state)
    state.update(status="failed", reason_code="source_coverage_provider_failed")
    assert not owner._coverage_pending(state)


def test_idle_origin_preflight_proves_interruption_before_any_new_worker(interrupted):
    terminal, _prepared, _state, *_ = interrupted
    backend, root, origin, carrier, _job, provider, config, _bindings = terminal
    carrier.status = "failed"
    carrier.completed_at = datetime.now(timezone.utc)
    run(backend.structured_store.save_dream_run(carrier))
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    reflection.status = "completed"
    backend.reflection_job_store.save(reflection)
    before = run(backend.structured_store.get_dream_run(origin.id)).to_dict()
    found = run(owner.bound_terminal_source_coverage_origin(backend, project_name="demo", project_root=root,
        config=config, host_client="codex", origin_run_id=origin.id))
    assert found[0].id == origin.id and found[1] == "original-generation"
    assert run(backend.structured_store.get_dream_run(origin.id)).to_dict() == before
    assert provider.calls == []


def test_live_unowned_lease_refuses_interruption_adoption(interrupted):
    terminal = interrupted[0]
    backend, root, _origin, _carrier, *_ = terminal
    stem = hashlib.sha256(f"codex\0{root.resolve()}".encode()).hexdigest()[:24]
    path = backend.data_dir / "hook_runtime" / "background" / f"codex-{stem}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": 1, "generation": "other-worker"}))
    with pytest.raises(ValueError, match="interrupted_worker_active"):
        prove(interrupted)


def test_every_old_same_binding_claim_must_be_closed(interrupted):
    terminal, _prepared, _state, claim, _identities, closed = interrupted
    backend, _root, origin, *_ = terminal
    other = closed.model_copy(deep=True)
    other.id = "other-old-carrier"
    other.status = "processing"
    run(backend.structured_store.save_dream_run(other))
    origin.continuation["terminal_coverage_takeover"]["claims"]["other-old-carrier:1"] = {
        **claim, "carrier_run_id": other.id}
    with pytest.raises(ValueError, match="interrupted_carrier_not_closed"):
        prove(interrupted)


def test_workspace_race_after_proof_cannot_claim_or_dispatch(interrupted, monkeypatch):
    terminal, _prepared, _state, _claim, identities, _closed = interrupted
    backend, _root, origin, _carrier, _job, provider, *_ = terminal
    actual = owner._prove_interrupted_retry
    store = backend.structured_store.knowledge_store

    async def changed_after_proof(*args, **kwargs):
        proof = await actual(*args, **kwargs)
        candidate = await store.get_candidate(identities[0])
        candidate.status = "assimilated"
        await store.save_candidate(candidate)
        return proof

    monkeypatch.setattr(owner, "_prove_interrupted_retry", changed_after_proof)
    before = run(backend.structured_store.get_dream_run(origin.id)).to_dict()
    result = invoke(terminal)
    assert result["reason"] == "source_coverage_interrupted_candidate_snapshot_changed", result
    assert run(backend.structured_store.get_dream_run(origin.id)).to_dict() == before
    assert provider.calls == []
