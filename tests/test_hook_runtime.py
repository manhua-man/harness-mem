from __future__ import annotations

import subprocess
from pathlib import Path

import harness_mem.integration.hook_runner as hook_runner_module
from harness_mem.hook_runtime import collect_hook_runtime_report
from harness_mem.integration.hook_runner import probe_hook_runner, resolve_hook_runner


def test_resolve_hook_runner_prefers_the_active_environment_scripts_dir(monkeypatch, tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    expected = scripts_dir / "harness-mem-hook"
    expected.write_text("runner", encoding="utf-8")
    monkeypatch.setattr(hook_runner_module.sysconfig, "get_path", lambda _name: str(scripts_dir))
    monkeypatch.setattr(hook_runner_module.shutil, "which", lambda _name: None)

    assert resolve_hook_runner() == expected.resolve()


def test_probe_hook_runner_reports_version(tmp_path: Path) -> None:
    runner_path = tmp_path / "harness-mem-hook"
    runner_path.write_text("runner", encoding="utf-8")

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="harness-mem-hook 0.8.24\n", stderr="")

    probe = probe_hook_runner(hook_runner=runner_path, runner=runner)
    assert probe.ok is True
    assert probe.path == runner_path.resolve()
    assert probe.version == "0.8.24"


def test_probe_hook_runner_reports_bad_version_output(tmp_path: Path) -> None:
    runner_path = tmp_path / "harness-mem-hook"
    runner_path.write_text("runner", encoding="utf-8")

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="unexpected\n", stderr="")

    probe = probe_hook_runner(hook_runner=runner_path, runner=runner)
    assert probe.ok is False
    assert "unexpected --version output" in (probe.error or "")


def test_collect_hook_runtime_report_detects_bound_and_legacy_hooks(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    runner_path = tmp_path / "harness-mem-hook"
    runner_path.write_text("runner", encoding="utf-8")
    cursor_hook = project_root / ".cursor" / "hooks" / "session-start.sh"
    cursor_hook.parent.mkdir(parents=True)
    cursor_hook.write_text(
        f"{runner_path.resolve().as_posix()} --action wake-start --project-root {project_root.as_posix()}",
        encoding="utf-8",
    )
    claude_hook = project_root / ".claude" / "hooks" / "after-turn.sh"
    claude_hook.parent.mkdir(parents=True)
    claude_hook.write_text(
        f"python -m harness_mem.host_entry --project-root {project_root.as_posix()}",
        encoding="utf-8",
    )

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="harness-mem-hook 0.8.24\n", stderr="")

    report = collect_hook_runtime_report(
        project_root,
        hook_runner=runner_path,
        runner=runner,
    )
    installed = {(hook.client, hook.label): hook for hook in report.hooks if hook.exists}
    assert report.runner_probe.ok is True
    assert installed[("cursor", "session-start")].runner_bound is True
    assert installed[("cursor", "session-start")].legacy_python is False
    assert installed[("claude-code", "after-turn")].legacy_python is True
