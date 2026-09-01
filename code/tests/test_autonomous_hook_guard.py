from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.autonomous import hook_guard as hook_guard_module
from harness_mem.autonomous.hook_guard import (
    autonomous_provider_hook_reentry_blocked,
    challenge_hook_reentry_guard,
    count_hook_reentry_blocks,
    record_hook_reentry_block,
)


def test_posix_process_stat_falls_back_to_ps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hook_guard_module,
        "_linux_process_stat",
        lambda _pid: (None, None),
    )
    monkeypatch.setattr(
        hook_guard_module.subprocess,
        "run",
        lambda *_args, **_kwargs: hook_guard_module.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="42 Mon Sep  1 12:34:56 2026\n",
        ),
    )

    assert hook_guard_module._posix_process_stat(99) == (
        42,
        "Mon Sep  1 12:34:56 2026",
    )


def test_record_and_count_hook_reentry_blocks(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_dir = tmp_path / "data"
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="post-turn-maintenance",
        trigger_id="session-1",
    )
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="dream-end",
        trigger_id="session-2",
    )
    assert (
        count_hook_reentry_blocks(
            data_dir,
            project_name="demo",
            project_root=project_root,
        )
        == 2
    )
    assert (
        count_hook_reentry_blocks(
            data_dir,
            project_name="demo",
            project_root=project_root,
            trigger_id="session-1",
        )
        == 1
    )


def test_autonomous_provider_context_blocks_wake_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_AUTONOMOUS_PROVIDER", "1")
    assert autonomous_provider_hook_reentry_blocked("wake-start") is True


def test_hook_reentry_ledger_is_json_lines(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_dir = tmp_path / "data"
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="post-turn-maintenance",
        trigger_id="session-1",
    )
    ledger = next((data_dir / "autonomous" / "hook_reentry").glob("*.jsonl"))
    payload = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert payload["action"] == "post-turn-maintenance"
    assert payload["trigger_id"] == "session-1"


def test_hook_guard_challenge_blocks_all_actions_without_env_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "generation-1")
    original_run = hook_guard_module.subprocess.run
    challenge_envs: list[dict[str, str]] = []

    def recording_run(*args, **kwargs):
        challenge_envs.append(kwargs["env"])
        return original_run(*args, **kwargs)

    monkeypatch.setattr(hook_guard_module.subprocess, "run", recording_run)
    result = challenge_hook_reentry_guard(
        tmp_path / "data",
        project_name="project",
        project_root=project_root,
        client="codex",
    )

    assert result["actions"] == {
        "dream-end": True,
        "post-turn-maintenance": True,
        "wake-start": True,
    }
    assert result["all_blocked"] is True
    assert result["downstream_jobs_created"] == 0
    assert all("HARNESS_MEM_AUTONOMOUS_PROVIDER" not in env for env in challenge_envs)
    assert all("HARNESS_MEM_HOOK_BACKGROUND_WORKER" not in env for env in challenge_envs)
    assert all(
        "HARNESS_MEM_HOOK_BACKGROUND_GENERATION" not in env for env in challenge_envs
    )
