"""Typed Dream handoff routes, isolated from native providers and live data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from harness_mem.commands import dream
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.dream_run import DreamRun


def run(value):
    return asyncio.run(value)


@pytest.fixture
def route(tmp_path, monkeypatch):
    from harness_mem.autonomous.executors import task_budget
    original_scope = {"trigger_id": "original-task", "dispatch_generation": "original-generation"}
    source = {"contract": "explicit-source-handoff-recovery-v1", "binding": {
        "maintenance_scope": original_scope, "source_candidates": [{"handoff_id": str(index)} for index in range(4)]}}
    frozen = {"contract": "explicit-dream-repair-v1", "source": source, "groups": []}
    arms, saves, invocations = [], [], []

    async def no_runs(*args, **kwargs):
        return []

    async def get_run(*args, **kwargs):
        return None

    async def save_run(value):
        saves.append(value)

    async def freeze(*args, **kwargs):
        return frozen

    async def inner(backend, **kwargs):
        invocations.append(kwargs)
        return DreamRun(id=kwargs["_run_id"], project_name="demo", status="completed",
            completed_at=datetime.now(timezone.utc), continuation={"maintenance_scope": kwargs["_maintenance_scope"]})

    backend = SimpleNamespace(data_dir=tmp_path,
        structured_store=SimpleNamespace(list_dream_runs=no_runs, get_dream_run=get_run, save_dream_run=save_run))
    provider = SimpleNamespace(host_client="codex", bind_task_budget=lambda *args, **kwargs: None)
    monkeypatch.setattr(dream, "_freeze_explicit_repair_scope", freeze)
    monkeypatch.setattr(dream, "_dream_once", inner)
    monkeypatch.setattr(task_budget, "arm_provider_maintenance_task", lambda *args, **kwargs: arms.append(kwargs))
    monkeypatch.setattr(task_budget, "task_budget_observation", lambda *args: {})
    return SimpleNamespace(backend=backend, provider=provider, original_scope=original_scope,
        arms=arms, saves=saves, invocations=invocations, frozen=frozen, root=tmp_path)


def request(route, **overrides):
    arguments = dict(project_name="demo", project_root=route.root, config=MergedConfig(),
        source="agent", semantic_provider=route.provider, host_client="codex", repair_scope={"source": {
            "origin_run_id": "origin", "source_job_id": "original-job", "handoff_ids": ["one"],
            "handoff_only": True}, "groups": []})
    arguments.update(overrides)
    return dream.dream_once(route.backend, **arguments)


def test_handoff_route_derives_original_account_without_caller_maintenance_scope(route):
    result = run(request(route))
    assert len(route.arms) == 1
    assert {key: route.arms[0][key] for key in ("trigger_id", "dispatch_generation")} == route.original_scope
    assert route.invocations[0]["_maintenance_scope"] == route.original_scope
    assert result.continuation["maintenance_scope"] == route.original_scope


def test_conflicting_caller_scope_is_rejected_before_account_arm(route):
    with pytest.raises(ValueError, match="source_handoff_original_account_changed"):
        run(request(route, maintenance_scope={"trigger_id": "other-task", "dispatch_generation": "other-generation"}))
    assert route.arms == route.invocations == route.saves == []


def test_real_inner_route_counts_binding_candidates_for_finite_slices(tmp_path, monkeypatch):
    from harness_mem.commands import dream_source_coverage
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "fixture-data")
    run(backend.init())
    source = {"contract": "explicit-source-handoff-recovery-v1",
              "binding": {"source_candidates": [{"handoff_id": str(index)} for index in range(4)]}}

    async def completed_source(*args, **kwargs):
        return {"status": "no_write", "pending": False}

    monkeypatch.setattr(dream_source_coverage, "run_explicit_source_repair", completed_source)
    try:
        result = run(dream._dream_once(backend, project_name="demo", project_root=tmp_path,
            config=MergedConfig(), source="agent", semantic_provider=SimpleNamespace(),
            _run_id="isolated-route", _explicit_repair={"contract": "explicit-dream-repair-v1",
                "source": source, "groups": []},
            _maintenance_scope={"trigger_id": "original-task", "dispatch_generation": "original-generation"}))
        assert result.continuation["max_slices"] == 9
        assert result.continuation["slice_count"] == 1
        assert result.status == "completed"
    finally:
        run(backend.close())


def test_audit_route_passes_exact_recovery_run_reference(tmp_path, monkeypatch):
    from harness_mem.commands import dream_source_audit
    observed = []

    async def prepare(*args, **kwargs):
        observed.append(kwargs)
        return {"contract": "explicit-dream-source-audit-v1"}

    monkeypatch.setattr(dream_source_audit, "prepare_explicit_source_audit", prepare)
    result = run(dream._freeze_explicit_repair_scope(SimpleNamespace(), project_name="demo",
        project_root=tmp_path, run_id="audit-child", scope={"groups": [], "source": {
            "origin_run_id": "original-failed-audit", "predecessor_ids": ["old-predecessor"],
            "audit_only": True, "resolved_handoff_run_id": "real-recovery-child"}}))
    assert result["source"]["contract"] == "explicit-dream-source-audit-v1"
    assert observed[0]["origin_run_id"] == "original-failed-audit"
    assert observed[0]["resolved_handoff_run_id"] == "real-recovery-child"
    assert observed[0]["predecessor_ids"] == ["old-predecessor"]
