"""Partial contract revalidation preserves old writes, workspaces and budgets."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from dataclasses import replace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal, AccountedProvider, invoke, run
from test_dream_stage4_contract import _result
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, task_budget_receipt_path


class PartialProvider(AccountedProvider):
    def decide(self, manifest, **kwargs):
        result = super().decide(manifest, **kwargs)
        first = result.decision.candidates[0]
        second = first.model_copy(update={"content": "Preserve the current repair's validation limits."})
        return replace(result, decision=result.decision.model_copy(update={"candidates": [first, second]}))

    def assimilate(self, manifest, **kwargs):
        self.charge()
        kwargs["heartbeat"]()
        self.calls.append("assimilate")
        target = next(row["handle"] for row in manifest["current_truth"] if row["statement"] == "Preserve explicit corrections.")
        points = []
        for row in manifest["verified_candidates"]:
            if "validation limits" in row["statement"]:
                points.append({"candidate_id": row["candidate_id"], "disposition": "refine", "matched_truth_handles": [target],
                    "knowledge_items": [{"title": "Repair validation scope", "statement": "Preserve the current repair's validation limits.",
                        "topic_path": ["daily-entry"], "claim_kind": "design_requirement"}],
                    "reason": "This proposed update still requires a complete independent update judgment."})
                continue
            points.append({"candidate_id": row["candidate_id"], "disposition": "add", "matched_truth_handles": [],
             "knowledge_items": [{"title": f"Retained condition {index}",
                 "statement": text, "topic_path": ["daily-entry"], "claim_kind": "design_requirement"}
                 for index, text in enumerate(["Repair the daily-entry workflow.", "Preserve explicit daily-entry corrections.",
                     "Do not add daily-entry acceptance rituals during this repair."])],
             "reason": "Keep the source-supported existing repair conditions."})
        return _result(AssimilationDecision.model_validate({"points": points}))


@pytest.fixture
def partial(terminal, monkeypatch):
    backend, root, origin, carrier, job, _provider, config, bindings = terminal
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    carrier.continuation.update(terminal_source_coverage_origin_run_id=origin.id,
        maintenance_scope=dict(origin.continuation["maintenance_scope"]))
    run(backend.structured_store.save_dream_run(carrier))
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    reflection.input_refs = [origin.id, job.id]
    backend.reflection_job_store.save(reflection)
    provider = PartialProvider()
    provider.bind_task_budget(bindings[0], phase="dream", slice_id=f"dream:{carrier.id}:1")
    old_data = backend, root, origin, carrier, job, provider, config, bindings
    with monkeypatch.context() as old_contract:
        old_contract.setattr(owner, "CONTRACT", "dream-applied-source-coverage-v3")
        result = invoke(old_data)
    assert result["status"] == "unresolved", result
    origin = run(backend.structured_store.get_dream_run(origin.id))
    state = origin.continuation["source_coverage"][origin.items[0].source_id]
    assert len(state["commit_bindings"]) == 1 and len(state["commit_bindings"][0]["truth_ids"]) == 3, (state, provider.calls)
    assert any(row["disposition"] == "defer" for row in state["candidate_outcomes"])
    # The fake native transport's receipts attest the same known usage charged
    # to the isolated original account; no real host process is invoked.
    receipts = []
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    phase_slices = {"decide": "source-decide:" + state["binding"]["source_job_id"], "candidate_verify": "source-verify",
        "assimilate": "source-assimilate", "final_scope": "source-final-scope"}
    for note in origin.continuation["terminal_coverage_receipts"]:
        receipt = json.loads(note.split(": ", 1)[1])
        assert receipt.get("schema_valid") is True, receipt
        suffix = phase_slices[receipt["phase"]]
        calls = [call for call in account["calls"] if call["slice_id"].endswith(":" + suffix)]
        assert calls, (suffix, [call["slice_id"] for call in account["calls"]])
        incoming, outgoing = (sum(call["usage"][key] for call in calls) for key in ("input_tokens", "output_tokens"))
        receipt.update(host_client="codex", input_sha256="a" * 64, response_sha256="b" * 64,
            input_tokens=incoming, output_tokens=outgoing, total_tokens=incoming + outgoing,
            native_attempts=[{"status": "completed", "terminal": "completed", "model_dispatched": True,
                "unknown_response_usage_count": 0, "input_sha256": "a" * 64, "response_text_sha256": "b" * 64}])
        receipts.append("dream source coverage receipt: " + json.dumps(receipt))
    origin.continuation["terminal_coverage_receipts"] = receipts
    run(backend.structured_store.save_dream_run(origin))
    reflection.status = "retryable"
    backend.reflection_job_store.save(reflection)
    final_reflection = ReflectionJob(id="partial-final-reflection", project_name="demo", project_root=str(root),
        kind="dream", source="ide_hook", status="failed", completed_at=datetime.now(timezone.utc),
        input_refs=[origin.id, job.id])
    backend.reflection_job_store.save(final_reflection)
    carrier = run(backend.structured_store.get_dream_run(carrier.id))
    carrier.status, carrier.completed_at = "failed", datetime.now(timezone.utc)
    carrier.reflection_job_id = final_reflection.id
    carrier.continuation["terminal_source_coverage"] = {f"{origin.id}:{origin.items[0].source_id}": result}
    run(backend.structured_store.save_dream_run(carrier))
    fresh_reflection = ReflectionJob(id="partial-new-reflection", project_name="demo", project_root=str(root),
        kind="dream", source="ide_hook", status="processing", input_refs=[origin.id, job.id])
    backend.reflection_job_store.save(fresh_reflection)
    fresh = DreamRun(id="partial-new-carrier", project_name="demo", status="processing", trigger_source="ide_hook",
        reflection_job_id=fresh_reflection.id, continuation={"version": "dream-slices-v3", "slice_count": 1,
        "max_slices": 2, "target_ids": [], "signals": [], "terminal_source_coverage_origin_run_id": origin.id,
        "maintenance_scope": dict(origin.continuation["maintenance_scope"])})
    run(backend.structured_store.save_dream_run(fresh))
    provider = AccountedProvider(no_candidate=True)
    provider.bind_task_budget(bindings[0], phase="dream", slice_id=f"dream:{fresh.id}:1")
    data = backend, root, origin, fresh, job, provider, config, bindings
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=origin.id, item=origin.items[0], checkpoint=origin.continuation, notes=origin.notes))
    return data, prepared, copy.deepcopy(state), carrier


def proof(partial):
    data, prepared, _old, _carrier = partial
    backend, _root, origin, fresh, _job, _provider, config, _bindings = data
    return run(owner._prove_partial_retry(backend, origin=origin, item=origin.items[0], prepared=prepared,
        config=config, host_client="codex", active_carrier_id=fresh.id))


def test_partial_revalidation_is_content_free_and_requires_live_proof(partial):
    data, prepared, state, _closed = partial
    assert owner._coverage_pending(state)
    with pytest.raises(ValueError, match="partial_preflight_required"):
        owner._state_for_binding(state, prepared["binding"])
    verified = proof(partial)
    assert len(verified["committed_truth"]) == 3 and len(verified["deferred"]) == 1
    new = owner._state_for_binding(state, prepared["binding"], partial_proof=verified)
    assert new["candidate_ids"] == [] and new["commit_bindings"] == []
    old = new["previous_contract_attempts"][-1]
    assert old["commit_bindings"] == state["commit_bindings"] and old["candidate_outcomes"] == state["candidate_outcomes"]
    assert old["partial_revalidation"]["state_sha256"] == owner._digest(state)
    assert "acceptance rituals" not in json.dumps(new)
    assert data[2].status == "failed"


def test_fresh_contract_does_not_replay_prior_adds_or_change_old_workspaces(partial):
    data, _prepared, old_state, _closed = partial
    backend, _root, origin, _fresh, _job, provider, _config, bindings = data
    canonical = backend.structured_store._canonical
    truth_ids = old_state["commit_bindings"][0]["truth_ids"]
    before = {i: canonical.get_payload_json("knowledge_entries", i) for i in truth_ids}
    old_claims = copy.deepcopy(origin.continuation["terminal_coverage_takeover"]["claims"])
    old_candidates = [run(backend.structured_store.knowledge_store.get_candidate(i)).to_dict() for i in old_state["candidate_ids"]]
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    result = invoke(data)
    assert result["status"] == "no_write", result
    assert provider.calls == ["decide", "candidate_verify"]
    saved = run(backend.structured_store.get_dream_run(origin.id))
    state = saved.continuation["source_coverage"][origin.items[0].source_id]
    assert state["binding"]["contract"] == owner.CONTRACT
    assert {i: canonical.get_payload_json("knowledge_entries", i) for i in truth_ids} == before
    assert [run(backend.structured_store.knowledge_store.get_candidate(i)).to_dict() for i in old_state["candidate_ids"]] == old_candidates
    assert all(saved.continuation["terminal_coverage_takeover"]["claims"][key] == value for key, value in old_claims.items())
    assert saved.continuation["max_slices"] == origin.continuation["max_slices"]
    current = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert current["calls"][:-2] == account["calls"]
    invoke(data)
    assert provider.calls == ["decide", "candidate_verify"]


@pytest.mark.parametrize("fault", ["truth", "source", "candidate", "reason", "native_phase", "current_final",
    "old_yield", "binding", "committing", "failed", "unknown", "active", "limit"])
def test_partial_revalidation_faults_never_claim_or_dispatch(partial, fault):
    data, _prepared, _state, closed = partial
    backend, _root, origin, _fresh, _job, provider, _config, bindings = data
    canonical = backend.structured_store._canonical
    state = origin.continuation["source_coverage"][origin.items[0].source_id]
    identity = state["commit_bindings"][0]["truth_ids"][0]
    if fault in {"truth", "source"}:
        collection = "knowledge_entries" if fault == "truth" else "knowledge_sources"
        target = identity if fault == "truth" else run(backend.structured_store.knowledge_store.list_sources(identity))[0].id
        payload = json.loads(canonical.get_payload_json(collection, target))
        payload["statement" if fault == "truth" else "content_sha256"] = "Changed retained contents." if fault == "truth" else "f" * 64
        canonical.apply_payload_transaction(idempotency_key="isolated-changed-partial", mutations=[{
            "operation": "upsert", "collection": collection, "entity_id": target, "payload": payload}])
    elif fault == "candidate":
        row = run(backend.structured_store.knowledge_store.get_candidate(state["candidate_ids"][0]))
        row.statement += " Changed."
        run(backend.structured_store.knowledge_store.save_candidate(row))
    elif fault == "reason":
        directory = backend.data_dir / "job_workspaces/knowledge/decisions"
        for path in directory.glob("*.json"):
            wrapper = json.loads(path.read_text())
            if wrapper["data"].get("candidate_id") == state["candidate_ids"][1]:
                wrapper["data"]["reason"] = "A different semantic rejection."
                path.write_text(json.dumps(wrapper))
    elif fault == "native_phase":
        origin.continuation["terminal_coverage_receipts"] = origin.continuation["terminal_coverage_receipts"][:-1]
    elif fault in {"current_final", "old_yield"}:
        reflection_id = closed.reflection_job_id if fault == "current_final" else next(iter(origin.continuation["terminal_coverage_takeover"]["claims"].values()))["carrier_reflection_id"]
        row = backend.reflection_job_store.get(reflection_id)
        row.status = "processing"
        backend.reflection_job_store.save(row)
    elif fault == "binding":
        state["binding"]["context_sha256"] = "changed"
        state["binding_sha256"] = owner._digest(state["binding"])
    elif fault == "committing":
        state["commit_bindings"][0]["status"] = "committing"
    elif fault == "failed":
        state["status"] = "failed"
    elif fault in {"active", "unknown"}:
        path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
        receipt = json.loads(path.read_text())
        receipt["calls"][-1]["status" if fault == "active" else "usage_exact"] = "reserved" if fault == "active" else False
        path.write_text(json.dumps(receipt))
    else:
        claims = origin.continuation["terminal_coverage_takeover"]["claims"]
        while len(claims) < origin.continuation["max_slices"] - origin.continuation["slice_count"]:
            claims[f"consumed-{len(claims)}"] = {"status": "failed"}
        origin.continuation["terminal_coverage_takeover"]["slice_count"] = len(claims)
    run(backend.structured_store.save_dream_run(origin))
    before = canonical.get_payload_json("dream_runs", origin.id)
    result = invoke(data)
    assert not result["worked"] and provider.calls == [], result
    assert canonical.get_payload_json("dream_runs", origin.id) == before


def test_retained_truth_race_is_rejected_by_the_same_claim_transaction(partial, monkeypatch):
    data, _prepared, state, _closed = partial
    backend, _root, origin, _fresh, _job, provider, *_ = data
    canonical, identity = backend.structured_store._canonical, state["commit_bindings"][0]["truth_ids"][0]
    actual = canonical.apply_payload_transaction
    changed = []
    def race(*args, **kwargs):
        if not changed:
            raw = json.loads(canonical.get_payload_json("knowledge_entries", identity))
            raw["statement"] += " Concurrent change survives."
            actual(idempotency_key="isolated-partial-cas-race", mutations=[{"operation": "upsert",
                "collection": "knowledge_entries", "entity_id": identity, "payload": raw}])
            changed.append(True)
        return actual(*args, **kwargs)
    monkeypatch.setattr(canonical, "apply_payload_transaction", race)
    before = canonical.get_payload_json("dream_runs", origin.id)
    result = invoke(data)
    assert result["reason"] == "terminal_coverage_checkpoint_changed" and provider.calls == [], result
    assert canonical.get_payload_json("dream_runs", origin.id) == before
    assert "Concurrent change survives" in canonical.get_payload_json("knowledge_entries", identity)
