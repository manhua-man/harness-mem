from __future__ import annotations

from pathlib import Path

from harness_mem.hook_background import (
    dispatch_post_turn,
    finish_background_worker,
    load_background_request,
)


def test_post_turn_dispatch_coalesces_while_worker_is_active(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict]] = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    first = dispatch_post_turn(
        tmp_path / "data",
        project_root=tmp_path,
        client="codex",
        source="ide_hook",
        trigger_id="turn-1",
        popen=popen,
        now=100.0,
    )
    second = dispatch_post_turn(
        tmp_path / "data",
        project_root=tmp_path,
        client="codex",
        source="ide_hook",
        trigger_id="turn-2",
        popen=popen,
        now=101.0,
    )

    assert first.spawned is True
    assert first.coalesced is False
    assert second.spawned is False
    assert second.coalesced is True
    assert len(calls) == 1
    latest = load_background_request(
        tmp_path / "data",
        project_root=tmp_path,
        client="codex",
    )
    assert latest is not None
    assert latest.trigger_id == "turn-2"


def test_finished_worker_hands_off_request_that_arrived_during_sync(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict]] = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    first = dispatch_post_turn(
        tmp_path / "data",
        project_root=tmp_path,
        client="cursor",
        source="ide_hook",
        trigger_id="turn-1",
        popen=popen,
        now=100.0,
    )
    second = dispatch_post_turn(
        tmp_path / "data",
        project_root=tmp_path,
        client="cursor",
        source="ide_hook",
        trigger_id="turn-2",
        popen=popen,
        now=101.0,
    )

    handed_off = finish_background_worker(
        tmp_path / "data",
        project_root=tmp_path,
        client="cursor",
        processed_generation=first.generation,
        popen=popen,
    )

    assert second.coalesced is True
    assert handed_off is True
    assert len(calls) == 2
    assert "turn-2" in calls[1][0]
    assert calls[1][1]["stdout"] is not None
    assert calls[1][1]["stderr"] is not None


def test_finished_worker_does_not_spawn_when_request_is_current(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict]] = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    dispatch = dispatch_post_turn(
        tmp_path / "data",
        project_root=tmp_path,
        client="opencode",
        source="ide_hook",
        trigger_id="session-idle",
        popen=popen,
        now=100.0,
    )

    assert (
        finish_background_worker(
            tmp_path / "data",
            project_root=tmp_path,
            client="opencode",
            processed_generation=dispatch.generation,
            popen=popen,
        )
        is False
    )
    assert len(calls) == 1
