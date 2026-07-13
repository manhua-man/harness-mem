from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from harness_mem.commands.distill_lifecycle import (
    pending_distill_jobs,
    render_pending_distill_instruction,
    stage_distill_job,
)
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
        instruction = render_pending_distill_instruction(
            pending_distill_jobs(backend, project_name="demo")
        )
        assert "prepare_session_distill" in instruction
        assert "auto_review_candidates(apply=true)" in instruction
        assert "runs Dream" in instruction
        assert "summarized until those steps finish" in instruction
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
