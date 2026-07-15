from __future__ import annotations

from pathlib import Path

from harness_mem.commands.doctor import _doctor_hook_runtime_block
from harness_mem.hook_runtime import HookFileStatus, HookRunnerProbe, HookRuntimeReport


def test_doctor_hook_runtime_block_renders_ready_runner(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "project"
    runner = tmp_path / "harness-mem-hook"
    hook_path = project_root / ".cursor" / "hooks" / "session-start.sh"
    report = HookRuntimeReport(
        project_root=project_root,
        runner_probe=HookRunnerProbe(path=runner, ok=True, version="0.8.24"),
        hooks=(
            HookFileStatus(
                client="cursor",
                label="session-start",
                path=hook_path,
                exists=True,
                runner_bound=True,
                legacy_python=False,
                project_root_match=True,
            ),
        ),
    )

    _doctor_hook_runtime_block(report)
    out = capsys.readouterr().out
    assert "Hook runtime: ready" in out
    assert f"runner: {runner} (0.8.24)" in out
    assert "cursor session-start: runner bound, project-root match" in out


def test_doctor_hook_runtime_block_renders_legacy_runner(tmp_path: Path, capsys) -> None:
    report = HookRuntimeReport(
        project_root=tmp_path,
        runner_probe=HookRunnerProbe(path=tmp_path / "harness-mem-hook", ok=True, version="0.8.24"),
        hooks=(
            HookFileStatus(
                client="cursor",
                label="session-start",
                path=tmp_path / ".cursor" / "hooks" / "session-start.sh",
                exists=True,
                runner_bound=False,
                legacy_python=True,
                project_root_match=True,
            ),
        ),
    )

    _doctor_hook_runtime_block(report)
    out = capsys.readouterr().out
    assert "Hook runtime: repair needed" in out
    assert "legacy python" in out
    assert "reinstall the Hook suite" in out


def test_doctor_hook_runtime_block_renders_runner_failure(tmp_path: Path, capsys) -> None:
    report = HookRuntimeReport(
        project_root=tmp_path,
        runner_probe=HookRunnerProbe(path=None, ok=False, error="harness-mem-hook executable was not found"),
        hooks=(),
    )

    _doctor_hook_runtime_block(report)
    out = capsys.readouterr().out
    assert "Hook runtime: unavailable" in out
    assert "runner: unavailable" in out
    assert "harness-mem-hook executable was not found" in out
