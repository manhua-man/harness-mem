"""Explicit source repair uses isolated stores and the existing fake transport."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, task_budget_receipt_path
from harness_mem.autonomous.provider import ProviderError


def run(value):
    return asyncio.run(value)


@pytest.fixture
def repair(terminal, monkeypatch):
    backend, root, old, carrier, job, provider, config, bindings = terminal
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    manifest = run(owner.prepare_explicit_source_repair(backend, project_name="demo", project_root=root,
        run_id="new-explicit", origin_run_id=old.id, predecessor_ids=[old.items[0].source_id]))
    checkpoint = {"slice_count": 1, "maintenance_scope": carrier.continuation["maintenance_scope"]}
    return terminal, manifest, checkpoint


def invoke(repair, *, provider=None, boundary=None):
    data, manifest, checkpoint = repair
    backend, root, _old, _carrier, _job, selected, _config, _bindings = data
    async def persist():
        checkpoint["persist_count"] = checkpoint.get("persist_count", 0) + 1
    return run(owner.run_explicit_source_repair(backend, project_name="demo", project_root=root,
        run_id="new-explicit", manifest=manifest, checkpoint=checkpoint, notes=[],
        provider=provider or selected, persist=persist, boundary=boundary))


def test_explicit_repair_freezes_source_and_commits_in_fresh_namespace(repair):
    data, manifest, checkpoint = repair
    backend, root, old, _carrier, job, provider, _config, bindings = data
    canonical = backend.structured_store._canonical
    oldraw = canonical.get_payload_json("dream_runs", old.id)
    oldaccount = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    frozen = manifest["source_bindings"][old.items[0].source_id]
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id="new-explicit", item=old.items[0], checkpoint=old.continuation, notes=old.notes,
        include_current_comparison=True))
    assert len(prepared["authored_user_exchanges"]) == 78
    assert frozen["binding"]["run_id"] == "new-explicit"
    assert frozen["binding"]["source_job_id"] == prepared["job"].id
    assert frozen["binding"]["source_revision"] == job.source_revision
    assert manifest["origin_payload_sha256"] == hashlib.sha256(oldraw.encode()).hexdigest()
    result = invoke(repair)
    assert result == {"worked": True, "pending": False, "status": "applied"}
    state = checkpoint["repair_source_coverage"]["source_coverage"][old.items[0].source_id]
    assert state["binding"]["run_id"] == "new-explicit" and state["candidate_ids"]
    assert state["commit_bindings"]
    assert canonical.get_payload_json("dream_runs", old.id) == oldraw
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope) == oldaccount
    calls = len(provider.calls)
    assert invoke(repair)["worked"] is False
    assert len(provider.calls) == calls


def test_repair_accepts_known_exhausted_old_account_without_reusing_it(terminal, monkeypatch):
    backend, root, old, _carrier, _job, _provider, config, bindings = terminal
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(path.read_text())
    account["calls"][0]["usage"]["output_tokens"] = config.task_model_budget_max_output_tokens + 1
    path.write_text(json.dumps(account), encoding="utf-8")
    original = path.read_bytes()
    manifest = run(owner.prepare_explicit_source_repair(backend, project_name="demo", project_root=root,
        run_id="new-explicit", origin_run_id=old.id, predecessor_ids=[old.items[0].source_id]))
    assert manifest["origin_task_scope"] == bindings[0].task_scope
    assert path.read_bytes() == original


@pytest.mark.parametrize("status", ["failed", "active"])
def test_exact_failed_unknown_is_preserved_but_active_old_usage_refuses(terminal, monkeypatch, status):
    backend, root, old, _carrier, _job, _provider, config, bindings = terminal
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(path.read_text())
    now = time.time()
    account["calls"].append({"call_id": "old-terminal-unknown", "status": status,
        "phase": "dream", "slice_id": "old-failure", "usage_exact": False,
        "usage": {"input_tokens": None, "output_tokens": None, "duration_seconds": None},
        "model_completion": False, "reserved_at": now - 1, "reconciled_at": now})
    path.write_text(json.dumps(account), encoding="utf-8")
    original = path.read_bytes()
    async def prepare():
        return await owner.prepare_explicit_source_repair(backend, project_name="demo", project_root=root,
            run_id="new-explicit", origin_run_id=old.id, predecessor_ids=[old.items[0].source_id])
    if status == "failed":
        manifest = run(prepare())
        assert manifest["origin_account_sha256"] == owner._digest(account)
        result = invoke((terminal, manifest, {"slice_count": 1}))
        assert result["status"] == "applied"
    else:
        with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
            run(prepare())
    assert path.read_bytes() == original


def test_comparison_entry_change_during_final_vote_prevents_all_repair_writes(terminal, monkeypatch):
    from test_source_coverage_current_comparison import seed
    # Reconstruct the captured tuple used by the common comparison fixture.
    backend, root, old, _carrier, _job, provider, config, _bindings = terminal
    entry = run(backend.structured_store.knowledge_store.get_entry("narrow-successor",
        project_name="demo", project_root=root))
    refs = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    comparison, _refs = seed((backend, root, None, None, refs), identity="read-only-comparison")
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    manifest = run(owner.prepare_explicit_source_repair(backend, project_name="demo", project_root=root,
        run_id="new-explicit", origin_run_id=old.id, predecessor_ids=[old.items[0].source_id]))
    fixture = terminal, manifest, {"slice_count": 1}
    original_verify = provider.verify
    def concurrent_change(manifest, **kwargs):
        result = original_verify(manifest, **kwargs)
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            canonical = backend.structured_store._canonical
            payload = json.loads(canonical.get_payload_json("knowledge_entries", comparison.id))
            payload["statement"] += " Changed during final vote."
            canonical.apply_payload_transaction(idempotency_key="comparison-race", mutations=[{
                "operation": "upsert", "collection": "knowledge_entries", "entity_id": comparison.id,
                "payload": payload}])
        return result
    monkeypatch.setattr(provider, "verify", concurrent_change)
    with pytest.raises(ValueError, match="source_coverage_repair_current_changed"):
        invoke(fixture)
    assert run(backend.structured_store.knowledge_store.get_entry(entry.id,
        project_name="demo", project_root=root)) is not None
    assert not fixture[2]["repair_source_coverage"]["source_coverage"][old.items[0].source_id].get("commit_bindings")


@pytest.mark.parametrize("fault", ["origin", "current", "account", "manifest", "old_account"])
def test_drift_or_old_provider_account_refuses_before_transport(repair, fault):
    data, manifest, _checkpoint = repair
    backend, _root, old, _carrier, _job, provider, _config, bindings = data
    canonical = backend.structured_store._canonical
    if fault == "origin":
        changed = old.model_copy(update={"notes": old.notes + ["Concurrent history change."]})
        run(backend.structured_store.save_dream_run(changed))
    elif fault == "current":
        key = next(iter(manifest["source_bindings"][old.items[0].source_id]["current_rows"]))
        payload = json.loads(canonical.get_payload_json("knowledge_entries", key))
        payload["statement"] += " Concurrent change."
        canonical.apply_payload_transaction(idempotency_key="fixture-drift", mutations=[{
            "operation": "upsert", "collection": "knowledge_entries", "entity_id": key, "payload": payload}])
    elif fault == "account":
        path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
        payload = json.loads(path.read_text())
        payload["calls"][0]["usage"]["output_tokens"] += 1
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif fault == "manifest":
        manifest["source_bindings"][old.items[0].source_id]["binding"]["source_revision"] = "foreign"
    else:
        provider.bind_task_budget(bindings[0], phase="dream", slice_id="forbidden-old")
    with pytest.raises(ValueError):
        invoke(repair)
    assert provider.calls == []


def test_provider_failure_is_rethrown_and_saved_in_new_ledger(repair, monkeypatch):
    provider = repair[0][5]
    failure = ProviderError("Original transport failure.", kind="unrecoverable")
    def fail(*_args, **_kwargs):
        raise failure
    monkeypatch.setattr(provider, "decide", fail)
    with pytest.raises(ProviderError) as caught:
        invoke(repair)
    assert caught.value is failure
    state = repair[2]["repair_source_coverage"]["source_coverage"]
    assert next(iter(state.values()))["status"] == "failed"


def test_independent_confirmation_is_no_write_not_a_restoration(repair):
    repair[0][5].confirm = True
    result = invoke(repair)
    assert result["status"] == "no_write" and result["pending"] is False
    count = len(repair[0][5].calls)
    assert invoke(repair)["worked"] is False
    assert len(repair[0][5].calls) == count


def test_fresh_explicit_repair_does_not_adopt_old_partial_retry_snapshots(terminal, monkeypatch):
    backend, root, old, _carrier, _job, _provider, config, _bindings = terminal
    monkeypatch.setattr("harness_mem.config.merge.load_merged_config", lambda _: config)
    async def obsolete_partial_adoption(*_args, **_kwargs):
        raise AssertionError("Old partial retry snapshots are no longer current and must not be adopted.")
    monkeypatch.setattr(owner, "_assert_partial_history", obsolete_partial_adoption)
    # The old ledger remains frozen history. Only its original applied group's
    # still-current final output and complete original source authorize this
    # fresh check; other historical partial outputs grant no current authority.
    oldraw = backend.structured_store._canonical.get_payload_json("dream_runs", old.id)
    manifest = run(owner.prepare_explicit_source_repair(backend, project_name="demo", project_root=root,
        run_id="new-explicit", origin_run_id=old.id, predecessor_ids=[old.items[0].source_id]))
    result = invoke((terminal, manifest, {"slice_count": 1}))
    assert result["status"] == "applied"
    assert backend.structured_store._canonical.get_payload_json("dream_runs", old.id) == oldraw
