from __future__ import annotations

import asyncio
from pathlib import Path

import harness_mem.commands.onboarding as onboarding
import harness_mem.commands.support as support
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


def test_quickstart_defaults_to_workspace_before_active_project(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(onboarding, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(onboarding, "get_active_project", lambda: "wrong-project")

    result = asyncio.run(onboarding.cmd_quickstart(project_name=None, client="auto", limit=1))

    assert result == 0
    assert "Quickstart for project: servers" in capsys.readouterr().out

    store = LocalProjectProfileStore(data_dir)
    saved = asyncio.run(store.get("servers"))
    assert saved is not None
    assert saved.project_root == str(workspace.resolve())
