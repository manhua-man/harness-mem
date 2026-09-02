from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

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
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(onboarding, "get_active_project", lambda: "wrong-project")
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: "codex")
    repaired: list[tuple[tuple[str, ...], Path]] = []

    def repair_integrations(*, clients, project_root, **_kwargs):
        repaired.append((clients, project_root))
        return SimpleNamespace(success=True)

    monkeypatch.setattr(onboarding, "repair_integrations", repair_integrations)
    monkeypatch.setattr(
        onboarding,
        "cmd_ingest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("quickstart must not import old sessions by default")
        ),
    )

    result = asyncio.run(onboarding.cmd_quickstart(project_name=None, client="auto"))

    assert result == 0
    output = capsys.readouterr().out
    assert "Installed $hm and project Hooks for servers" in output
    assert "use $hm" in output
    assert "MCP" not in output
    assert "Phase:" not in output
    assert "doctor" not in output
    assert repaired == [(('codex',), workspace.resolve())]

    store = LocalProjectProfileStore(data_dir)
    saved = asyncio.run(store.get("servers"))
    assert saved is not None
    assert saved.project_root == str(workspace.resolve())


def test_quickstart_imports_history_only_when_limit_is_explicit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: "codex")
    monkeypatch.setattr(
        onboarding,
        "repair_integrations",
        lambda **_kwargs: SimpleNamespace(success=True),
    )
    calls: list[tuple[str, str, int, str]] = []

    async def ingest(client, project_name, limit, *, project_root):
        calls.append((client, project_name, limit, project_root))
        return 0

    monkeypatch.setattr(onboarding, "cmd_ingest", ingest)

    result = asyncio.run(
        onboarding.cmd_quickstart(project_name="project", client="codex", limit=2)
    )

    assert result == 0
    assert calls == [("codex", "project", 2, str(workspace.resolve()))]


def test_quickstart_skip_connects_project_without_host_or_history_work(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(
        onboarding,
        "repair_integrations",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("skip must not install host integration")
        ),
    )
    monkeypatch.setattr(
        onboarding,
        "cmd_ingest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("skip must not import history")
        ),
    )

    result = asyncio.run(
        onboarding.cmd_quickstart(project_name="project", client="skip")
    )

    assert result == 0
    assert capsys.readouterr().out.strip() == (
        "Project connected: project. Host integration was skipped."
    )
    saved = asyncio.run(LocalProjectProfileStore(tmp_path / "data").get("project"))
    assert saved is not None


def test_quickstart_keeps_mcp_configuration_out_of_host_setup(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(
        onboarding,
        "repair_integrations",
        lambda **_kwargs: SimpleNamespace(success=True),
    )

    result = asyncio.run(
        onboarding.cmd_quickstart(project_name="project", client="cursor")
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Installed /hm and project Hooks for project" in output
    assert "use /hm" in output
    assert "MCP" not in output
    assert "harness-mem-mcp" not in output


def test_quickstart_auto_stops_when_current_app_is_unknown(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: None)
    monkeypatch.setattr(
        onboarding,
        "repair_integrations",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown auto client must not install another app's files")
        ),
    )

    result = asyncio.run(
        onboarding.cmd_quickstart(project_name="project", client="auto")
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "Could not detect the current app" in output
    assert "harness-mem quickstart --client cursor" in output


def test_quickstart_does_not_claim_installation_when_hooks_are_not_ready(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(onboarding, "can_prompt", lambda: False)
    monkeypatch.setattr(
        onboarding,
        "repair_integrations",
        lambda **_kwargs: SimpleNamespace(success=False),
    )

    result = asyncio.run(
        onboarding.cmd_quickstart(project_name="project", client="cursor")
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "Could not finish setup" in output
    assert "Installed /hm and project Hooks" not in output
