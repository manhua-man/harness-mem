from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

import pytest

import harness_mem.commands.dream as dream_module
import harness_mem.commands.maintenance as maintenance_module
import harness_mem.embedding as embedding_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.commands.dream import (
    DreamSchedulerDecision,
    dream_auto_tick,
    dream_once,
    dream_status_snapshot,
    latest_dream_ledger,
)
from harness_mem.commands.maintenance import run_post_turn_maintenance
from harness_mem.commands.metabolism_pass import MetabolismPass
from harness_mem.commands.metabolism_pass import _load_pool_embeddings
from harness_mem.commands.replay_window import ReplayWindow
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.embedding import embeddings_disabled, temporarily_disable_embeddings
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.sqlite_index import SQLiteIndex


def _run(coro):
    return asyncio.run(coro)


async def _new_backend(data_dir: Path) -> LocalMemoryBackend:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    return backend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = _run(_new_backend(tmp_path))
    try:
        yield backend
    finally:
        _run(backend.close())


def _empty_window() -> ReplayWindow:
    now = datetime.now(timezone.utc)
    return ReplayWindow(
        time_range=(now - timedelta(days=1), now),
        dimensions={},
    )


def test_dream_supersede_candidates_wait_for_explicit_review(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="supersede-review-token old local-first storage decision",
                source="test",
                status="user_confirmed",
            )
        )
    )
    new_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="supersede-review-token new canonical storage decision",
                source="test",
                status="user_confirmed",
            )
        )
    )
    candidate = SupersedeCandidate(
        project_name="demo",
        target_type="memory_entry",
        target_id=old_id,
        replacement_type="memory_entry",
        replacement_id=new_id,
        reason="New current decision supersedes the old one.",
        evidence="dream found matching evidence",
        source="test",
        confidence=0.92,
    )

    async def fake_select_metabolism_pass(*_args, **_kwargs) -> MetabolismPass:
        return MetabolismPass(
            window=_empty_window(),
            merge=[],
            stale=[],
            supersede=[candidate],
            notes=["fake supersede pass"],
        )

    monkeypatch.setattr(
        dream_module,
        "select_metabolism_pass",
        fake_select_metabolism_pass,
    )

    run = _run(dream_once(backend, project_name="demo", config=None, source="agent"))

    reloaded_candidate = _run(backend.structured_store.get_supersede_candidate(candidate.id))
    old_entry = _run(backend.structured_store.get_memory_entry(old_id))
    new_entry = _run(backend.structured_store.get_memory_entry(new_id))

    assert reloaded_candidate is not None
    assert reloaded_candidate.status == "pending"
    assert old_entry is not None
    assert old_entry.valid_to is None
    assert old_entry.superseded_by == []
    assert new_entry is not None
    assert new_entry.supersedes == []
    assert run.handling_summary["pending_review"] == 1
    assert run.handling_summary["applied"] == 0
    assert run.items[0].final_action == "pending_review"
    assert run.items[0].result["candidate_status"] == "pending"
    assert run.items[0].result["review_action"] == {
        "tool": "govern_memory",
        "action": "supersede",
        "decisions": ["confirm", "reject"],
    }


def test_dream_auto_tick_persists_skipped_receipt_separately_from_runs(
    backend,
    tmp_path: Path,
) -> None:
    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_enabled=False),
            source="ide_hook",
            trigger_id="turn-42",
        )
    )

    assert payload["status"] == "skipped"
    assert payload["reason"] == "dream.auto.enabled is false"
    assert payload["tick_receipt"] == {"state": "recorded"}

    second_payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_enabled=False),
            source="ide_hook",
            trigger_id="turn-43",
        )
    )
    assert second_payload["tick_receipt"] == {"state": "recorded"}

    ledger = _run(latest_dream_ledger(backend, project_name="demo"))
    assert ledger["run"] is None
    assert [item["trigger_id"] for item in ledger["recent_ticks"]] == [
        "turn-42",
        "turn-43",
    ]
    assert ledger["last_tick"] == ledger["recent_ticks"][-1]
    assert ledger["last_tick"] == {
        "timestamp": ledger["last_tick"]["timestamp"],
        "status": "skipped",
        "reason": "dream.auto.enabled is false",
        "source": "ide_hook",
        "trigger_id": "turn-43",
        "job_id": None,
        "run_id": None,
        "last_run_id": None,
        "next_eligible_at": None,
        "receipt_state": "recorded",
    }

    status = _run(
        dream_status_snapshot(
            backend,
            project_name="demo",
            config=MergedConfig(dream_auto_enabled=False),
        )
    )
    assert status["last_tick_status"] == "skipped"
    assert status["last_tick_reason"] == "dream.auto.enabled is false"
    assert status["last_run_id"] is None


def test_reflection_job_claim_is_atomic_across_independent_connections(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reflection-jobs.sqlite"
    indexes = [SQLiteIndex(db_path), SQLiteIndex(db_path)]
    for index in indexes:
        index.init_db()
    stores = [ReflectionJobStore(index) for index in indexes]
    barrier = threading.Barrier(2)
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=5)

    def claim(slot: int):
        job = ReflectionJob(
            project_name="demo",
            project_root=str(tmp_path),
            kind="dream",
            phase="metabolism",
            status="processing",
            source="ide_hook",
        )
        barrier.wait()
        return stores[slot].save_if_no_active_processing(
            job,
            stale_before=stale_before,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, (0, 1)))
        assert sum(result is None for result in results) == 1
        assert sum(result is not None for result in results) == 1
        assert len(stores[0].list(project_name="demo", status="processing")) == 1
    finally:
        for index in indexes:
            index.close()


def test_dream_rechecks_eligibility_after_winning_durable_claim(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = iter(
        (
            DreamSchedulerDecision(True, "eligible for dream run"),
            DreamSchedulerDecision(
                False,
                "no new project activity since the last dream run",
                last_run_id="other-run",
            ),
        )
    )

    async def fake_decision(*_args, **_kwargs):
        return next(decisions)

    async def fail_run(*_args, **_kwargs):
        raise AssertionError("stale eligibility must not start a second Dream")

    monkeypatch.setattr(dream_module, "dream_scheduler_decision", fake_decision)
    monkeypatch.setattr(dream_module, "_run_dream_with_progress_timeout", fail_run)

    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            source="ide_hook",
        )
    )

    assert payload["status"] == "skipped"
    assert payload["last_run_id"] == "other-run"
    jobs = backend.reflection_job_store.list(project_name="demo", kind="dream")
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert jobs[0].phase == "done"


def test_idle_scheduler_reports_activity_based_next_eligible_time(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    latest_activity = now - timedelta(minutes=5)

    async def fake_latest_activity(*_args, **_kwargs):
        return latest_activity

    monkeypatch.setattr(dream_module, "_now", lambda: now)
    monkeypatch.setattr(
        dream_module,
        "_latest_project_activity",
        fake_latest_activity,
    )

    decision = _run(
        dream_module.dream_scheduler_decision(
            backend,
            project_name="demo",
            config=MergedConfig(
                dream_auto_trigger="idle",
                dream_auto_idle_seconds=900,
            ),
        )
    )

    assert decision.eligible is False
    assert decision.next_eligible_at == latest_activity + timedelta(minutes=15)


def test_dream_wall_clock_timeout_fails_job_and_records_tick(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def always_eligible(*_args, **_kwargs):
        return DreamSchedulerDecision(True, "eligible for dream run")

    async def blocked_dream(run_backend, **kwargs):
        await run_backend.structured_store.save_dream_run(
            DreamRun(
                project_name="demo",
                status="processing",
                reflection_job_id=kwargs["reflection_job_id"],
                trigger_source="ide_hook",
            )
        )
        await asyncio.Event().wait()

    monkeypatch.setattr(dream_module, "dream_scheduler_decision", always_eligible)
    monkeypatch.setattr(dream_module, "dream_once", blocked_dream)

    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_max_runtime_seconds=1),
            source="ide_hook",
            trigger_id="timeout-turn",
        )
    )

    assert payload["status"] == "failed"
    assert payload["error"] == "dream runtime exceeded max_runtime_seconds"
    assert payload["tick_receipt"] == {"state": "recorded"}
    jobs = backend.reflection_job_store.list(project_name="demo", kind="dream")
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert jobs[0].phase == "done"
    assert jobs[0].completed_at is not None
    runs = _run(backend.structured_store.list_dream_runs("demo", limit=10))
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].completed_at is not None
    assert "dream runtime exceeded" in " ".join(runs[0].notes or [])


def test_disabled_embedding_context_uses_only_persisted_vectors(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [
        _run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content=f"entry {index}",
                    source="test",
                    status="user_confirmed",
                )
            )
        )
        for index in range(2)
    ]

    def fail_loader(*_args, **_kwargs):
        raise AssertionError("post-turn Dream must not load an embedding model")

    monkeypatch.setattr(embedding_module, "get_model_loader", fail_loader)
    with temporarily_disable_embeddings():
        assert embeddings_disabled() is True
        vectors = _run(
            _load_pool_embeddings(
                backend,
                backend.structured_store,
                ids,
            )
        )
    assert vectors == {}


def test_post_turn_runs_dream_before_ingest_with_embeddings_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class DistillJobs:
        @staticmethod
        def get_distill_job(_job_id: str):
            return None

    class Backend:
        data_dir = tmp_path
        transcript_store = DistillJobs()

    async def fake_dream_tick(_backend, **kwargs):
        assert embeddings_disabled() is True
        assert kwargs["trigger_id"] == "turn-99"
        observed.append("dream")
        return {
            "success": True,
            "status": "skipped",
            "reason": "scheduler gates have not elapsed",
            "tick_receipt": {"state": "recorded"},
        }

    def fake_prepare_session_distill(**_kwargs):
        assert embeddings_disabled() is True
        observed.append("ingest")
        return {
            "success": True,
            "observation_count": 0,
            "distill_job_id": None,
        }

    monkeypatch.setattr(maintenance_module, "dream_auto_tick", fake_dream_tick)
    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        fake_prepare_session_distill,
    )

    payload = _run(
        run_post_turn_maintenance(
            Backend(),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            trigger_id="turn-99",
        )
    )

    assert observed == ["dream", "ingest"]
    assert payload["dream_tick"]["status"] == "skipped"
    assert payload["summary"]["dream_tick_receipt_state"] == "recorded"
