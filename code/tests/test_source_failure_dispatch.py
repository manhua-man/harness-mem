"""The existing typed continuation only closes a failed source, never dispatches it."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_mem.commands import dream_continuation as continuation
from harness_mem.commands import dream_source_coverage as coverage


@pytest.fixture
def route(tmp_path, monkeypatch):
    scope = dict(trigger_id="original-trigger", dispatch_generation="original-generation")
    child = SimpleNamespace(id="child", project_name="demo", status="continuing", continuation={
        "version": "dream-slices-v3", "slice_count": 1, "max_slices": 3,
        "maintenance_scope": scope, "terminal_source_coverage_origin_run_id": "original"})
    origin = SimpleNamespace(id="original", project_name="demo", status="failed",
        continuation={"source_coverage": {}, "source_coverage_pending_ids": ["old-target"]})

    async def get(identity):
        return {"original": origin, "child": child}.get(identity)

    async def latest(*_args, **_kwargs):
        return [child]

    backend = SimpleNamespace(data_dir=tmp_path, structured_store=SimpleNamespace(
        get_dream_run=get, list_dream_runs=latest),
        reflection_job_store=SimpleNamespace(list=lambda **_kwargs: []))
    state = SimpleNamespace(failures=[], closes=[], native=[], outcomes=[], bound_reason="continuation_usage_unknown_or_active")

    async def account(*_args, **_kwargs):
        if state.bound_reason:
            raise ValueError(state.bound_reason)
        return child, scope["dispatch_generation"], scope["trigger_id"]

    async def failure(*_args, **kwargs):
        state.failures.append(kwargs)
        return child, scope["dispatch_generation"], scope["trigger_id"]

    async def close(*_args, **kwargs):
        state.closes.append(kwargs)
        return {"run_id": child.id, "status": "failed", "execution_status": "failed",
                "resolution_status": "unresolved", "reason": "source_coverage_terminal_native_failure"}

    async def native(*_args, **kwargs):
        state.native.append(kwargs)
        raise AssertionError("failure bookkeeping must never invoke Dream/provider")

    monkeypatch.setattr(continuation, "_bound_source_account", account)
    monkeypatch.setattr(coverage, "bound_failed_source_child", failure)
    monkeypatch.setattr(coverage, "close_failed_source_child", close)
    monkeypatch.setattr("harness_mem.commands.dream.dream_auto_tick", native)
    monkeypatch.setattr("harness_mem.hook_background.background_generation_from_env", lambda: scope["dispatch_generation"])
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("harness_mem.autonomous.worker.record_post_turn_maintenance_outcome",
        lambda *_args, **kwargs: state.outcomes.append(kwargs))
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    return backend, SimpleNamespace(dream_auto_max_runtime_seconds=120), child, state


def check(route, **kwargs):
    backend, config, child, _state = route
    return asyncio.run(continuation._bound_origin(backend, project_name="demo", project_root="demo",
        config=config, host_client="codex", run_id=child.id, **kwargs))


def test_source_failure_bookkeeping_is_explicit_and_never_the_inference_default(route):
    with pytest.raises(ValueError, match="continuation_usage_unknown_or_active"):
        check(route)
    child, generation, trigger = check(route, allow_failed_source_bookkeeping=True)
    assert child.id == "child" and generation == "original-generation" and trigger == "original-trigger"
    assert len(route[3].failures) == 1
    assert not route[3].native


def test_last_finite_slice_may_close_failed_metadata_without_an_extra_slice(route):
    route[2].continuation["slice_count"] = 3
    with pytest.raises(ValueError, match="continuation_slices_exhausted"):
        check(route)
    child, _generation, _trigger = check(route, allow_failed_source_bookkeeping=True)
    assert child.continuation["slice_count"] == child.continuation["max_slices"] == 3
    assert len(route[3].failures) == 1 and not route[3].native


@pytest.mark.parametrize("reason", ["continuation_bounds_changed", "continuation_source_scope_mismatch"])
def test_other_failures_cannot_select_the_bookkeeping_exception(route, reason):
    route[3].bound_reason = reason
    with pytest.raises(ValueError, match=reason):
        check(route, allow_failed_source_bookkeeping=True)
    assert not route[3].failures and not route[3].closes


def test_existing_worker_closes_exact_original_pointer_without_model_or_new_slice(route):
    backend, config, child, state = route
    result = asyncio.run(continuation.run_bound_continuation(backend, project_name="demo",
        project_root="demo", config=config, host_client="codex", resume_run_id="original",
        trigger_id="original-trigger"))
    assert result["status"] == "failed" and result["dream_tick"]["run_id"] == child.id
    assert result["dream_tick"]["resolution_status"] == "unresolved"
    assert len(state.closes) == 1 and not state.native
    assert child.continuation["slice_count"] == 1
    assert state.closes[0]["generation"] == "original-generation"
    assert state.closes[0]["trigger_id"] == "original-trigger"
    assert state.outcomes[0]["dream"] == result["dream_tick"]


def test_natural_wake_reuses_original_typed_queue_identity_for_bookkeeping(route, monkeypatch):
    backend, config, _child, state = route
    queued = []

    def dispatch(*_args, **kwargs):
        queued.append(kwargs)
        return SimpleNamespace(spawned=False, coalesced=True)

    monkeypatch.setattr("harness_mem.hook_background.dispatch_bound_continuation", dispatch)
    result = asyncio.run(continuation.enqueue_bound_continuation(backend, project_name="demo",
        project_root="demo", config=config, host_client="codex"))
    assert result["status"] == "queued" and result["run_id"] == "original"
    assert queued == [dict(project_root=Path("demo"), client="codex",
        trigger_id="original-trigger", generation="original-generation", resume_run_id="original")]
    assert not state.native and not state.closes
