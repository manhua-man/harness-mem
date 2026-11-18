"""Typed report queue routing with isolated accounts and no native execution."""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from test_dream_continuation_recovery import bound as bound, enqueue
from harness_mem.commands import dream_continuation as recovery


def run(value):
    return asyncio.run(value)


@pytest.fixture
def reports(bound, monkeypatch):
    import harness_mem.commands.dream_source_coverage as coverage

    origin = bound.run
    origin.status = "failed"
    state = NS(origin=origin, latest=origin, child=None, attempted=False,
               coverage_error="no_terminal_pending_coverage", calls=[])

    async def get_run(rid):
        return next((row for row in [origin, state.child] if row and row.id == rid), None)

    async def list_runs(project_name, limit):
        return [state.latest] if project_name == origin.project_name else []

    async def account(row, kwargs, remaining=True):
        return await recovery._bound_source_account(
            bound.backend, run=row, project_name=kwargs["project_name"],
            project_root=kwargs["project_root"], config=kwargs["config"],
            host_client=kwargs["host_client"], require_remaining=remaining)

    async def source_origin(_backend, **kwargs):
        state.calls.append(("source", kwargs.get("origin_run_id")))
        if state.coverage_error:
            raise ValueError(state.coverage_error)
        row, generation, trigger = await account(origin, kwargs)
        return row, generation, trigger, bound.job.id

    async def report_origin(_backend, **kwargs):
        state.calls.append(("report", kwargs.get("origin_run_id")))
        if kwargs.get("origin_run_id") not in (None, origin.id):
            raise ValueError("terminal_report_origin_changed")
        if state.attempted:
            raise ValueError("terminal_report_contract_already_attempted")
        row, generation, trigger = await account(origin, kwargs)
        return row, generation, trigger, bound.job.id

    async def report_child(_backend, **kwargs):
        state.calls.append(("child", kwargs["child_run_id"]))
        child = await get_run(kwargs["child_run_id"])
        if not child or child.continuation["terminal_report_origin_run_id"] != origin.id:
            raise ValueError("terminal_report_child_origin_changed")
        # The production helper additionally checks its frozen manifest and shared
        # slice claims; this fixture isolates dispatch from those owner's tests.
        if child.continuation.get("fixture_claim_valid") is not True:
            raise ValueError("terminal_report_shared_claim_missing")
        await account(origin, kwargs, remaining=False)
        row, generation, trigger = await account(child, kwargs, remaining=kwargs["require_remaining"])
        scope = origin.continuation["maintenance_scope"]
        if generation != scope["dispatch_generation"] or trigger != scope["trigger_id"]:
            raise ValueError("terminal_report_child_account_changed")
        return row, generation, trigger

    async def close_exhausted(_backend, **kwargs):
        # This dispatch fixture has an unspent account. Full exhausted-owner
        # validation and canonical closure are exercised by real-store tests.
        await account(origin, kwargs, remaining=True)
        return {}

    module = ModuleType("harness_mem.commands.dream_report_continuation")
    module.bound_terminal_report_origin = report_origin
    module.bound_report_child = report_child
    module.close_exhausted_report_child = close_exhausted
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(coverage, "bound_terminal_source_coverage_origin", source_origin)
    bound.backend.structured_store.get_dream_run = get_run
    bound.backend.structured_store.list_dream_runs = list_runs

    def make_child(*, done=False):
        child = copy.deepcopy(origin)
        child.id, child.status = "report-child", "continuing"
        child.continuation.update(
            terminal_report_origin_run_id=origin.id, fixture_claim_valid=True,
            signals=[{"id": "report-target"}],
            completed_signal_indexes=[0] if done else [],
            slice_count=4 if done else 3)
        state.child = state.latest = child
        state.attempted = True
        return child

    state.make_child = make_child
    return state


def worker(bound, monkeypatch):
    import harness_mem.autonomous.worker as owner

    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_a, **_k: True)
    monkeypatch.setattr(owner, "record_post_turn_maintenance_outcome", lambda *_a, **_k: None)

    def forbidden(*_a, **_k):
        raise AssertionError("typed resume cannot intake or restage a source")

    monkeypatch.setattr(owner, "run_autonomous_distill_batch", forbidden)
    monkeypatch.setattr("harness_mem.mcp.tool_handlers.tool_prepare_session_distill", forbidden)
    from harness_mem.commands.maintenance import run_post_turn_maintenance
    return run(run_post_turn_maintenance(
        bound.backend, project_name=bound.run.project_name, project_root=str(bound.root),
        config=bound.config, source="ide_hook", trigger_id="original-session",
        resume_run_id="original-run", host_client="codex"))


def test_failed_pointer_creates_report_child_then_resumes_without_restage(bound, reports, monkeypatch):
    import harness_mem.commands.dream as dream

    first = enqueue(bound)
    assert first["status"] == "queued" and first["run_id"] == "original-run"
    assert first["generation"] == "original-generation" and len(bound.spawned) == 1
    before = bound.path.read_bytes()
    calls = []

    async def tick(_backend, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["report_origin_run_id"] == "original-run"
            assert "coverage_origin_run_id" not in kwargs
            reports.make_child()
            # A wake during the child must coalesce on the original queue pointer.
            queued = await recovery.enqueue_bound_continuation(
                bound.backend, project_name=bound.run.project_name, project_root=str(bound.root),
                config=bound.config, host_client="codex")
            assert queued["coalesced"] and queued["run_id"] == "original-run"
            return {"status": "continuing", "run_id": "report-child"}
        assert kwargs["resume_run_id"] == "report-child"
        reports.child.status = "completed"
        return {"status": "completed", "run_id": "report-child"}

    monkeypatch.setattr(dream, "dream_auto_tick", tick)
    result = worker(bound, monkeypatch)
    assert result["success"] and result["dream_tick"]["run_id"] == "report-child"
    assert len(calls) == 2 and len(bound.spawned) == 1
    assert bound.run.status == "failed" and bound.path.read_bytes() == before
    assert enqueue(bound)["reason"] == "terminal_report_contract_already_attempted"


@pytest.mark.parametrize("reason", ["continuation_usage_unknown_or_active",
    "continuation_source_scope_mismatch", "continuation_budget_exhausted"])
def test_source_coverage_failure_never_falls_through_to_report(bound, reports, reason):
    reports.coverage_error = reason
    result = enqueue(bound)
    assert result["reason"] == reason and not bound.spawned
    assert reports.calls == [("source", None)]


def test_pending_source_coverage_has_priority(bound, reports):
    reports.coverage_error = None
    assert enqueue(bound)["status"] == "queued"
    assert reports.calls == [("source", None)]


@pytest.mark.parametrize("fault,reason", [
    ("ambiguous", "continuation_child_origin_ambiguous"),
    ("empty", "continuation_child_origin_invalid"),
    ("self", "continuation_child_origin_invalid"),
    ("foreign", "terminal_report_child_origin_changed"),
    ("claim", "terminal_report_shared_claim_missing"),
    ("account", "continuation_account_mismatch"),
])
def test_corrupt_report_child_refuses_without_other_account_fallback(bound, reports, fault, reason):
    child = reports.make_child()
    cp = child.continuation
    if fault == "ambiguous":
        cp["terminal_source_coverage_origin_run_id"] = "original-run"
    elif fault == "empty":
        cp["terminal_report_origin_run_id"] = ""
    elif fault == "self":
        cp["terminal_report_origin_run_id"] = child.id
    elif fault == "foreign":
        cp["terminal_report_origin_run_id"] = "other-original"
    elif fault == "claim":
        cp["fixture_claim_valid"] = False
    elif fault == "account":
        cp["maintenance_scope"]["dispatch_generation"] = "another-account"
    result = enqueue(bound)
    assert result["reason"] == reason and not bound.spawned
    assert all(kind not in {"source", "report"} for kind, _ in reports.calls)


@pytest.mark.parametrize("unknown", [False, True])
def test_exhausted_known_account_only_allows_final_bookkeeping(bound, reports, monkeypatch, unknown):
    import harness_mem.commands.dream as dream

    reports.make_child(done=True)
    bound.receipt["calls"][0]["usage"]["output_tokens"] = bound.config.task_model_budget_max_output_tokens
    if unknown:
        bound.receipt["calls"][0]["usage_exact"] = False
    bound.persist()
    calls = []

    async def close(_backend, **kwargs):
        calls.append(kwargs)
        assert kwargs["resume_run_id"] == "report-child"
        reports.child.status = "completed"
        return {"status": "completed", "run_id": "report-child"}

    monkeypatch.setattr(dream, "dream_auto_tick", close)
    result = worker(bound, monkeypatch)
    if unknown:
        assert result["reason"] == "continuation_usage_unknown_or_active" and not calls
    else:
        assert result["success"] and len(calls) == 1
    assert bound.run.status == "failed"


def test_exhausted_account_cannot_dispatch_unfinished_report_signals(bound, reports):
    reports.make_child()
    bound.receipt["calls"][0]["usage"]["output_tokens"] = bound.config.task_model_budget_max_output_tokens
    bound.persist()
    assert enqueue(bound)["reason"] == "continuation_budget_exhausted"
    assert not bound.spawned


def test_another_valid_account_with_credit_cannot_replace_original(bound, reports):
    from harness_mem.autonomous.executors.task_budget import task_budget_receipt_path

    child = reports.make_child()
    child.continuation["maintenance_scope"]["dispatch_generation"] = "another-account"
    alternate = copy.deepcopy(bound.receipt)
    alternate["task_scope"] = "maintenance:original-session:another-account"
    path = task_budget_receipt_path(bound.backend.data_dir, alternate["task_scope"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alternate), encoding="utf-8")
    before = bound.path.read_bytes(), path.read_bytes()
    assert enqueue(bound)["reason"] == "terminal_report_child_account_changed"
    assert not bound.spawned
    assert (bound.path.read_bytes(), path.read_bytes()) == before


@pytest.mark.parametrize("completed", [[-1], [1], [0, 0], [True], "0"])
def test_report_completion_indexes_must_be_exact(bound, reports, completed):
    child = reports.make_child(done=True)
    child.continuation["completed_signal_indexes"] = completed
    assert enqueue(bound)["reason"] == "terminal_report_progress_invalid"
    assert not bound.spawned
