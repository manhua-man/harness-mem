"""Terminal native failures retain receipts without granting another invocation."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from dataclasses import replace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal, AccountedProvider, invoke, run, _idle_carrier
from harness_mem.commands import dream, dream_source_coverage as module
from harness_mem.commands.dream_continuation import _bound_source_account
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, dispatch_with_task_budget, read_task_budget_receipt, task_budget_receipt_path,
)
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


class FailedProvider(AccountedProvider):
    def __init__(self):
        super().__init__()
        self.after_failure = lambda: None
        self.error = None
        self.known_usage = False

    def decide(self, manifest, **kwargs):
        self.calls.append("failed_decide")
        dispatched = dispatch_with_task_budget(self.task_budget_binding,
            phase=self._budget_phase, slice_id=self._budget_slice, timeout_seconds=1,
            transport=lambda _request: NativeDispatchResult(status="failed", input_tokens=20 if self.known_usage else None,
                output_tokens=3 if self.known_usage else None, duration_seconds=1 if self.known_usage else None,
                usage_exact=self.known_usage))
        self._last_budget_call_id = dispatched.call_id
        native = {"call_id": "isolated-native-call", "status": "failed", "terminal": None,
            "model_dispatched": True, "input_sha256": "a" * 64,
            "usage": {"input_tokens": 20 if self.known_usage else None,
                "output_tokens": 3 if self.known_usage else None, "total_tokens": 23 if self.known_usage else None}}
        result = ProviderResult(decision=None, provider="isolated", model="fixture", duration_seconds=1,
            input_sha256="a" * 64, response_sha256="b" * 64, input_tokens=20 if self.known_usage else None,
            output_tokens=3 if self.known_usage else None, total_tokens=23 if self.known_usage else None,
            event_count=1, schema_valid=False, host_client="codex", native_attempts=(native,))
        self.error = ProviderError("Secret source/error prose must not be copied", kind="transient",
            failure_reason="native_call_timeout", attempt_results=(result,), native_attempts=(native,))
        self.after_failure()
        raise self.error


def failing_data(terminal):
    values = list(terminal)
    provider = FailedProvider()
    provider.bind_task_budget(values[-1][1], phase="dream", slice_id="dream:carrier:1", retry_of="keep-retry")
    values[5] = provider
    return tuple(values)


def test_failed_unknown_saves_original_native_receipt_state_claim_and_never_retries(terminal):
    data = failing_data(terminal)
    backend, _root, original, _child, job, provider, _config, bindings = data
    fixed = module._terminal_fixed(original)
    before_knowledge = [entry.to_dict() for entry in run(backend.structured_store.knowledge_store.list_entries("demo"))]
    other_account = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    with pytest.raises(ProviderError) as raised:
        invoke(data)
    assert raised.value is provider.error
    saved = run(backend.structured_store.get_dream_run(original.id))
    assert module._terminal_fixed(saved) == fixed
    state = saved.continuation["source_coverage"][original.items[0].source_id]
    assert state["status"] == "failed" and state["reason_code"] == "native_call_timeout"
    assert saved.continuation["terminal_coverage_takeover"]["claims"]["carrier:1"]["status"] == "failed"
    receipts = [json.loads(note.split(": ", 1)[1]) for note in saved.continuation["terminal_coverage_receipts"]]
    failure = next(row for row in receipts if row["phase"] == "provider_failure")
    assert failure["budget_call_id"] == read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)["calls"][-1]["call_id"]
    assert failure["source_job_id"] == state["binding"]["source_job_id"] and failure["native_attempts"]
    assert "Secret source/error prose" not in json.dumps(saved.to_dict())
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == other_account
    assert [entry.to_dict() for entry in run(backend.structured_store.knowledge_store.list_entries("demo"))] == before_knowledge
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert len(account["calls"]) == 2 and account["calls"][-1]["status"] == "failed"
    assert account["calls"][-1]["usage_exact"] is False
    result = invoke(data)
    assert result["status"] in {"blocked", "skipped"}
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        run(_bound_source_account(backend, run=saved, project_name="demo", project_root=data[1],
            config=data[-2], host_client="codex", require_remaining=False))
    assert provider.calls == ["failed_decide"]


def test_known_paid_failure_retains_usage_and_error_receipt_without_inference_credit(terminal):
    data = failing_data(terminal)
    backend, _root, original, _child, _job, provider, _config, bindings = data
    provider.known_usage = True
    with pytest.raises(ProviderError) as raised:
        invoke(data)
    assert raised.value is provider.error
    saved = run(backend.structured_store.get_dream_run(original.id))
    assert saved.continuation["source_coverage"][original.items[0].source_id]["status"] == "failed"
    receipt = next(json.loads(row.split(": ", 1)[1]) for row in saved.continuation["terminal_coverage_receipts"]
        if json.loads(row.split(": ", 1)[1]).get("phase") == "provider_failure")
    assert receipt["attempt_results"][0]["input_tokens"] == 20
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert account["calls"][-1]["usage_exact"] is True
    assert account["calls"][-1]["usage"] == {"input_tokens": 20, "output_tokens": 3, "duration_seconds": 1.0}
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        run(_bound_source_account(backend, run=saved, project_name="demo", project_root=data[1],
            config=data[-2], host_client="codex", require_remaining=False))
    assert provider.calls == ["failed_decide"]


@pytest.mark.parametrize("fault", ["reserved", "prefix", "scope", "host", "source", "context", "parent_race", "bare_error"])
def test_failed_bookkeeping_refuses_account_context_or_cas_drift_and_keeps_primary_error(terminal, fault, monkeypatch):
    data = failing_data(terminal)
    backend, _root, original, _child, job, provider, _config, bindings = data
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)

    def change():
        if fault in {"reserved", "prefix", "scope", "host"}:
            account = json.loads(path.read_text())
            if fault == "reserved":
                account["calls"][-1]["status"] = "reserved"
            elif fault == "prefix":
                account["calls"][0]["usage"]["input_tokens"] += 1
            elif fault == "scope":
                account["calls"][-1]["slice_id"] = "source-coverage:another-owner:other"
            else:
                account["host_client"] = "hermes"
            path.write_text(json.dumps(account))
        elif fault == "source":
            get = backend.transcript_store.get_distill_job
            monkeypatch.setattr(backend.transcript_store, "get_distill_job", lambda identity:
                get(identity).model_copy(update={"status": "failed"}) if identity == job.id else get(identity))
        elif fault == "context":
            prepare = module._prepare

            async def drift(*args, **kwargs):
                value = await prepare(*args, **kwargs)
                value["authored_user_exchanges"] = []
                return value
            monkeypatch.setattr(module, "_prepare", drift)
        elif fault == "parent_race":
            current = run(backend.structured_store.get_dream_run(original.id))
            current.notes = list(current.notes or []) + ["Concurrent owner survives."]
            run(backend.structured_store.save_dream_run(current))
        else:
            provider.error = ProviderError("Bare errors cannot certify native failure", kind="transient")

    provider.after_failure = change
    with pytest.raises(ProviderError) as raised:
        invoke(data)
    assert raised.value is provider.error and raised.value.__cause__ is not None
    saved = run(backend.structured_store.get_dream_run(original.id))
    assert saved.continuation["source_coverage"][original.items[0].source_id]["status"] == "extracting"
    if fault == "parent_race":
        assert saved.notes[-1] == "Concurrent owner survives."
    assert provider.calls == ["failed_decide"]


def test_dream_native_failure_after_slice_deadline_is_failed_unresolved_not_yield(terminal, monkeypatch):
    data = failing_data(terminal)
    backend, root, original, _old, job, provider, config, _bindings = data
    _idle_carrier(data)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(dream, "_dream_provider_from_config", lambda *_a, **_k: provider)
    now = dream._now
    provider.after_failure = lambda: monkeypatch.setattr(dream, "_now", lambda: now() + timedelta(seconds=301))
    result = run(dream.dream_auto_tick(backend, project_name="demo", project_root=str(root), config=config,
        source="ide_hook", host_client="codex", trigger_id=job.session_id, coverage_origin_run_id=original.id))
    assert result["status"] == "failed", result
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    assert child.execution_status == "failed" and child.resolution_status == "unresolved"
    assert not any("scheduling slice elapsed" in note for note in child.notes or [])
    assert provider.calls == ["failed_decide"]


@pytest.fixture
def legacy_failure(terminal, monkeypatch):
    data = failing_data(terminal)
    backend, _root, original, child, job, provider, _config, bindings = data
    child.continuation.update(terminal_source_coverage_origin_run_id=original.id,
        maintenance_scope=copy.deepcopy(original.continuation["maintenance_scope"]))
    child.notes = ["Hook session distill succeeded: " + job.id]
    run(backend.structured_store.save_dream_run(child))
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    reflection.input_refs = [original.id, job.id]
    backend.reflection_job_store.save(reflection)
    provider.bind_task_budget(bindings[0], phase="dream", slice_id="dream:carrier:1")
    with pytest.raises(ProviderError):
        invoke(data)
    # Reproduce the old masked-error checkpoint only in this isolated store.
    parent = run(backend.structured_store.get_dream_run(original.id))
    state = parent.continuation["source_coverage"][original.items[0].source_id]
    state["status"] = "extracting"
    state.pop("reason_code", None)
    parent.continuation["terminal_coverage_takeover"]["claims"]["carrier:1"]["status"] = "claimed"
    parent.continuation.pop("terminal_coverage_receipts", None)
    run(backend.structured_store.save_dream_run(parent))
    child = run(backend.structured_store.get_dream_run(child.id))
    child.status = "continuing"
    run(backend.structured_store.save_dream_run(child))
    reflection.status, reflection.phase = "retryable", "metabolism"
    backend.reflection_job_store.save(reflection)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_a, **_k: True)
    return data


def close_legacy(data):
    backend, root, _origin, child, job, _provider, config, _bindings = data
    return run(module.close_failed_source_child(backend, project_name="demo", project_root=root,
        config=config, host_client="codex", child_run_id=child.id,
        generation="original-generation", trigger_id=job.session_id))


def test_legacy_missing_receipt_closes_through_original_dual_cas_without_new_calls(legacy_failure):
    backend, _root, original, child, _job, provider, _config, bindings = legacy_failure
    account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    old = run(backend.structured_store.get_dream_run(original.id))
    result = close_legacy(legacy_failure)
    assert result["status"] == "failed" and result["resolution_status"] == "unresolved"
    assert result["source_coverage_failure"]["native_receipt_status"] == "original_provider_receipt_missing"
    saved = run(backend.structured_store.get_dream_run(original.id))
    assert module._terminal_fixed(saved) == module._terminal_fixed(old)
    assert saved.continuation["terminal_coverage_takeover"]["slice_count"] == old.continuation["terminal_coverage_takeover"]["slice_count"]
    assert saved.continuation["source_coverage"][original.items[0].source_id]["status"] == "failed"
    assert run(backend.structured_store.get_dream_run(child.id)).status == "failed"
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope) == account
    assert provider.calls == ["failed_decide"]
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        run(_bound_source_account(backend, run=saved, project_name="demo", project_root=legacy_failure[1],
            config=legacy_failure[-2], host_client="codex", require_remaining=False))


@pytest.mark.parametrize("owner", ["origin", "child"])
def test_legacy_close_dual_cas_rejects_concurrent_owner(legacy_failure, monkeypatch, owner):
    backend, _root, original, child, *_ = legacy_failure
    canonical = backend.structured_store._canonical
    actual = canonical.apply_payload_transaction
    identity = original.id if owner == "origin" else child.id
    injected = []

    def race(*args, **kwargs):
        if not injected:
            injected.append(True)
            payload = json.loads(canonical.get_payload_json("dream_runs", identity))
            payload["notes"] = ["Concurrent owner survives."]
            actual(idempotency_key="source-failure-race", mutations=[{"operation": "upsert", "collection": "dream_runs",
                "entity_id": identity, "payload": payload}])
        return actual(*args, **kwargs)

    monkeypatch.setattr(canonical, "apply_payload_transaction", race)
    with pytest.raises(CanonicalTransactionPreconditionError):
        close_legacy(legacy_failure)
    assert run(backend.structured_store.get_dream_run(identity)).notes == ["Concurrent owner survives."]
    assert run(backend.structured_store.get_dream_run(child.id)).status == "continuing"


@pytest.mark.parametrize("fault", ["reserved", "call_scope", "claim", "reflection_lease", "source_context", "permission"])
def test_legacy_closure_rejects_active_or_changed_bindings_without_mutation(legacy_failure, monkeypatch, fault):
    backend, root, original, child, _job, _provider, config, bindings = legacy_failure
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    if fault in {"reserved", "call_scope"}:
        account = json.loads(path.read_text())
        account["calls"][-1]["status" if fault == "reserved" else "slice_id"] = (
            "reserved" if fault == "reserved" else "source-coverage:other:other:source-decide:other")
        path.write_text(json.dumps(account))
    elif fault == "claim":
        parent = run(backend.structured_store.get_dream_run(original.id))
        parent.continuation["terminal_coverage_takeover"]["claims"]["carrier:1"]["carrier_reflection_id"] = "other"
        run(backend.structured_store.save_dream_run(parent))
    elif fault == "reflection_lease":
        owner = backend.reflection_job_store.get(child.reflection_job_id)
        owner.lease_owner = "other-owner"
        backend.reflection_job_store.save(owner)
    elif fault == "permission":
        replacement = list(legacy_failure)
        replacement[-2] = replace(config, distill_autonomous_enabled=False)
        legacy_failure = tuple(replacement)
    else:
        prepare = module._prepare

        async def changed(*args, **kwargs):
            value = await prepare(*args, **kwargs)
            value["binding"]["context_sha256"] = "0" * 64
            return value
        monkeypatch.setattr(module, "_prepare", changed)
    canonical = backend.structured_store._canonical
    before = {row.id: canonical.get_payload_json("dream_runs", row.id) for row in (original, child)}
    with pytest.raises(ValueError):
        close_legacy(legacy_failure)
    assert {row.id: canonical.get_payload_json("dream_runs", row.id) for row in (original, child)} == before


def test_legacy_closure_at_child_slice_limit_uses_no_extra_claim(legacy_failure):
    backend, _root, original, child, *_ = legacy_failure
    current = run(backend.structured_store.get_dream_run(child.id))
    current.continuation["max_slices"] = current.continuation["slice_count"]
    run(backend.structured_store.save_dream_run(current))
    old = run(backend.structured_store.get_dream_run(original.id))
    assert close_legacy(legacy_failure)["status"] == "failed"
    saved = run(backend.structured_store.get_dream_run(original.id))
    assert saved.continuation["terminal_coverage_takeover"]["slice_count"] == old.continuation["terminal_coverage_takeover"]["slice_count"]


def test_ordinary_known_account_returns_no_failure_closure_even_when_budget_used(legacy_failure):
    backend, _root, original, child, *_rest, bindings = legacy_failure
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(path.read_text())
    account["calls"].pop()
    account["calls"][0]["usage"]["output_tokens"] = 128000
    path.write_text(json.dumps(account))
    canonical = backend.structured_store._canonical
    before = {row.id: canonical.get_payload_json("dream_runs", row.id) for row in (original, child)}
    assert close_legacy(legacy_failure) == {}
    assert {row.id: canonical.get_payload_json("dream_runs", row.id) for row in (original, child)} == before


def test_legacy_known_failure_closes_without_changing_paid_usage(legacy_failure):
    backend, _root, _original, _child, *_rest, bindings = legacy_failure
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(path.read_text())
    account["calls"][-1].update(usage_exact=True,
        usage={"input_tokens": 20, "output_tokens": 3, "duration_seconds": 1.0})
    path.write_text(json.dumps(account))
    before = path.read_bytes()
    result = close_legacy(legacy_failure)
    assert result["source_coverage_failure"]["usage_status"] == "known"
    assert path.read_bytes() == before
