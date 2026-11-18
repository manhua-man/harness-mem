"""One exact old zero outcome can acquire the inventory contract, without replay."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal, AccountedProvider, invoke, run
from test_source_coverage_partial_contract import partial as partial
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, task_budget_receipt_path


@pytest.fixture
def zero(partial, monkeypatch):
    data, _prepared, _state, _closed = partial
    backend, root, origin, carrier, job, provider, config, bindings = data
    with monkeypatch.context() as old:
        old.setattr(owner, "CONTRACT", "dream-applied-source-coverage-v4")
        result = invoke(data)
    assert result["status"] == "no_write", result
    origin = run(backend.structured_store.get_dream_run(origin.id))
    state = origin.continuation["source_coverage"][origin.items[0].source_id]
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    for index, note in enumerate(origin.continuation["terminal_coverage_receipts"]):
        receipt = json.loads(note.split(": ", 1)[1])
        if receipt.get("attempt_id") != state["binding_sha256"]:
            continue
        calls = [call for call in account["calls"] if call["slice_id"].startswith(
            f"source-coverage:{origin.id}:{state['binding_sha256']}:")]
        assert len(calls) == 1
        incoming, outgoing = (calls[0]["usage"][key] for key in ("input_tokens", "output_tokens"))
        receipt.update(host_client="codex", input_sha256="a" * 64, response_sha256="b" * 64,
            input_tokens=incoming, output_tokens=outgoing, total_tokens=incoming + outgoing,
            native_attempts=[{"status": "completed", "terminal": "completed", "model_dispatched": True,
                "unknown_response_usage_count": 0, "input_sha256": "a" * 64,
                "response_text_sha256": "b" * 64}])
        origin.continuation["terminal_coverage_receipts"][index] = "dream source coverage receipt: " + json.dumps(receipt)
    run(backend.structured_store.save_dream_run(origin))
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    reflection.status, reflection.completed_at = "completed", datetime.now(timezone.utc)
    backend.reflection_job_store.save(reflection)
    carrier = run(backend.structured_store.get_dream_run(carrier.id))
    carrier.status, carrier.completed_at = "completed", datetime.now(timezone.utc)
    carrier.continuation["terminal_source_coverage"] = {f"{origin.id}:{origin.items[0].source_id}": result}
    run(backend.structured_store.save_dream_run(carrier))
    new_ref = ReflectionJob(id="zero-new-reflection", project_name="demo", project_root=str(root),
        kind="dream", source="ide_hook", status="processing", input_refs=[origin.id, job.id])
    backend.reflection_job_store.save(new_ref)
    fresh = DreamRun(id="zero-new-carrier", project_name="demo", status="processing", trigger_source="ide_hook",
        reflection_job_id=new_ref.id, continuation={"version": "dream-slices-v3", "slice_count": 1,
        "max_slices": 2, "target_ids": [], "signals": [], "terminal_source_coverage_origin_run_id": origin.id,
        "maintenance_scope": dict(origin.continuation["maintenance_scope"])})
    run(backend.structured_store.save_dream_run(fresh))
    provider = AccountedProvider(no_candidate=True)
    provider.bind_task_budget(bindings[0], phase="dream", slice_id=f"dream:{fresh.id}:1")
    return (backend, root, origin, fresh, job, provider, config, bindings), copy.deepcopy(state), carrier


def test_v4_zero_requires_proof_and_preserves_partial_truth_workspaces_and_account(zero):
    data, old, _closed = zero
    backend, root, origin, fresh, _job, provider, config, bindings = data
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=origin.id, item=origin.items[0], checkpoint=origin.continuation, notes=origin.notes))
    assert owner._coverage_pending(old)
    with pytest.raises(ValueError, match="zero_preflight_required"):
        owner._state_for_binding(old, prepared["binding"])
    proof = run(owner._prove_zero_retry(backend, origin=origin, item=origin.items[0], prepared=prepared,
        config=config, host_client="codex", active_carrier_id=fresh.id))
    assert len(proof["closed_claims"]) == 1 and len(proof["retained_partial_sha256"]) == 1
    canonical = backend.structured_store._canonical
    retained = old["previous_contract_attempts"][-1]["partial_revalidation"]
    before = {row["entry_id"]: canonical.get_payload_json("knowledge_entries", row["entry_id"])
        for row in retained["committed_truth"]}
    claims = copy.deepcopy(origin.continuation["terminal_coverage_takeover"]["claims"])
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    result = invoke(data)
    assert result["status"] == "no_write" and provider.calls == ["decide", "candidate_verify"], result
    saved = run(backend.structured_store.get_dream_run(origin.id))
    state = saved.continuation["source_coverage"][origin.items[0].source_id]
    assert state["binding"]["contract"] == owner.CONTRACT
    assert state["previous_contract_attempts"][:-1] == old["previous_contract_attempts"]
    assert state["previous_contract_attempts"][-1]["decision_sha256"] == old["decision_sha256"]
    assert state["previous_contract_attempts"][-1]["zero_revalidation"] == proof
    assert all(saved.continuation["terminal_coverage_takeover"]["claims"][key] == value for key, value in claims.items())
    assert saved.continuation["max_slices"] == origin.continuation["max_slices"]
    assert {identity: canonical.get_payload_json("knowledge_entries", identity) for identity in before} == before
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)["calls"][:-2] == account["calls"]
    invoke(data)
    assert provider.calls == ["decide", "candidate_verify"]


def test_authored_inventory_is_exact_per_message_with_original_anchor_and_packet(zero):
    data, _old, _closed = zero
    backend, root, origin, *_ = data
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=origin.id, item=origin.items[0], checkpoint=origin.continuation, notes=origin.notes))
    windows = {row["exchange_index"]: row for row in prepared["packet"]["semantic_decision_exchanges"]}
    _revision, rendering, _raw = owner._source_report_context(backend, project_name="demo",
        source_id=prepared["binding"]["source_id"], source_revision=prepared["binding"]["source_revision"])
    exchanges = owner._parse_exchanges(rendering)[1]
    expected = [(index, offset, message) for index, exchange in enumerate(exchanges, 1)
        if index in windows for offset, message in enumerate(exchange["user"])]
    actual = prepared["authored_user_exchanges"]
    assert [(row["exchange_index"], row["message_index"], row["text"]) for row in actual] == expected
    assert all(row["role"] == "user" and row["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        and row["anchor_sha256"] == windows[row["exchange_index"]]["content_sha256"] for row in actual)
    assert prepared["comparison_current_truth"] == []


@pytest.mark.parametrize("fault", ["candidate", "commit", "reason", "decision", "binding", "claim",
    "carrier", "reflection", "lease", "native_phase", "native_hash", "unknown", "limit", "truth", "handoff", "history"])
def test_v4_zero_fault_does_not_claim_or_dispatch(zero, fault):
    data, _old, closed = zero
    backend, _root, origin, _fresh, _job, provider, _config, bindings = data
    canonical = backend.structured_store._canonical
    state = origin.continuation["source_coverage"][origin.items[0].source_id]
    if fault == "candidate":
        state["candidate_ids"] = ["unexpected-candidate"]
    elif fault == "commit":
        state["commit_bindings"] = [{"status": "committing"}]
    elif fault == "reason":
        state["reason_code"] = "source_coverage_partial_resolution"
    elif fault == "decision":
        state["decision_sha256"] = "not-a-digest"
    elif fault == "binding":
        state["binding"]["context_sha256"] = "e" * 64
        state["binding_sha256"] = owner._digest(state["binding"])
    elif fault == "claim":
        next(row for row in origin.continuation["terminal_coverage_takeover"]["claims"].values()
            if row["source_binding_sha256"] == state["binding_sha256"])["status"] = "claimed"
    elif fault == "carrier":
        closed.status = "processing"
        run(backend.structured_store.save_dream_run(closed))
    elif fault in {"reflection", "lease"}:
        row = backend.reflection_job_store.get(closed.reflection_job_id)
        if fault == "reflection":
            row.status = "processing"
        else:
            row.lease_owner = "unexpected-owner"
        backend.reflection_job_store.save(row)
    elif fault in {"native_phase", "native_hash"}:
        for index, note in enumerate(origin.continuation["terminal_coverage_receipts"]):
            receipt = json.loads(note.split(": ", 1)[1])
            if receipt["attempt_id"] == state["binding_sha256"]:
                if fault == "native_phase":
                    receipt["phase"] = "candidate_verify"
                else:
                    receipt["native_attempts"][0]["input_sha256"] = "c" * 64
                origin.continuation["terminal_coverage_receipts"][index] = "dream source coverage receipt: " + json.dumps(receipt)
    elif fault == "unknown":
        path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
        receipt = json.loads(path.read_text())
        receipt["calls"][-1]["usage_exact"] = False
        path.write_text(json.dumps(receipt))
    elif fault == "limit":
        claims = origin.continuation["terminal_coverage_takeover"]["claims"]
        while len(claims) < origin.continuation["max_slices"] - origin.continuation["slice_count"]:
            claims[f"consumed-{len(claims)}"] = {"status": "failed"}
        origin.continuation["terminal_coverage_takeover"]["slice_count"] = len(claims)
    else:
        proof = state["previous_contract_attempts"][-1]["partial_revalidation"]
        if fault == "history":
            proof["binding_sha256"] = "d" * 64
        else:
            collection = "knowledge_entries" if fault == "truth" else "task_handoffs"
            identity = proof["committed_truth"][0]["entry_id"] if fault == "truth" else proof["deferred"][0]["handoff_id"]
            payload = json.loads(canonical.get_payload_json(collection, identity))
            payload["statement" if fault == "truth" else "title"] = "Changed retained content."
            canonical.apply_payload_transaction(idempotency_key="isolated-zero-change", mutations=[{
                "operation": "upsert", "collection": collection, "entity_id": identity, "payload": payload}])
    run(backend.structured_store.save_dream_run(origin))
    before = canonical.get_payload_json("dream_runs", origin.id)
    result = invoke(data)
    assert not result["worked"] and provider.calls == [], result
    assert canonical.get_payload_json("dream_runs", origin.id) == before


def test_v5_claim_transaction_freezes_the_historical_partial_truth(zero, monkeypatch):
    data, old, _closed = zero
    backend, _root, origin, _fresh, _job, provider, *_ = data
    canonical = backend.structured_store._canonical
    identity = old["previous_contract_attempts"][-1]["partial_revalidation"]["committed_truth"][0]["entry_id"]
    actual, changed = canonical.apply_payload_transaction, []
    def race(*args, **kwargs):
        if not changed:
            payload = json.loads(canonical.get_payload_json("knowledge_entries", identity))
            payload["statement"] += " Concurrent revision survives."
            actual(idempotency_key="isolated-zero-cas-race", mutations=[{"operation": "upsert",
                "collection": "knowledge_entries", "entity_id": identity, "payload": payload}])
            changed.append(True)
        return actual(*args, **kwargs)
    monkeypatch.setattr(canonical, "apply_payload_transaction", race)
    before = canonical.get_payload_json("dream_runs", origin.id)
    result = invoke(data)
    assert result["reason"] == "terminal_coverage_checkpoint_changed" and provider.calls == [], result
    assert canonical.get_payload_json("dream_runs", origin.id) == before
    assert "Concurrent revision survives" in canonical.get_payload_json("knowledge_entries", identity)
