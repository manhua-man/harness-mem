from __future__ import annotations

from pathlib import Path

from harness_mem.commands.doctor import _doctor_hook_runtime_block
from harness_mem.hook_runtime import (
    HookFileStatus,
    HookRuntimeReport,
    PythonRuntimeProbe,
)


def test_doctor_hook_runtime_block_renders_success(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path / "project"
    hook_path = project_root / ".cursor" / "hooks" / "session-start.sh"
    report = HookRuntimeReport(
        project_root=project_root,
        python_probe=PythonRuntimeProbe(
            command=("python",),
            ok=True,
            executable="C:/Python/python.exe",
            python_version="3.13.1",
            harness_mem_version="0.8.21",
        ),
        hooks=(
            HookFileStatus(
                client="cursor",
                label="session-start",
                path=hook_path,
                exists=True,
                contains_host_entry=True,
                project_root_match=True,
            ),
        ),
    )

    _doctor_hook_runtime_block(report)

    out = capsys.readouterr().out
    assert "Hook runtime:" in out
    assert "current shell python (python): ok" in out
    assert "harness-mem=0.8.21" in out
    assert "cursor session-start: host_entry, project-root match" in out
    assert "HARNESS_MEM_HOOK_DEBUG=1" in out


def test_doctor_hook_runtime_block_renders_probe_failure(
    tmp_path: Path,
    capsys,
) -> None:
    report = HookRuntimeReport(
        project_root=tmp_path,
        python_probe=PythonRuntimeProbe(
            command=("python",),
            ok=False,
            error="Traceback\nModuleNotFoundError: No module named 'harness_mem'",
        ),
        hooks=(),
    )

    _doctor_hook_runtime_block(report)

    out = capsys.readouterr().out
    assert "current shell python (python): unavailable" in out
    assert "No module named 'harness_mem'" in out
    assert "install harness-mem into the Python visible to generated hooks" in out
    assert "hook files: none installed" in out
