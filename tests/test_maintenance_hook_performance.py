from __future__ import annotations

import asyncio
from pathlib import Path

import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.commands.maintenance import run_post_turn_maintenance
from harness_mem.config.merge import MergedConfig
from harness_mem.embedding import embeddings_disabled


class _ReflectionJobs:
    def get(self, _job_id: str):
        return None


class _Backend:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.reflection_job_store = _ReflectionJobs()


def test_stop_maintenance_defers_embedding_model_loading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: dict[str, bool | int] = {}

    def fake_prepare_session_distill(**kwargs):
        observed["embeddings_disabled"] = embeddings_disabled()
        observed["limit"] = kwargs["limit"]
        return {
            "success": True,
            "observation_count": 1,
            "distill_job_id": None,
        }

    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        fake_prepare_session_distill,
    )

    payload = asyncio.run(
        run_post_turn_maintenance(
            _Backend(tmp_path),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
        )
    )

    assert payload["success"] is True
    assert observed["embeddings_disabled"] is True
    assert observed["limit"] == 1
    assert embeddings_disabled() is False
