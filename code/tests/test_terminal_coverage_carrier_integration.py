"""Dream carries bounded original obligations without adding them as new items."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from harness_mem.commands import dream, dream_source_coverage
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal


def run(value):
    return asyncio.run(value)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    run(backend.init())
    root = tmp_path / "project"
    root.mkdir()
    yield backend, root
    run(backend.close())


def test_carrier_saves_its_scope_before_one_takeover_and_keeps_own_manifest(workspace, monkeypatch):
    backend, root = workspace
    calls = []

    async def count(*_args, **_kwargs):
        return 2

    async def takeover(_backend, **kwargs):
        current = await backend.structured_store.get_dream_run(kwargs["carrier_run_id"])
        assert current.status == "processing"
        assert current.continuation["maintenance_scope"]["dispatch_generation"] == "new-generation"
        assert current.continuation["terminal_source_coverage_initial_count"] == 2
        assert current.continuation["max_slices"] == 5
        assert current.continuation["signals"] == [] and current.items == []
        calls.append(kwargs["carrier_run_id"])
        return {"worked": True, "pending": True, "origin_run_id": "old-failed-run",
                "predecessor_id": "old-applied", "status": "applied", "reason": "fixture_applied"}

    monkeypatch.setattr(dream_source_coverage, "pending_terminal_source_coverage_count", count)
    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", takeover)
    result = run(dream.dream_once(backend, project_name="demo", project_root=root,
        semantic_provider=SimpleNamespace(name="fixture"),
        maintenance_scope={"trigger_id": "new-trigger", "dispatch_generation": "new-generation"}))
    assert calls == [result.id] and result.status == "continuing"
    assert result.items == [] and result.handling_summary["applied"] == 0
    assert result.continuation["target_ids"] == []
    assert result.continuation["terminal_source_coverage_pending"] is True
    assert "old-failed-run:old-applied" in result.continuation["terminal_source_coverage"]

    async def no_recount(*_args, **_kwargs):
        raise AssertionError("a resumed carrier cannot acquire a higher slice limit")

    async def finished(*_args, **_kwargs):
        return {"worked": False, "pending": False}

    monkeypatch.setattr(dream_source_coverage, "pending_terminal_source_coverage_count", no_recount)
    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", finished)
    resumed = run(dream.dream_once(backend, project_name="demo", project_root=root,
        semantic_provider=SimpleNamespace(name="fixture"), resume_run_id=result.id))
    assert resumed.status == "completed" and resumed.continuation["max_slices"] == 5
    assert resumed.continuation["slice_count"] == 2
    assert resumed.continuation["terminal_source_coverage_pending"] is False


@pytest.mark.parametrize("status", ["blocked", "failed", "no_write", "unresolved"])
def test_takeover_failure_keeps_carrier_resolution_unresolved(workspace, monkeypatch, status):
    backend, root = workspace

    async def count(*_args, **_kwargs):
        return 1

    async def blocked(*_args, **_kwargs):
        return {"worked": False, "pending": False, "origin_run_id": "old-failed-run",
                "predecessor_id": "missing-source-group", "status": status, "reason": "fixture_reason"}

    monkeypatch.setattr(dream_source_coverage, "pending_terminal_source_coverage_count", count)
    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", blocked)
    result = run(dream.dream_once(backend, project_name="demo", project_root=root,
        semantic_provider=SimpleNamespace(name="fixture")))
    assert result.status == "failed" and result.resolution_status == "unresolved"
    assert result.items == [] and result.handling_summary["applied"] == 0
    assert result.continuation["unresolved_scope"] == {
        "terminal_source_coverage:old-failed-run:missing-source-group": "source_coverage_" + status}


def test_existing_carrier_slice_limit_is_never_raised_for_new_pending_work(workspace, monkeypatch):
    backend, root = workspace
    from harness_mem.core.schemas.dream_run import DreamRun
    original = DreamRun(id="old-carrier", project_name="demo", status="continuing",
        continuation={"version": "dream-slices-v3", "signals": [], "target_ids": [],
                      "slice_count": 1, "max_slices": 1,
                      "maintenance_scope": {"trigger_id": "new", "dispatch_generation": "generation"}})
    run(backend.structured_store.save_dream_run(original))

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("exhausted carrier cannot count or start inherited work")

    monkeypatch.setattr(dream_source_coverage, "pending_terminal_source_coverage_count", forbidden)
    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", forbidden)
    result = run(dream.dream_once(backend, project_name="demo", project_root=root,
        semantic_provider=SimpleNamespace(name="fixture"), resume_run_id=original.id))
    assert result.status == "failed" and result.continuation["max_slices"] == 1


def test_coverage_only_tick_uses_common_claim_and_original_candidate_pipeline(terminal, monkeypatch):
    from test_terminal_source_coverage import _idle_carrier
    from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt
    from harness_mem.commands import dream_continuation
    from harness_mem import hook_background
    backend, root, old, _carrier, job, provider, config, bindings = terminal
    _idle_carrier(terminal)
    new_account_before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    job_before = job.to_dict()
    old_items = [item.to_dict() for item in old.items]
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr(dream, "_dream_provider_from_config", lambda *_a, **_k: provider)

    async def no_new_traversal(*_args, **_kwargs):
        raise AssertionError("coverage-only execution cannot replay ordinary traversal")

    def no_source_intake(*_args, **_kwargs):
        raise AssertionError("coverage-only execution cannot create a source job")

    monkeypatch.setattr(dream, "_detect_separated_rechecks", no_new_traversal)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_autonomous_distill_batch", no_source_intake)
    original_dispatch = hook_background.dispatch_bound_continuation
    spawned = []
    monkeypatch.setattr(hook_background, "dispatch_bound_continuation", lambda *args, **kwargs:
        original_dispatch(*args, **kwargs, popen=lambda *a, **k: spawned.append((a, k))))
    queued = run(dream_continuation.enqueue_bound_continuation(
        backend, project_name="demo", project_root=str(root), config=config, host_client="codex"))
    assert queued["status"] == "queued" and queued["run_id"] == old.id and len(spawned) == 1
    monkeypatch.setattr(hook_background, "heartbeat_background_worker", lambda *_a, **_k: True)
    recorded = []
    monkeypatch.setattr("harness_mem.autonomous.worker.record_post_turn_maintenance_outcome",
                        lambda *_args, **kwargs: recorded.append(kwargs))
    finished = run(dream_continuation.run_bound_continuation(
        backend, project_name="demo", project_root=str(root), config=config, host_client="codex",
        trigger_id=job.session_id, resume_run_id=queued["run_id"]))
    assert finished["success"] and recorded[0]["dispatch_generation"] == "original-generation", finished
    result = finished["dream_tick"]
    assert result["success"] and result["status"] == "completed", result
    assert result["session_distill"] is None and result["run_id"] != old.id
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    assert child.continuation["terminal_source_coverage_origin_run_id"] == old.id
    assert child.continuation["signals"] == [] and child.items == []
    assert child.continuation["max_slices"] == 3
    assert child.continuation["maintenance_scope"] == old.continuation["maintenance_scope"]
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    assert reflection.status == "completed" and old.id in reflection.input_refs and job.id in reflection.input_refs
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    final_old = run(backend.structured_store.get_dream_run(old.id))
    assert final_old.status == "failed" and final_old.completed_at == old.completed_at
    assert [item.to_dict() for item in final_old.items] == old_items
    assert final_old.continuation["slice_count"] == 4 and final_old.continuation["max_slices"] == 24
    assert len(read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)["calls"]) == 5
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == new_account_before
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    rows = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert any("During this daily-entry repair, do not add acceptance rituals." == row.statement for row in rows)
    again = run(dream_continuation.enqueue_bound_continuation(
        backend, project_name="demo", project_root=str(root), config=config, host_client="codex"))
    assert again["status"] == "skipped" and len(spawned) == 1
    assert len(provider.calls) == 4


def test_coverage_carrier_resumes_second_slice_with_original_source_binding(terminal, monkeypatch):
    from datetime import timedelta
    from test_terminal_source_coverage import _idle_carrier
    from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt
    backend, root, old, _carrier, job, provider, config, bindings = terminal
    _idle_carrier(terminal)
    new_before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    job_before = job.to_dict()
    old_fixed = dream_source_coverage._terminal_fixed(old)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr(dream, "_dream_provider_from_config", lambda *_a, **_k: provider)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("coverage carrier cannot replay ordinary traversal")

    monkeypatch.setattr(dream, "_detect_separated_rechecks", forbidden)
    real_now = dream._now
    elapsed = [False]
    monkeypatch.setattr(dream, "_now", lambda: real_now() + timedelta(seconds=200 if elapsed[0] else 0))
    original_verify = provider.verify

    def yield_after_candidate_verify(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        if provider.calls[-1] == "candidate_verify":
            elapsed[0] = True
        return result

    monkeypatch.setattr(provider, "verify", yield_after_candidate_verify)
    first = run(dream.dream_auto_tick(backend, project_name="demo", project_root=str(root),
        config=config, source="ide_hook", host_client="codex", trigger_id=job.session_id,
        coverage_origin_run_id=old.id))
    assert first["status"] == "continuing", first
    assert provider.calls == ["decide", "candidate_verify"]
    child_id = first["run_id"]
    elapsed[0] = False
    second = run(dream.dream_auto_tick(backend, project_name="demo", project_root=str(root),
        config=config, source="ide_hook", host_client="codex", trigger_id=job.session_id,
        resume_run_id=child_id))
    assert second["status"] == "completed", second
    assert second["run_id"] == child_id
    child = run(backend.structured_store.get_dream_run(child_id))
    assert child.continuation["slice_count"] == 2 and child.continuation["max_slices"] == 3
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    assert job.id in reflection.input_refs and old.id in reflection.input_refs
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    final_old = run(backend.structured_store.get_dream_run(old.id))
    assert dream_source_coverage._terminal_fixed(final_old) == old_fixed
    assert len(read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)["calls"]) == 5
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == new_before
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before
    rows = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert any(row.statement == "During this daily-entry repair, do not add acceptance rituals." for row in rows)


def test_originless_blocked_takeover_cannot_complete_pinned_carrier(workspace, monkeypatch):
    backend, root = workspace
    from harness_mem.core.schemas.dream_run import DreamRun
    original = DreamRun(id="pinned-carrier", project_name="demo", status="continuing",
        continuation={"version": "dream-slices-v3", "signals": [], "target_ids": [],
            "slice_count": 1, "max_slices": 3, "terminal_source_coverage_initial_count": 1,
            "terminal_source_coverage_origin_run_id": "old-failed-run"})
    run(backend.structured_store.save_dream_run(original))

    async def blocked(*_args, **_kwargs):
        return {"worked": False, "pending": False, "status": "blocked", "reason": "source_missing"}

    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", blocked)
    result = run(dream.dream_once(backend, project_name="demo", project_root=root,
        semantic_provider=SimpleNamespace(name="fixture"), resume_run_id=original.id))
    assert result.status == "failed" and result.resolution_status == "unresolved"
    assert result.continuation["unresolved_scope"]


@pytest.mark.parametrize("fault", ["generation", "foreground", "source"])
def test_coverage_only_tick_rejects_unbound_call_before_any_provider(terminal, monkeypatch, fault):
    from test_terminal_source_coverage import _idle_carrier
    from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt
    backend, root, old, _carrier, job, _provider, config, bindings = terminal
    _idle_carrier(terminal)
    before = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "0" if fault == "foreground" else "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "wrong" if fault == "generation" else "original-generation")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("an invalid pointer cannot create a provider")

    monkeypatch.setattr(dream, "_dream_provider_from_config", forbidden)
    with pytest.raises(ValueError, match="terminal_source_coverage_(account_mismatch|detached_owner_required)"):
        run(dream._dream_auto_tick_core(
            backend, project_name="demo", project_root=str(root), config=config,
            source="agent" if fault == "source" else "ide_hook", host_client="codex",
            trigger_id=job.session_id, coverage_origin_run_id=old.id))
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope) == before
