from __future__ import annotations

import asyncio
from pathlib import Path

import harness_mem.mcp.tool_handlers as tool_handlers
import pytest
from harness_mem.commands.maintenance import run_post_turn_maintenance
from harness_mem.config.merge import MergedConfig
from harness_mem.embedding import embeddings_disabled


class _DistillJobs:
    def __init__(self, job=None):
        self.job = job

    def get_distill_job(self, _job_id: str):
        return self.job


class _Job:
    id = "distill-1"

    def __init__(self, status: str):
        self.status = status

    def to_dict(self):
        return {"id": self.id, "status": self.status}


class _Backend:
    def __init__(self, data_dir: Path, job=None):
        self.data_dir = data_dir
        self.transcript_store = _DistillJobs(job)


def test_stop_maintenance_defers_embedding_model_loading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: dict[str, bool | int | str | None] = {}

    def fake_prepare_session_distill(**kwargs):
        observed["embeddings_disabled"] = embeddings_disabled()
        observed["limit"] = kwargs["limit"]
        observed["session_id"] = kwargs["session_id"]
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
            trigger_id="current-session",
        )
    )

    assert payload["success"] is True
    assert observed["embeddings_disabled"] is True
    assert observed["limit"] == 1
    assert observed["session_id"] == "current-session"
    assert embeddings_disabled() is False


def test_stop_maintenance_retries_exact_trigger_until_native_session_is_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    attempts = 0

    def fake_prepare_session_distill(**kwargs):
        nonlocal attempts
        attempts += 1
        assert kwargs["session_id"] == "new-native-session"
        if attempts < 3:
            return {
                "success": False,
                "error": "session_id is not available for this project",
            }
        return {
            "success": True,
            "observation_count": 1,
            "distill_job_id": None,
        }

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        fake_prepare_session_distill,
    )
    monkeypatch.setattr("harness_mem.commands.maintenance.asyncio.sleep", no_wait)

    payload = asyncio.run(
        run_post_turn_maintenance(
            _Backend(tmp_path),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            source="ide_hook",
            trigger_id="new-native-session",
        )
    )

    assert payload["success"] is True
    assert payload["summary"]["evidence_ingest_attempts"] == 3
    assert payload["summary"]["evidence_ingest_wait_seconds"] >= 0


def test_stop_maintenance_does_not_retry_unrelated_ingest_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    attempts = 0

    def fake_prepare_session_distill(**_kwargs):
        nonlocal attempts
        attempts += 1
        return {"success": False, "error": "repository unavailable"}

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
            source="ide_hook",
            trigger_id="new-native-session",
        )
    )

    assert payload["success"] is False
    assert attempts == 1
    assert payload["summary"]["evidence_ingest_attempts"] == 1


@pytest.mark.parametrize(
    ("job_status", "expected_status", "queued"),
    (
        ("queued", "queued", True),
        ("parked", "queued", True),
        ("processing", "in_progress", False),
        ("reviewing", "in_progress", False),
        ("completed", "completed", False),
    ),
)
def test_stop_maintenance_reports_lossless_job_from_transcript_store(
    tmp_path: Path,
    monkeypatch,
    job_status: str,
    expected_status: str,
    queued: bool,
) -> None:
    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        lambda **_kwargs: {
            "success": True,
            "observation_count": 0,
            "distill_job_id": "distill-1",
        },
    )

    payload = asyncio.run(
        run_post_turn_maintenance(
            _Backend(tmp_path, _Job(job_status)),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
        )
    )

    assert payload["status"] == expected_status
    assert payload["distill_job"] == {"id": "distill-1", "status": job_status}
    assert payload["summary"]["distill_queued"] is queued
    assert payload["summary"]["distill_job_id"] == "distill-1"
