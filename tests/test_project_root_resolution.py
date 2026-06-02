from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.support import find_project_root


def test_find_project_root_prefers_named_child_before_bare_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project_root = workspace / "demo"
    project_root.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    assert find_project_root("demo") == project_root


def test_find_project_root_keeps_cwd_when_it_is_the_named_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "demo"
    project_root.mkdir()
    monkeypatch.chdir(project_root)

    assert find_project_root("demo") == project_root
