"""Terminal obligations run in isolated canonical stores with fake transports."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider
from harness_mem.commands import dream_source_coverage as module
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult,
    bind_maintenance_task,
    dispatch_with_task_budget,
    read_task_budget_receipt,
    task_budget_receipt_path,
)


def run(awaitable):
    return asyncio.run(awaitable)


class AccountedProvider(CoverageProvider):
    host_client = "codex"

    def bind_task_budget(self, binding, **kwargs):
        self.task_budget_binding = binding
        self._budget_phase = kwargs["phase"]
        self._budget_slice = kwargs["slice_id"]
        self._budget_retry_of = kwargs.get("retry_of")
        self.bindings.append({"scope": binding.task_scope, **kwargs})

    def charge(self):
        dispatch_with_task_budget(
            self.task_budget_binding,
            phase=self._budget_phase,
            slice_id=self._budget_slice,
            timeout_seconds=1,
            transport=lambda _: NativeDispatchResult(
                status="completed",
                input_tokens=12,
                output_tokens=3,
                duration_seconds=0.01,
                usage_exact=True,
            ),
        )

    def decide(self, *args, **kwargs):
        self.charge()
        return super().decide(*args, **kwargs)

    def verify(self, *args, **kwargs):
        self.charge()
        return super().verify(*args, **kwargs)

    def assimilate(self, *args, **kwargs):
        self.charge()
        return super().assimilate(*args, **kwargs)


@pytest.fixture
def terminal(coverage, monkeypatch):
    backend, root, job, entry, item, checkpoint, notes = coverage
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.autonomous_runtime_fingerprint",
        lambda: "fixture-code",
    )
    config = MergedConfig(distill_autonomous_enabled=True)
    checkpoint.update(
        version="dream-slices-v3",
        target_ids=[item.source_id] + [f"old-{i}" for i in range(22)],
        source_coverage_pending_ids=[item.source_id],
        source_coverage={},
        maintenance_scope={
            "trigger_id": job.session_id,
            "dispatch_generation": "original-generation",
        },
    )
    now = datetime.now(timezone.utc)
    notes = notes + [
        "dream verification receipt: "
        + json.dumps(
            {
                "final_output_bindings": [
                    {
                        "owner_candidate_id": "dream:" + item.source_id,
                        "title_sha256": hashlib.sha256(
                            entry.title.encode()
                        ).hexdigest(),
                        "statement_sha256": hashlib.sha256(
                            entry.statement.encode()
                        ).hexdigest(),
                    }
                ]
            }
        )
    ]
    old = DreamRun(
        id="old-run",
        project_name="demo",
        status="failed",
        execution_status="failed",
        resolution_status="failed",
        trigger_source="ide_hook",
        started_at=now - timedelta(hours=1),
        completed_at=now - timedelta(minutes=5),
        items=[item],
        notes=notes + ["Hook session distill verified: " + job.id],
        continuation=checkpoint,
    )
    run(backend.structured_store.save_dream_run(old))
    newjob = job.model_copy(
        update={"id": "carrier-source-job", "idempotency_key": "carrier-source-job"}
    )
    ledger = backend.transcript_store
    with ledger._lock:
        ledger._distill._upsert_job_locked(newjob)
        ledger._conn.commit()
    reflection = ReflectionJob(
        id="carrier-reflection",
        project_name="demo",
        project_root=str(root),
        kind="dream",
        status="processing",
        phase="metabolism",
        source="ide_hook",
        input_refs=[newjob.id],
    )
    backend.reflection_job_store.save(reflection)
    carrier = DreamRun(
        id="carrier",
        project_name="demo",
        status="processing",
        trigger_source="ide_hook",
        reflection_job_id=reflection.id,
        started_at=now,
        continuation={
            "version": "dream-slices-v3",
            "slice_count": 1,
            "max_slices": 2,
            "maintenance_scope": {
                "trigger_id": job.session_id,
                "dispatch_generation": "carrier-generation",
            },
            "target_ids": [],
            "signals": [],
            "source_coverage": {},
        },
    )
    run(backend.structured_store.save_dream_run(carrier))
    bindings = []
    for generation, source_job in (
        ("original-generation", job),
        ("carrier-generation", newjob),
    ):
        binding = bind_maintenance_task(
            data_dir=backend.data_dir,
            host_client="codex",
            config=config,
            trigger_id=job.session_id,
            dispatch_generation=generation,
        )
        dispatch_with_task_budget(
            binding,
            phase="source",
            slice_id="source-decide:" + source_job.id,
            timeout_seconds=1,
            transport=lambda _: NativeDispatchResult(
                status="completed",
                input_tokens=10,
                output_tokens=2,
                duration_seconds=0.01,
                usage_exact=True,
            ),
        )
        bindings.append(binding)
    provider = AccountedProvider()
    provider.bind_task_budget(
        bindings[1], phase="dream", slice_id="dream:carrier:1", retry_of="keep-retry"
    )
    return backend, root, old, carrier, job, provider, config, bindings


def invoke(data, *, boundary=None):
    backend, root, _old, carrier, _job, provider, config, _bindings = data
    return run(
        module.run_pending_terminal_source_coverage(
            backend,
            project_name="demo",
            project_root=root,
            carrier_run_id=carrier.id,
            provider=provider,
            config=config,
            host_client="codex",
            boundary=boundary,
        )
    )


def test_terminal_work_reaches_candidate_pipeline_charges_old_and_restores_carrier(
    terminal,
):
    backend, root, old, carrier, job, provider, config, bindings = terminal
    old_fixed = module._terminal_fixed(old)
    carrier_before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    job_before = job.to_dict()
    result = invoke(terminal)
    assert result["worked"] and result["status"] == "applied", result
    assert provider.calls == [
        "decide",
        "candidate_verify",
        "assimilate",
        "final_verify",
    ]
    retained = run(backend.structured_store.get_dream_run(old.id))
    assert retained.status == "failed" and retained.completed_at == old.completed_at
    assert retained.items == old.items and module._terminal_fixed(retained) == old_fixed
    assert (
        retained.continuation["slice_count"] == 4
        and retained.continuation["max_slices"] == 24
    )
    assert retained.continuation["terminal_coverage_takeover"]["slice_count"] == 1
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    rows = run(
        backend.structured_store.knowledge_store.list_entries("demo", project_root=root)
    )
    assert any("acceptance rituals" in row.statement for row in rows)
    old_account = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert len(old_account["calls"]) == 5
    assert all(
        call["phase"] == "dream"
        and call["slice_id"].startswith("source-coverage:old-run:")
        for call in old_account["calls"][1:]
    )
    assert (
        read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
        == carrier_before
    )
    assert provider.task_budget_binding == bindings[1]
    assert (
        provider._budget_phase,
        provider._budget_slice,
        provider._budget_retry_of,
    ) == ("dream", "dream:carrier:1", "keep-retry")
    before_calls = list(provider.calls)
    invoke(terminal)
    assert provider.calls == before_calls


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "budget",
        "host",
        "bounds",
        "source",
        "standalone",
        "carrier_terminal",
        "reflection",
        "reflection_stale",
        "carrier_source",
        "carrier_binding",
        "phase",
        "original_limit",
        "failed_coverage",
    ],
)
def test_refusals_never_borrow_new_account_or_resurrect_terminal(terminal, fault):
    backend, root, old, carrier, _job, provider, config, bindings = terminal
    ledger_path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(ledger_path.read_text())
    if fault == "unknown":
        account["calls"][0]["usage_exact"] = False
    elif fault == "budget":
        account["calls"][0]["usage"]["output_tokens"] = 128000
    elif fault == "host":
        account["host_client"] = "hermes"
    elif fault == "bounds":
        account["bounds"]["max_calls"] += 1
    elif fault == "source":
        backend.transcript_store.reconstruct_raw = lambda *_a, **_k: b"tampered"
    elif fault == "standalone":
        carrier.trigger_source = "agent"
    elif fault == "carrier_terminal":
        carrier.status = "completed"
    elif fault == "reflection":
        job = backend.reflection_job_store.get(carrier.reflection_job_id)
        job.status = "completed"
        backend.reflection_job_store.save(job)
    elif fault == "reflection_stale":
        reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
        reflection.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
        # Save normally updates the timestamp; isolated SQL simulates a crash.
        with backend.structured_store.index.locked_connection() as connection:
            connection.execute(
                "UPDATE reflection_jobs SET data=? WHERE id=?",
                (json.dumps(reflection.to_dict()), reflection.id),
            )
            connection.commit()
    elif fault == "carrier_source":
        job = backend.reflection_job_store.get(carrier.reflection_job_id)
        job.input_refs = []
        backend.reflection_job_store.save(job)
    elif fault == "carrier_binding":
        provider.task_budget_binding = bindings[0]
    elif fault == "phase":
        provider._budget_slice = "incorrect-slice"
    elif fault == "original_limit":
        old.continuation["slice_count"] = 24
    elif fault == "failed_coverage":
        old.continuation["source_coverage"] = {
            old.items[0].source_id: {"status": "failed"}
        }
    ledger_path.write_text(json.dumps(account))
    run(backend.structured_store.save_dream_run(old))
    run(backend.structured_store.save_dream_run(carrier))
    new_before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    result = invoke(terminal)
    assert not result["worked"] and not provider.calls, result
    assert (
        read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == new_before
    )
    assert run(backend.structured_store.get_dream_run(old.id)).status == "failed"


def test_takeover_counter_is_bounded_by_original_24(terminal):
    backend, _root, old, _carrier, _job, _provider, _config, _bindings = terminal
    old.continuation["terminal_coverage_takeover"] = {
        "contract": module.TERMINAL_TAKEOVER_CONTRACT,
        "slice_count": 20,
        "claims": {str(i): {} for i in range(20)},
        "origin_fixed_sha256": module._terminal_fixed(old),
    }
    run(backend.structured_store.save_dream_run(old))
    result = invoke(terminal)
    assert (
        result["status"] == "blocked"
        and result["reason"] == "terminal_coverage_original_slices_exhausted"
    )
    assert (
        run(backend.structured_store.get_dream_run(old.id)).continuation["max_slices"]
        == 24
    )


def test_new_carrier_count_is_read_only_and_excludes_attempted_terminal_states(
    terminal,
):
    backend, _root, old, _carrier, _job, _provider, _config, _bindings = terminal
    canonical = backend.structured_store._canonical
    before = canonical.get_payload_json("dream_runs", old.id)
    assert (
        run(
            module.pending_terminal_source_coverage_count(
                backend, project_name="demo", exclude_run_id="carrier"
            )
        )
        == 1
    )
    assert canonical.get_payload_json("dream_runs", old.id) == before
    old.continuation["source_coverage"][old.items[0].source_id] = {"status": "no_write"}
    run(backend.structured_store.save_dream_run(old))
    assert (
        run(module.pending_terminal_source_coverage_count(backend, project_name="demo"))
        == 0
    )


@pytest.mark.parametrize("target", ["origin", "carrier"])
def test_checkpoint_cas_rejects_same_project_concurrent_owner_change(
    terminal, monkeypatch, target
):
    backend, _root, old, carrier, _job, provider, _config, _bindings = terminal
    canonical = backend.structured_store._canonical
    original = canonical.apply_payload_transaction
    changed = [False]

    def race(**kwargs):
        if not changed[0]:
            changed[0] = True
            identity = old.id if target == "origin" else carrier.id
            payload = json.loads(canonical.get_payload_json("dream_runs", identity))
            payload["notes"] = ["Concurrent owner changed this record."]
            original(
                idempotency_key="isolated-concurrent-owner",
                mutations=[
                    {
                        "operation": "upsert",
                        "collection": "dream_runs",
                        "entity_id": identity,
                        "payload": payload,
                    }
                ],
            )
        return original(**kwargs)

    monkeypatch.setattr(canonical, "apply_payload_transaction", race)
    result = invoke(terminal)
    assert result["status"] == "blocked" and not provider.calls
    saved = run(backend.structured_store.get_dream_run(old.id))
    assert (
        saved.status == "failed"
        and "terminal_coverage_takeover" not in saved.continuation
    )


def test_slice_yield_propagates_restores_binding_then_resumes_existing_candidates(
    terminal,
):
    from harness_mem.commands.dream import _DreamSliceYield

    backend, _root, old, carrier, _job, provider, _config, bindings = terminal
    boundaries = [0]

    async def boundary():
        boundaries[0] += 1
        if boundaries[0] == 2:
            raise _DreamSliceYield()

    with pytest.raises(_DreamSliceYield):
        invoke(terminal, boundary=boundary)
    assert provider.calls == ["decide", "candidate_verify"]
    assert (
        provider.task_budget_binding == bindings[1]
        and provider._budget_slice == "dream:carrier:1"
    )
    saved = run(backend.structured_store.get_dream_run(old.id))
    assert saved.status == "failed"
    assert (
        saved.continuation["source_coverage"][old.items[0].source_id]["status"]
        == "candidates_verified"
    )
    carrier.continuation["slice_count"] = 2
    run(backend.structured_store.save_dream_run(carrier))
    provider.bind_task_budget(bindings[1], phase="dream", slice_id="dream:carrier:2")
    result = invoke(terminal)
    assert result["status"] == "applied", result
    assert provider.calls == [
        "decide",
        "candidate_verify",
        "assimilate",
        "final_verify",
    ]
    saved = run(backend.structured_store.get_dream_run(old.id))
    assert saved.continuation["terminal_coverage_takeover"]["slice_count"] == 2
    assert (
        saved.continuation["slice_count"] == 4
        and saved.continuation["max_slices"] == 24
    )


def _idle_carrier(data):
    backend, _root, _old, carrier, _job, _provider, _config, _bindings = data
    carrier.status = "failed"
    carrier.completed_at = datetime.now(timezone.utc)
    run(backend.structured_store.save_dream_run(carrier))
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    reflection.status = "completed"
    backend.reflection_job_store.save(reflection)


def test_idle_preflight_proves_exact_old_source_without_new_intake(terminal):
    backend, root, old, _carrier, job, _provider, config, _bindings = terminal
    with pytest.raises(ValueError, match="processing_active"):
        run(
            module.bound_terminal_source_coverage_origin(
                backend,
                project_name="demo",
                project_root=root,
                config=config,
                host_client="codex",
            )
        )
    _idle_carrier(terminal)
    origin, generation, trigger, source_job = run(
        module.bound_terminal_source_coverage_origin(
            backend,
            project_name="demo",
            project_root=root,
            config=config,
            host_client="codex",
        )
    )
    assert (origin.id, generation, trigger, source_job) == (
        old.id,
        "original-generation",
        job.session_id,
        job.id,
    )
    prepared = run(
        module._prepare(
            backend,
            project_name="demo",
            project_root=root,
            run_id=old.id,
            item=old.items[0],
            checkpoint=old.continuation,
            notes=old.notes,
        )
    )
    assert len(prepared["packet"]["semantic_decision_exchanges"]) == 78
    assert any(
        window["exchange_index"] == 47
        for window in prepared["packet"]["semantic_decision_exchanges"]
    )


def test_native_wake_queues_stable_origin_then_existing_worker_creates_and_finishes_child(
    terminal, monkeypatch
):
    from harness_mem import hook_background as queue
    from harness_mem.commands import dream_continuation as continuation, dream

    backend, root, old, carrier, job, _provider, config, _bindings = terminal
    _idle_carrier(terminal)
    spawned = []
    original_dispatch = queue.dispatch_bound_continuation
    monkeypatch.setattr(
        queue,
        "dispatch_bound_continuation",
        lambda *args, **kwargs: original_dispatch(
            *args, **kwargs, popen=lambda *a, **k: spawned.append((a, k))
        ),
    )
    response = run(
        continuation.enqueue_bound_continuation(
            backend,
            project_name="demo",
            project_root=str(root),
            config=config,
            host_client="codex",
        )
    )
    assert (
        response["run_id"] == old.id and response["generation"] == "original-generation"
    )
    assert len(spawned) == 1
    calls = []

    async def fake_tick(*_args, **kwargs):
        calls.append(kwargs)
        assert kwargs["trigger_job_id"] is None
        if kwargs.get("coverage_origin_run_id"):
            assert kwargs["coverage_origin_run_id"] == old.id
            carrier.status = "continuing"
            carrier.completed_at = None
            carrier.notes = list(old.notes)
            carrier.continuation.update(
                terminal_source_coverage_origin_run_id=old.id,
                maintenance_scope=dict(old.continuation["maintenance_scope"]),
                max_slices=3,
            )
            await backend.structured_store.save_dream_run(carrier)
            # Concurrent wake must reuse the same origin filename/pointer.
            queued = await continuation.enqueue_bound_continuation(
                backend,
                project_name="demo",
                project_root=str(root),
                config=config,
                host_client="codex",
            )
            assert queued["run_id"] == old.id and queued["coalesced"]
            return {"run_id": carrier.id, "status": "continuing"}
        assert kwargs["resume_run_id"] == carrier.id
        carrier.status = "completed"
        await backend.structured_store.save_dream_run(carrier)
        return {"run_id": carrier.id, "status": "completed"}

    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_LEASE", "original-generation")
    monkeypatch.setattr(dream, "dream_auto_tick", fake_tick)
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.record_post_turn_maintenance_outcome",
        lambda *_a, **_k: None,
    )
    result = run(
        continuation.run_bound_continuation(
            backend,
            project_name="demo",
            project_root=str(root),
            config=config,
            host_client="codex",
            resume_run_id=old.id,
            trigger_id=job.session_id,
        )
    )
    assert result["success"] and len(calls) == 2
    assert run(backend.structured_store.get_dream_run(old.id)).status == "failed"
    assert len(spawned) == 1


def test_settled_child_can_finish_without_fresh_pending_or_unused_native_budget(
    terminal, monkeypatch
):
    from harness_mem.commands import dream_continuation as continuation, dream

    backend, root, old, carrier, job, _provider, config, bindings = terminal
    _idle_carrier(terminal)
    old.continuation["source_coverage"][old.items[0].source_id] = {"status": "applied"}
    run(backend.structured_store.save_dream_run(old))
    carrier.status = "continuing"
    carrier.completed_at = None
    carrier.notes = list(old.notes)
    carrier.continuation.update(
        terminal_source_coverage_origin_run_id=old.id,
        maintenance_scope=dict(old.continuation["maintenance_scope"]),
        max_slices=3,
        slice_count=2,
    )
    run(backend.structured_store.save_dream_run(carrier))
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    account = json.loads(path.read_text())
    account["calls"][0]["usage"]["output_tokens"] = 128000
    path.write_text(json.dumps(account))
    # Fresh production of another child is forbidden, but closing an existing
    # continuing child uses no new source and needs no native invocation.
    origin = run(
        module.bound_terminal_source_coverage_origin(
            backend,
            project_name="demo",
            project_root=root,
            config=config,
            host_client="codex",
            origin_run_id=old.id,
            require_idle=False,
        )
    )
    assert origin[0].id == old.id
    calls = []

    async def close(*_args, **kwargs):
        calls.append(kwargs)
        assert (
            kwargs["resume_run_id"] == carrier.id
            and "coverage_origin_run_id" not in kwargs
        )
        return {"run_id": carrier.id, "status": "completed"}

    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr(
        continuation,
        "heartbeat_background_worker",
        lambda *_a, **_k: True,
        raising=False,
    )
    monkeypatch.setattr(
        "harness_mem.hook_background.heartbeat_background_worker",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(dream, "dream_auto_tick", close)
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.record_post_turn_maintenance_outcome",
        lambda *_a, **_k: None,
    )
    result = run(
        continuation.run_bound_continuation(
            backend,
            project_name="demo",
            project_root=str(root),
            config=config,
            host_client="codex",
            resume_run_id=old.id,
            trigger_id=job.session_id,
        )
    )
    assert result["success"] and len(calls) == 1


def test_native_heartbeat_refreshes_exact_owner_while_old_call_is_reserved(terminal):
    backend, _root, _old, carrier, _job, _provider, config, bindings = terminal
    heartbeat = module._carrier_heartbeat(backend, carrier, config=config)
    reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
    reflection.updated_at = datetime.now(timezone.utc) - timedelta(seconds=205)
    with backend.structured_store.index.locked_connection() as connection:
        connection.execute(
            "UPDATE reflection_jobs SET data=? WHERE id=?",
            (json.dumps(reflection.to_dict()), reflection.id),
        )
        connection.commit()

    def fake_transport(_request):
        receipt = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
        assert receipt["calls"][-1]["status"] == "reserved"
        heartbeat()  # Must not demand terminal usage from this in-flight call.
        refreshed = backend.reflection_job_store.get(carrier.reflection_job_id)
        assert (
            refreshed.status == "processing"
            and refreshed.updated_at > reflection.updated_at
        )
        return NativeDispatchResult(
            status="completed",
            input_tokens=1,
            output_tokens=1,
            duration_seconds=0.01,
            usage_exact=True,
        )

    dispatch_with_task_budget(
        bindings[0],
        phase="dream",
        slice_id="source-coverage:old-run:heartbeat",
        timeout_seconds=1,
        transport=fake_transport,
    )
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)["calls"][
        -1
    ]["usage_exact"]


@pytest.mark.parametrize("change", ["closed", "deleted", "competing"])
def test_native_heartbeat_cannot_revive_or_steal_reflection_claim(terminal, change):
    from harness_mem.autonomous.provider import ProviderError

    backend, root, _old, carrier, _job, _provider, config, _bindings = terminal
    heartbeat = module._carrier_heartbeat(backend, carrier, config=config)
    if change == "closed":
        reflection = backend.reflection_job_store.get(carrier.reflection_job_id)
        reflection.status = "completed"
        backend.reflection_job_store.save(reflection)
    elif change == "deleted":
        with backend.structured_store.index.locked_connection() as connection:
            connection.execute(
                "DELETE FROM reflection_jobs WHERE id=?", (carrier.reflection_job_id,)
            )
            connection.commit()
    else:
        backend.reflection_job_store.save(
            ReflectionJob(
                project_name="demo",
                project_root=str(root),
                kind="dream",
                status="processing",
                phase="metabolism",
                source="ide_hook",
            )
        )
    with pytest.raises(ProviderError):
        heartbeat()
    final = backend.reflection_job_store.get(carrier.reflection_job_id)
    assert (
        final is None
        if change == "deleted"
        else final.status == ("completed" if change == "closed" else "processing")
    )


def test_changed_same_id_successor_fails_before_candidate_extraction(terminal):
    backend, root, _old, _carrier, _job, provider, _config, _bindings = terminal
    entry = run(
        backend.structured_store.knowledge_store.get_entry(
            "narrow-successor", project_name="demo", project_root=root
        )
    )
    canonical = backend.structured_store._canonical
    payload = entry.to_dict()
    payload["statement"] = "A concurrent different condition."
    canonical.apply_payload_transaction(
        idempotency_key="isolated-current-successor-change",
        mutations=[
            {
                "operation": "upsert",
                "collection": "knowledge_entries",
                "entity_id": entry.id,
                "payload": payload,
            }
        ],
    )
    result = invoke(terminal)
    assert (
        result["reason"] == "terminal_coverage_original_successor_changed"
        and not provider.calls
    )
