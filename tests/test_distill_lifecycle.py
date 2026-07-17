from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.distill_lifecycle import (
    distill_drainer_metrics,
    pending_distill_jobs,
    render_pending_distill_instruction,
    stage_distill_job,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


def test_distill_job_is_deduplicated_and_rendered(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        first = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-1", "obs-2"],
            source="ide_hook",
        )
        second = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-2", "obs-1"],
            source="ide_hook",
        )

        assert first is not None
        assert second is not None
        assert second.id == first.id
        assert pending_distill_jobs(backend, project_name="demo") == []
        assert render_pending_distill_instruction([]) == ""
    finally:
        _run(backend.close())


def test_agent_active_drainer_enforces_daily_new_job_budget(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        for index in range(3):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"session-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        timestamp=now,
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )

        first = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            daily_job_budget=1,
            now=now,
        )
        second = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=2,
            daily_job_budget=1,
            now=now,
        )
        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=1,
            now=now,
        )
        instruction = render_pending_distill_instruction(first, metrics=metrics)

        assert len(first) == 1
        assert [job.id for job in second] == [job.id for job in first]
        assert metrics["active"] == 2
        assert metrics["parked"] == 1
        assert metrics["offered_today"] == 1
        assert metrics["daily_budget_remaining"] == 0
        assert metrics["state"] == "waiting_for_agent"
        assert metrics["background_semantic_processing"] is False
        assert "State: waiting_for_agent" in instruction
        assert "three recent jobs, then one oldest" in instruction
    finally:
        _run(backend.close())


def test_agent_active_drainer_only_charges_jobs_emitted_to_agent(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    try:
        for index in range(3):
            _run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"session-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        timestamp=now,
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(tmp_path),
                    client="codex",
                    session_id=f"session-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///session-{index}.jsonl",
                    source_text=f"source {index}",
                )
            )

        offered = pending_distill_jobs(
            backend,
            project_name="demo",
            target_backlog=3,
            max_jobs=1,
            daily_job_budget=3,
            now=now,
        )
        metrics = distill_drainer_metrics(
            backend,
            project_name="demo",
            daily_job_budget=3,
            now=now,
        )

        assert len(offered) == 1
        assert metrics["active"] == 3
        assert metrics["offered_today"] == 1
        assert metrics["daily_budget_remaining"] == 2
    finally:
        _run(backend.close())


def test_auto_review_completes_distill_job_then_runs_dream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.distill-lifecycle"),
    )
    try:
        job = stage_distill_job(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            observation_ids=["obs-1"],
            source="agent",
        )
        assert job is not None
        job.status = "processing"
        backend.reflection_job_store.save(job)

        async def fake_dream(*_args, **_kwargs):
            return {"success": True, "status": "completed", "job_id": "dream-1"}

        monkeypatch.setattr(tool_handlers, "dream_auto_tick", fake_dream)
        payload = tool_handlers.tool_auto_review_candidates("demo", apply=True)

        assert payload["distill_jobs_completed"] == [job.id]
        assert payload["dream"]["job_id"] == "dream-1"
        reloaded = backend.reflection_job_store.get(job.id)
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.phase == "done"
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        _run(backend.close())
