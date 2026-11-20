"""Legacy migration uses only isolated receipts and in-process transports."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult,
    TaskBudgetRefusal,
    bind_maintenance_task,
    dispatch_with_task_budget,
    read_task_budget_receipt,
    seed_legacy_task_budget,
)
from harness_mem.autonomous.worker import autonomous_receipt_path
from harness_mem.commands import dream
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import DreamRun
from harness_mem.core.schemas.session_distill import SessionDistillJob


@pytest.fixture
def legacy(tmp_path):
    rows = [
        ("s1", 70449, 6465, 141.8992344000144),
        ("s2", 79955, 8123, 149.34238360007294),
        ("s3", 18285, 8231, 160.23513739998452),
        ("s4", 18478, 5036, 97.65077560010832),
        ("s5", 92178, 6179, 123.13549819996115),
        ("d1", 11227, 4585, 90.1842755000107),
    ]
    native = [
        {
            "call_id": cid,
            "status": "completed",
            "model_dispatched": True,
            "unknown_response_usage_count": 0,
            "duration_seconds": seconds,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": inp + out,
            },
        }
        for cid, inp, out, seconds in rows
    ]
    root = tmp_path / "workspace"
    job = SessionDistillJob(
        id="job",
        idempotency_key="legacy-job",
        source_id="source",
        project_name="project",
        project_root=str(root),
        client="codex",
        status="completed",
        session_id="session",
        source_revision="sha256:source",
    )
    provider = {
        "job_id": "job",
        "source_revision": job.source_revision,
        "host_client": "codex",
        "unknown_native_call_usage_count": 0,
        "attempt_count": 5,
        "input_tokens": 279345,
        "output_tokens": 34034,
        "total_tokens": 313379,
        "native_attempts": native[:5],
    }
    completion = {
        "job_id": "job",
        "client": "codex",
        "session_id": "session",
        "trigger_id": "session",
        "dispatch_generation": "original",
        "provider": provider,
    }
    receipt = {"last_verified_completion": completion}
    path = autonomous_receipt_path(tmp_path, project_name="project", project_root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    run = DreamRun(
        id="legacy",
        project_name="project",
        status="continuing",
        notes=[
            "Hook session distill succeeded: job",
            "dream verification receipt: "
            + json.dumps(
                {
                    "usage_unknown": False,
                    "native_attempts": native[5:],
                    "results": [native[5]["usage"]],
                    "target_ids": ["t1", "t2", "t3", "t4"],
                }
            ),
        ],
        continuation={
            "version": "dream-slices-v3",
            "slice_count": 1,
            "completed_signal_indexes": [0, 1, 2, 3],
            "signals": [
                {"target_ids": [target]} for target in ["t1", "t2", "t3", "t4"]
            ],
            "verification": {target: {} for target in ["t1", "t2", "t3", "t4"]},
        },
    )
    backend = SimpleNamespace(
        data_dir=tmp_path,
        transcript_store=SimpleNamespace(
            get_distill_job=lambda jid: job if jid == "job" else None,
            get_revision=lambda source_id, source_revision: None,
        ),
    )
    return backend, run, root, receipt, path


def recover(legacy):
    backend, run, root, _, _ = legacy
    scope, calls = dream._legacy_dream_accounting(
        backend, run, project_root=root, host_client="codex"
    )
    binding = bind_maintenance_task(
        data_dir=backend.data_dir, host_client="codex", config=MergedConfig(), **scope
    )
    return binding, calls


def test_recovery_preserves_six_exact_calls_and_idempotence(legacy):
    binding, calls = recover(legacy)
    first = seed_legacy_task_budget(
        binding, calls=calls + calls[-1:], legacy_run_id="legacy"
    )
    assert len(first["calls"]) == 6
    assert sum(c["usage"]["input_tokens"] for c in first["calls"]) == 290572
    assert sum(c["usage"]["output_tokens"] for c in first["calls"]) == 38619
    assert sum(c["reserved"]["seconds"] for c in first["calls"]) == 766
    assert binding.task_scope == "maintenance:session:original"
    assert (
        seed_legacy_task_budget(binding, calls=calls, legacy_run_id="legacy") == first
    )
    dispatch_with_task_budget(
        binding,
        transport=lambda req: NativeDispatchResult(
            status="completed",
            input_tokens=10,
            output_tokens=5,
            duration_seconds=1,
            usage_exact=True,
        ),
        timeout_seconds=30,
        phase="dream",
        slice_id="continued",
    )
    assert (
        len(read_task_budget_receipt(binding.data_dir, binding.task_scope)["calls"])
        == 7
    )
    assert (
        len(
            seed_legacy_task_budget(binding, calls=calls, legacy_run_id="legacy")[
                "calls"
            ]
        )
        == 7
    )


@pytest.mark.parametrize(
    "bad",
    [
        "foreign_host",
        "foreign_source",
        "foreign_job",
        "unknown",
        "ambiguous",
        "missing",
    ],
)
def test_refuses_unbound_or_incomplete_old_account(legacy, bad):
    backend, run, root, receipt, path = legacy
    completion = receipt["last_verified_completion"]
    if bad == "foreign_host":
        completion["client"] = "hermes"
    if bad == "foreign_source":
        completion["provider"]["source_revision"] = "sha256:other"
    if bad == "foreign_job":
        completion["job_id"] = "other"
    if bad == "unknown":
        completion["provider"]["unknown_native_call_usage_count"] = 1
    if bad == "ambiguous":
        run.notes.append("Hook session distill succeeded: other")
    if bad == "missing":
        receipt.clear()
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(TaskBudgetRefusal, match="cannot be linked"):
        dream._legacy_dream_accounting(
            backend, run, project_root=root, host_client="codex"
        )
    assert not list(
        (backend.data_dir / "autonomous/receipts/task-model-budget").glob("*.json")
    )


def test_unknown_duplicate_and_mode_change_refused(legacy):
    binding, calls = recover(legacy)
    broken = [dict(row) for row in calls]
    broken[0]["unknown_response_usage_count"] = 1
    with pytest.raises(TaskBudgetRefusal):
        seed_legacy_task_budget(binding, calls=broken, legacy_run_id="legacy")
    conflicting = {**calls[0], "duration_seconds": 1}
    with pytest.raises(TaskBudgetRefusal):
        seed_legacy_task_budget(
            binding, calls=calls + [conflicting], legacy_run_id="legacy"
        )
    seed_legacy_task_budget(binding, calls=calls, legacy_run_id="legacy")
    strict = replace(
        binding,
        config=replace(MergedConfig(), task_model_budget_host_max_output_tokens=10),
    )
    with pytest.raises(TaskBudgetRefusal):
        seed_legacy_task_budget(strict, calls=calls, legacy_run_id="legacy")


def test_actual_dream_owner_persists_old_scope_before_continuation(legacy, monkeypatch):
    backend, run, root, _, _ = legacy
    events = []

    class Store:
        async def get_dream_run(self, rid):
            return run

        async def list_dream_runs(self, project, limit):
            return [run]

        async def save_dream_run(self, value):
            assert value.continuation.get("maintenance_scope") == {
                "trigger_id": "session",
                "dispatch_generation": "original",
            }
            events.append("saved")

    backend.structured_store = Store()
    provider = SimpleNamespace(
        host_client="codex", bind_task_budget=lambda *a, **k: events.append("bound")
    )

    async def fake_once(*args, **kwargs):
        assert events[:2] == ["saved", "bound"]
        assert kwargs["_maintenance_scope"]["dispatch_generation"] == "original"
        binding, _ = recover(legacy)
        assert (
            len(read_task_budget_receipt(backend.data_dir, binding.task_scope)["calls"])
            == 6
        )
        return run

    monkeypatch.setattr(dream, "_dream_once", fake_once)
    asyncio.run(
        dream.dream_once(
            backend,
            project_name="project",
            project_root=root,
            config=MergedConfig(),
            semantic_provider=provider,
            resume_run_id="legacy",
            maintenance_scope={
                "trigger_id": "session",
                "dispatch_generation": "later-stop",
            },
        )
    )


def test_natural_owner_migrates_before_source_receipt_overwrite(legacy, monkeypatch):
    from harness_mem.autonomous import worker
    from harness_mem import maintenance_lock

    backend, run, root, _, _ = legacy
    events = []

    class Store:
        async def list_dream_runs(self, project, limit):
            return [run]

        async def save_dream_run(self, value):
            assert (
                value.continuation["maintenance_scope"]["dispatch_generation"]
                == "original"
            )
            events.append("saved")

    backend.structured_store = Store()
    monkeypatch.setattr(
        maintenance_lock, "maintenance_is_locked", lambda *a, **k: False
    )
    monkeypatch.setattr(
        dream,
        "background_status",
        lambda *a, **k: SimpleNamespace(ready=True, selected_cli="codex"),
    )

    def stop_before_source_transport(*args, **kwargs):
        assert events == ["saved"]
        binding, _ = recover(legacy)
        assert (
            len(read_task_budget_receipt(backend.data_dir, binding.task_scope)["calls"])
            == 6
        )
        raise RuntimeError("source transport deliberately blocked")

    monkeypatch.setattr(
        worker, "run_autonomous_distill_batch", stop_before_source_transport
    )
    with pytest.raises(RuntimeError, match="deliberately blocked"):
        asyncio.run(
            dream._dream_auto_tick_core(
                backend,
                project_name="project",
                project_root=str(root),
                config=MergedConfig(),
                source="ide_hook",
                trigger_id="session",
                trigger_job_id="job",
                host_client="codex",
            )
        )


@pytest.mark.parametrize(
    "bad",
    [
        "missing_dream_note",
        "empty_dream_native",
        "source_total",
        "source_unknown_alias",
        "dream_total",
        "dream_host",
        "missing_target_receipt",
    ],
)
def test_rejects_incomplete_or_inconsistent_accounting(legacy, bad):
    _, run, _, receipt, path = legacy
    provider = receipt["last_verified_completion"]["provider"]
    recorded = json.loads(run.notes[-1].split(": ", 1)[1])
    if bad == "missing_dream_note":
        run.notes.pop()
    elif bad == "empty_dream_native":
        recorded["native_attempts"] = []
    elif bad == "source_total":
        provider["total_tokens"] = 1
    elif bad == "source_unknown_alias":
        provider["unknown_attempt_count"] = 1
    elif bad == "dream_total":
        recorded["native_attempts"][0]["usage"]["total_tokens"] = 1
    elif bad == "dream_host":
        recorded["native_attempts"][0]["host_client"] = "hermes"
    elif bad == "missing_target_receipt":
        recorded["target_ids"] = ["t1"]
    if bad != "missing_dream_note":
        run.notes[-1] = "dream verification receipt: " + json.dumps(recorded)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(TaskBudgetRefusal):
        recover(legacy)


def test_old_account_failure_does_not_block_independent_source(legacy, monkeypatch):
    from harness_mem.autonomous import worker
    from harness_mem import maintenance_lock

    backend, run, root, _, _ = legacy
    run.notes.pop()
    events = []

    class Store:
        async def list_dream_runs(self, *a, **k):
            return [run]

        async def save_dream_run(self, value):
            assert "maintenance_scope" not in value.continuation
            assert (
                value.continuation["legacy_accounting_failure"]["code"]
                == "remaining_not_demonstrable"
            )
            events.append("old_failure_saved")

    backend.structured_store = Store()
    monkeypatch.setattr(
        maintenance_lock, "maintenance_is_locked", lambda *a, **k: False
    )
    monkeypatch.setattr(
        dream,
        "background_status",
        lambda *a, **k: SimpleNamespace(ready=True, selected_cli="codex"),
    )

    def independent_source(*a, **k):
        events.append("new_source_processed")
        return {
            "success": True,
            "state": "completed",
            "outcomes": [{"status": "completed"}],
        }

    monkeypatch.setattr(worker, "run_autonomous_distill_batch", independent_source)

    async def record_tick(*a, **k):
        return k["payload"]

    monkeypatch.setattr(dream, "_record_dream_tick", record_tick)
    result = asyncio.run(
        dream._dream_auto_tick_core(
            backend,
            project_name="project",
            project_root=str(root),
            config=MergedConfig(),
            source="ide_hook",
            trigger_id="session",
            trigger_job_id="job",
            host_client="codex",
        )
    )
    assert events == ["old_failure_saved", "new_source_processed"]
    assert result["status"] == "failed"
    assert result["session_distill"]["completed"] == 1
    assert not list(
        (backend.data_dir / "autonomous/receipts/task-model-budget").glob("*.json")
    )
