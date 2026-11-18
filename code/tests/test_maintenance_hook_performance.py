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
    client = "codex"

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
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    assert embeddings_disabled() is False
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
            config=MergedConfig(dream_auto_enabled=False),
            trigger_id="current-session",
        )
    )

    assert payload["success"] is True, payload
    assert observed["embeddings_disabled"] is True
    assert observed["limit"] == 1
    assert observed["session_id"] == "current-session"
    assert embeddings_disabled() is False


def test_stop_maintenance_does_not_stage_an_excluded_maintenance_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from harness_mem.maintenance_lock import exclusive_maintenance_run

    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("excluded maintenance must not stage a distill job")
        ),
    )
    with exclusive_maintenance_run(
        tmp_path,
        run_id="archive-run",
        operation="archive-distill",
        owner_session_ids=["maintenance-session"],
    ):
        pass

    payload = asyncio.run(
        run_post_turn_maintenance(
            _Backend(tmp_path),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            source="ide_hook",
            trigger_id="maintenance-session",
        )
    )

    assert payload["success"] is True
    assert payload["status"] == "skipped"
    assert payload["distill_job"] is None
    assert payload["summary"]["maintenance_excluded"] is True


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
            config=MergedConfig(dream_auto_enabled=False),
            source="ide_hook",
            trigger_id="new-native-session",
        )
    )

    assert payload["success"] is True, payload
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
    async def skip_background_dream(*_args, **kwargs):
        assert kwargs["trigger_job_id"] == "distill-1"
        return {"success": True, "status": "skipped"}

    monkeypatch.setattr("harness_mem.commands.maintenance.dream_auto_tick", skip_background_dream)
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

    assert payload["status"] == expected_status, payload
    assert payload["distill_job"] == {"id": "distill-1", "status": job_status}
    assert payload["summary"]["distill_queued"] is queued
    assert payload["summary"]["distill_job_id"] == "distill-1"


@pytest.mark.parametrize("scenario", ("new_activity", "exclusive", "lease_lost", "finite", "unstaged"))
def test_started_natural_dream_continuation_keeps_ownership_boundaries(
    tmp_path: Path, monkeypatch, scenario: str,
) -> None:
    import harness_mem.autonomous.worker as worker
    import harness_mem.commands.maintenance as maintenance
    import harness_mem.data_lifecycle as lifecycle
    import harness_mem.hook_background as background
    import harness_mem.maintenance_lock as locks

    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    calls: list[dict] = []
    recorded: list[dict] = []
    lease_checks: list[bool] = []
    scope = {"task_scope": "original-maintenance-task", "known_usage": ["source-call"]}

    async def retain_sources(*_args, **_kwargs):
        return {"deleted": 0}

    monkeypatch.setattr(lifecycle, "enforce_transcript_retention", retain_sources)
    monkeypatch.setattr(tool_handlers, "tool_prepare_session_distill", lambda **_kwargs: {
        "success": scenario != "unstaged", "observation_count": 1,
        "distill_job_id": "distill-1" if scenario != "unstaged" else None,
        "reason_codes": ["session_not_found"] if scenario == "unstaged" else [],
    })
    monkeypatch.setattr(locks, "maintenance_is_locked", lambda *_args, **_kwargs:
        scenario == "exclusive" and bool(calls))
    monkeypatch.setattr(worker, "record_post_turn_maintenance_outcome",
                        lambda *_args, **kwargs: recorded.append(kwargs))

    def heartbeat(*_args, **_kwargs):
        lease_checks.append(True)
        return scenario != "lease_lost"

    monkeypatch.setattr(background, "heartbeat_background_worker", heartbeat)

    async def tick(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1 and scenario == "new_activity":
            background.record_background_activity(
                tmp_path, project_root=tmp_path, client="codex",
                session_id="natural-session", now=101.0,
            )
            # The same marker must still cancel a not-yet-started idle request.
            assert background.background_request_cancelled(tmp_path, background.BackgroundRequest(
                generation="original-generation", project_root=str(tmp_path),
                client="codex", source="ide_hook", trigger_id="natural-session", requested_at=100.0,
            ))
        elif len(calls) > 1:
            assert kwargs["resume_run_id"] == "original-dream-run"
            assert kwargs["trigger_job_id"] is None
        return {
            "status": "completed" if scenario == "new_activity" and len(calls) == 2 else "continuing",
            "run_id": "original-dream-run",
            "continuation": {"max_slices": 2, "task_budget": scope},
        }

    monkeypatch.setattr(maintenance, "dream_auto_tick", tick)
    payload = asyncio.run(run_post_turn_maintenance(
        _Backend(tmp_path, _Job("completed")), project_name="demo", project_root=str(tmp_path),
        config=MergedConfig(), source="ide_hook", trigger_id="natural-session",
        background_requested_at=100.0,
    ))
    result = payload["dream_tick"]
    assert len(recorded) == 1
    assert recorded[0]["dream"] == result
    if scenario == "unstaged":
        assert calls == []
        assert lease_checks == []
        assert result["reason"] == "triggering_session_not_staged"
        return
    assert calls[0]["trigger_job_id"] == "distill-1"
    assert all(call["trigger_id"] == "natural-session" for call in calls)
    assert result["continuation"]["task_budget"] is scope
    if scenario == "new_activity":
        assert len(calls) == 2
        assert result["status"] == "completed"
        assert "continuation_paused" not in result
    elif scenario == "finite":
        assert len(calls) == 3  # Initial slice plus exactly the finite continuation allowance.
        assert len(lease_checks) == 2
        assert result["status"] == "continuing"
    else:
        assert len(calls) == 1
        assert result["continuation_paused"] is True
        assert result["reason"] == (
            "exclusive_maintenance_run_active" if scenario == "exclusive"
            else "background_worker_lease_lost"
        )


def test_new_activity_still_cancels_idle_request_before_dispatch(tmp_path, monkeypatch, capsys):
    import json
    import harness_mem.hook_background as background
    import harness_mem.host_entry.__main__ as host_entry
    import harness_mem.storage.local_memory_backend as backend_module

    request = background.BackgroundRequest(
        generation="idle-generation", project_root=str(tmp_path), client="codex",
        source="ide_hook", trigger_id="idle-session", requested_at=100.0,
    )
    background.record_background_activity(
        tmp_path, project_root=tmp_path, client="codex", session_id="idle-session", now=101.0,
    )
    retired = []
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setattr(backend_module, "DEFAULT_DATA_DIR", tmp_path)
    monkeypatch.setattr(background, "wait_for_background_request", lambda *_args, **_kwargs: request)
    monkeypatch.setattr(background, "finish_background_worker",
                        lambda *_args, **kwargs: retired.append(kwargs["processed_generation"]))
    monkeypatch.setattr(host_entry, "_run_request", lambda *_args: pytest.fail(
        "cancelled idle request must not stage sources or dispatch any work"))
    code = host_entry.main([
        "--action", "post-turn-maintenance", "--source", "ide_hook",
        "--project-root", str(tmp_path), "--client", "codex",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "new_user_input"
    assert retired == ["idle-generation"]
