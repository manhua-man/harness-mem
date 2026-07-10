from __future__ import annotations

import subprocess
from pathlib import Path

from harness_mem.hook_runtime import collect_hook_runtime_report, probe_python_runtime


def test_probe_python_runtime_reports_import_success() -> None:
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                '{"executable": "C:/Python/python.exe", '
                '"python_version": "3.13.1", '
                '"harness_mem_version": "0.8.21"}\n'
            ),
            stderr="",
        )

    probe = probe_python_runtime(runner=runner)

    assert probe.ok is True
    assert probe.executable == "C:/Python/python.exe"
    assert probe.python_version == "3.13.1"
    assert probe.harness_mem_version == "0.8.21"


def test_probe_python_runtime_reports_import_failure_tail() -> None:
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "  File \"<string>\", line 1, in <module>\n"
                "ModuleNotFoundError: No module named 'harness_mem'\n"
            ),
        )

    probe = probe_python_runtime(runner=runner)

    assert probe.ok is False
    assert probe.error == (
        "Traceback (most recent call last):\n"
        "  File \"<string>\", line 1, in <module>\n"
        "ModuleNotFoundError: No module named 'harness_mem'"
    )


def test_collect_hook_runtime_report_detects_project_and_global_hooks(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    cursor_hook = project_root / ".cursor" / "hooks" / "session-start.sh"
    cursor_hook.parent.mkdir(parents=True)
    cursor_hook.write_text(
        f"python -m harness_mem.host_entry --project-root {project_root.as_posix()}",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    hermes_hook = home / ".hermes" / "agent-hooks" / "harness_mem_pre_llm_call.py"
    hermes_hook.parent.mkdir(parents=True)
    hermes_hook.write_text(
        f'"harness_mem.host_entry", "--project-root", "{project_root.as_posix()}"',
        encoding="utf-8",
    )

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                '{"executable": "python", '
                '"python_version": "3.13.1", '
                '"harness_mem_version": "0.8.21"}\n'
            ),
            stderr="",
        )

    report = collect_hook_runtime_report(project_root, runner=runner, home_dir=home)
    installed = {(hook.client, hook.label): hook for hook in report.hooks if hook.exists}

    assert report.python_probe.ok is True
    assert installed[("cursor", "session-start")].contains_host_entry is True
    assert installed[("cursor", "session-start")].project_root_match is True
    assert installed[("hermes", "pre_llm_call script")].scope == "global"
    assert installed[("hermes", "pre_llm_call script")].project_root_match is True
