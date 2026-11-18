"""Known exhausted report accounts close locally; transports and live stores are forbidden."""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal
from test_terminal_report_carrier_integration import report_terminal as report_terminal
from test_terminal_report_continuation import prepared as prepared, claim, run
from harness_mem.commands import dream_continuation as continuation, dream_report_continuation as report
from harness_mem.commands.dream_source_coverage import _terminal_fixed
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, task_budget_receipt_path
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


@pytest.fixture
def exhausted(prepared, monkeypatch):
    return ready_exhausted(prepared, monkeypatch)


def ready_exhausted(prepared, monkeypatch, *, context=None):
    data, _child = prepared
    backend, root, origin, _old, job, provider, config, bindings = data[0]
    context = context or claim(prepared)
    child = context["carrier"]
    child.status = child.execution_status = "continuing"
    child.notes = ["Preserve the existing report progress."]
    run(context["persist"](child))
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    reflection.status, reflection.phase = "retryable", "metabolism"
    reflection.input_refs = [child.id, origin.id, job.id]
    backend.reflection_job_store.save(reflection)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    receipt = json.loads(path.read_text())
    receipt["calls"][0]["usage"]["output_tokens"] = config.task_model_budget_max_output_tokens
    path.write_text(json.dumps(receipt))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("terminal bookkeeping must never construct a provider or dispatch")

    monkeypatch.setattr("harness_mem.commands.dream._dream_provider_from_config", forbidden)
    return backend, root, origin, child, job, provider, config, bindings, path


def close(data):
    backend, root, _origin, child, job, _provider, config, _bindings, _path = data
    return run(report.close_exhausted_report_child(backend, child_run_id=child.id, project_name="demo",
        project_root=root, config=config, host_client="codex", generation="original-generation", trigger_id=job.session_id))


def snapshot(data):
    backend, _root, origin, child, *_ = data
    canonical = backend.structured_store._canonical
    return (canonical.get_payload_json("dream_runs", origin.id),
        canonical.get_payload_json("dream_runs", child.id),
        [entry.model_dump(mode="json") for entry in run(backend.structured_store.knowledge_store.list_entries("demo"))],
        data[-1].read_bytes(), backend.reflection_job_store.get(child.reflection_job_id).to_dict())


def test_exhausted_closure_preserves_progress_claim_count_items_sources_and_account(exhausted):
    backend, _root, origin, child, job, provider, _config, bindings, _path = exhausted
    before = snapshot(exhausted)
    original = run(backend.structured_store.get_dream_run(origin.id))
    source = backend.transcript_store.get_distill_job(job.id).to_dict()
    fresh_account = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    result = close(exhausted)
    assert result["status"] == "failed" and result["resolution_status"] == "unresolved"
    assert result["completed_target_count"] == 0 and result["target_count"] == 1
    assert result["remaining_target_ids"] == child.continuation["target_ids"]
    parent = run(backend.structured_store.get_dream_run(origin.id))
    saved = run(backend.structured_store.get_dream_run(child.id))
    assert _terminal_fixed(parent) == _terminal_fixed(original)
    assert parent.items == original.items and parent.notes == original.notes
    ledger = parent.continuation["terminal_coverage_takeover"]
    old_ledger = original.continuation["terminal_coverage_takeover"]
    assert ledger["slice_count"] == old_ledger["slice_count"] == len(ledger["claims"]) == 1
    assert next(iter(ledger["claims"].values()))["status"] == "failed"
    attempt = next(iter(ledger["report_attempts"].values()))
    assert attempt["status"] == "failed" and attempt["remaining_ids"] == result["remaining_target_ids"]
    assert saved.status == "failed" and saved.execution_status == "failed" and saved.resolution_status == "unresolved"
    assert saved.continuation["completed_signal_indexes"] == child.continuation["completed_signal_indexes"]
    assert saved.continuation["slice_count"] == child.continuation["slice_count"]
    assert saved.notes == child.notes and saved.items == child.items
    after = snapshot(exhausted)
    assert before[2:] == after[2:]
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == source
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == fresh_account
    assert not provider.calls


def test_wake_queues_original_pointer_then_detached_runner_closes_without_model(exhausted, monkeypatch):
    backend, root, origin, child, job, _provider, config, *_ = exhausted
    dispatched = []

    def queue(*args, **kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(spawned=True, coalesced=False)

    monkeypatch.setattr("harness_mem.hook_background.dispatch_bound_continuation", queue)
    queued = run(continuation.enqueue_bound_continuation(backend, project_name="demo", project_root=str(root),
        config=config, host_client="codex"))
    assert queued["status"] == "queued" and queued["run_id"] == origin.id
    assert dispatched[0]["generation"] == "original-generation" and dispatched[0]["resume_run_id"] == origin.id
    outcome = run(continuation.run_bound_continuation(backend, project_name="demo", project_root=str(root),
        config=config, host_client="codex", resume_run_id=origin.id, trigger_id=job.session_id))
    assert outcome["status"] == "failed", outcome
    assert outcome["dream_tick"]["run_id"] == child.id
    assert outcome["dream_tick"]["reason"] == "continuation_budget_exhausted"


@pytest.mark.parametrize("fault", ["unknown", "active", "host", "bounds", "manifest", "claim", "reflection", "source",
    "retryable_lease", "processing", "retryable_phase"])
def test_invalid_exhausted_binding_never_closes_or_dispatches(exhausted, fault, monkeypatch):
    backend, _root, origin, child, job, _provider, _config, _bindings, path = exhausted
    if fault in {"unknown", "active", "host", "bounds"}:
        receipt = json.loads(path.read_text())
        if fault == "unknown":
            receipt["calls"][0]["usage_exact"] = False
        elif fault == "active":
            receipt["calls"][0]["status"] = "reserved"
        elif fault == "host":
            receipt["host_client"] = "hermes"
        else:
            receipt["bounds"]["max_calls"] += 1
        path.write_text(json.dumps(receipt))
    elif fault == "manifest":
        child.continuation["terminal_report_manifest_sha256"] = "0" * 64
        run(backend.structured_store.save_dream_run(child))
    elif fault == "claim":
        parent = run(backend.structured_store.get_dream_run(origin.id))
        next(iter(parent.continuation["terminal_coverage_takeover"]["claims"].values()))["carrier_reflection_id"] = "different-owner"
        run(backend.structured_store.save_dream_run(parent))
    elif fault in {"reflection", "retryable_lease", "processing", "retryable_phase"}:
        owner = backend.reflection_job_store.get(child.reflection_job_id)
        if fault == "reflection":
            owner.input_refs = [origin.id]
        elif fault == "retryable_lease":
            owner.lease_owner = "another-worker"
        elif fault == "processing":
            owner.status = "processing"
        else:
            owner.phase = "ingest"
        backend.reflection_job_store.save(owner)
    else:
        native = backend.transcript_store.get_distill_job(job.id)
        native.status = "failed"
        original = backend.transcript_store.get_distill_job
        monkeypatch.setattr(backend.transcript_store, "get_distill_job", lambda identity:
            native if identity == job.id else original(identity))
    before = snapshot(exhausted)
    with pytest.raises(ValueError):
        close(exhausted)
    assert snapshot(exhausted) == before


def test_nonexhausted_account_has_no_terminal_mutation(exhausted):
    path = exhausted[-1]
    receipt = json.loads(path.read_text())
    receipt["calls"][0]["usage"]["output_tokens"] = 1
    path.write_text(json.dumps(receipt))
    before = snapshot(exhausted)
    assert close(exhausted) == {}
    assert snapshot(exhausted) == before


def test_terminal_close_exposes_existing_independent_source_origin(exhausted, monkeypatch):
    backend, root, origin, _child, job, _provider, config, bindings, _path = exhausted
    source_origin = origin.model_copy(deep=True)
    source_origin.id = "independent-source-origin"
    source_origin.started_at += timedelta(seconds=1)
    source_origin.continuation["source_coverage_pending_ids"] = [source_origin.items[0].source_id]
    source_origin.continuation["maintenance_scope"]["dispatch_generation"] = "carrier-generation"
    source_origin.notes = [note.replace(job.id, "carrier-source-job") for note in source_origin.notes]
    run(backend.structured_store.save_dream_run(source_origin))
    before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    dispatched = []
    monkeypatch.setattr("harness_mem.hook_background.dispatch_bound_continuation", lambda *args, **kwargs:
        (dispatched.append(kwargs) or SimpleNamespace(spawned=True, coalesced=False)))
    close(exhausted)
    result = run(continuation.enqueue_bound_continuation(backend, project_name="demo", project_root=str(root),
        config=config, host_client="codex"))
    assert result["status"] == "queued", result
    assert result["run_id"] == source_origin.id
    assert dispatched[0]["generation"] == "carrier-generation"
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == before


def test_eight_of_twenty_four_progress_is_retained_without_new_slice(report_terminal, monkeypatch):
    data, case, _rendered = report_terminal
    backend, _root, _origin, _old, _job, _provider, _config, _bindings = data
    canonical = backend.structured_store._canonical
    entry = case[3]
    sources = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    for index in range(23):
        identity = f"report-progress-{index:02d}"
        payload = json.loads(canonical.get_payload_json("knowledge_entries", entry.id))
        payload["id"] = identity
        mutations = [{"operation": "upsert", "collection": "knowledge_entries", "entity_id": identity, "payload": payload}]
        for source in sources:
            source_payload = json.loads(canonical.get_payload_json("knowledge_sources", source.id))
            source_payload.update(id=f"{source.id}-{index}", knowledge_id=identity)
            mutations.append({"operation": "upsert", "collection": "knowledge_sources",
                "entity_id": source_payload["id"], "payload": source_payload})
        canonical.apply_payload_transaction(idempotency_key=f"fixture-report-{index}", mutations=mutations)
    prepared_data = prepared.__wrapped__(report_terminal)
    bound = claim(prepared_data)
    child = bound["carrier"]
    child.continuation["completed_signal_indexes"] = list(range(8))
    run(bound["persist"](child))
    # Build the same continuing/retryable/exhausted fixture after frozen progress.
    exhausted_data = ready_exhausted((report_terminal, child), monkeypatch, context=bound)
    before = snapshot(exhausted_data)
    result = close(exhausted_data)
    assert result["completed_target_count"] == 8 and result["target_count"] == 24
    assert len(result["remaining_target_ids"]) == 16
    saved = run(backend.structured_store.get_dream_run(child.id))
    assert saved.continuation["completed_signal_indexes"] == list(range(8))
    assert snapshot(exhausted_data)[2:] == before[2:]


@pytest.mark.parametrize("owner", ["origin", "child"])
def test_exhausted_closure_dual_cas_keeps_concurrent_owner(exhausted, monkeypatch, owner):
    backend, _root, origin, child, *_ = exhausted
    canonical = backend.structured_store._canonical
    actual = canonical.apply_payload_transaction
    identity = origin.id if owner == "origin" else child.id
    injected = []

    def race(*args, **kwargs):
        if not injected:
            injected.append(True)
            row = json.loads(canonical.get_payload_json("dream_runs", identity))
            row["notes"] = ["Concurrent owner must survive."]
            actual(idempotency_key="exhausted-race", mutations=[{"operation": "upsert", "collection": "dream_runs",
                "entity_id": identity, "payload": row}])
        return actual(*args, **kwargs)

    monkeypatch.setattr(canonical, "apply_payload_transaction", race)
    with pytest.raises(CanonicalTransactionPreconditionError):
        close(exhausted)
    assert run(backend.structured_store.get_dream_run(identity)).notes == ["Concurrent owner must survive."]
    assert run(backend.structured_store.get_dream_run(child.id)).status == "continuing"
