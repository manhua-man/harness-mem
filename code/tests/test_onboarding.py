from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import harness_mem.commands.onboarding as onboarding


def test_quickstart_installs_user_hooks_without_touching_project(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: "codex")
    hook_calls = []
    monkeypatch.setattr(
        onboarding, "repair_project_hooks",
        lambda **kwargs: hook_calls.append(kwargs) or SimpleNamespace(success=True),
    )

    result = onboarding.cmd_quickstart(client="auto")

    assert result == 0
    assert hook_calls == [{"clients": ("codex",), "scope": "user", "project_root": workspace}]
    assert list(workspace.iterdir()) == []
    output = capsys.readouterr().out
    assert "Installed user-level lifecycle Hooks for codex" in output
    assert "then start a new task" in output
    assert "Background authorization is unchanged" in output
    assert "harness-mem-mcp" in output
    assert "Codex Settings > Hooks" in output


def test_quickstart_uses_explicit_host_without_inspecting_workspace(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    install_calls = []
    monkeypatch.setattr(
        onboarding, "repair_project_hooks",
        lambda **kwargs: install_calls.append(kwargs) or SimpleNamespace(success=True),
    )

    monkeypatch.chdir(first)
    assert onboarding.cmd_quickstart(client="cursor") == 0
    monkeypatch.chdir(second)
    assert onboarding.cmd_quickstart(client="cursor") == 0

    assert [call["scope"] for call in install_calls] == ["user", "user"]
    assert list(first.iterdir()) == []
    assert list(second.iterdir()) == []
    output = capsys.readouterr().out
    assert output.count("Installed user-level lifecycle Hooks for cursor.") == 2



def test_quickstart_auto_stops_when_current_app_is_unknown(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: None)
    monkeypatch.setattr(
        onboarding,
        "repair_project_hooks",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown host must not install another app's files")
        ),
    )

    assert onboarding.cmd_quickstart(client="auto") == 1
    output = capsys.readouterr().out
    assert "Could not detect the current app" in output
    assert "harness-mem quickstart --client cursor" in output
    assert "Installed" not in output
    assert "harness-mem-mcp" not in output


def test_quickstart_does_not_claim_success_when_hook_install_fails(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        onboarding,
        "repair_project_hooks",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("permission denied")),
    )

    assert onboarding.cmd_quickstart(client="cursor") == 1
    output = capsys.readouterr().out
    assert "Could not prepare automatic memory" in output
    assert "permission denied" in output
    assert "Installed" not in output
    assert "harness-mem-mcp" not in output


@pytest.mark.parametrize("client", ("codex", "cursor"))
def test_quickstart_handoff_preserves_existing_mcp_project_and_memory(
    monkeypatch,
    tmp_path: Path,
    client: str,
    capsys,
) -> None:
    from harness_mem.integration import installer

    home = tmp_path / "home"
    workspace = tmp_path / "project"
    preserved = {
        home / ".codex/config.toml": '[mcp_servers.existing]\ncommand = "router"\n',
        home / ".cursor/mcp.json": '{"mcpServers": {"existing": {"command": "router"}}}',
        home / ".harness-mem/data/canonical.sqlite": "memory fixture",
        workspace / ".harness-mem.toml": 'project_name = "fixture"\n',
        workspace / ".mcp.json": '{"mcpServers": {}}',
        workspace / ".codex/hooks.json": '{"hooks": {}}',
    }
    for path, content in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    before = {path: path.read_bytes() for path in preserved}
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData/Local"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    runner = tmp_path / "harness-mem-hook.exe"
    runner.write_text("fixture runner", encoding="utf-8")
    monkeypatch.setattr(installer, "verified_hook_runner", lambda: runner)
    assert onboarding.cmd_quickstart(client=client) == 0

    hook = installer.user_hook_path(client, home_dir=home)
    assert f"{client}-start" in hook.read_text(encoding="utf-8")
    assert all(path.read_bytes() == content for path, content in before.items())
    assert {path for path in tmp_path.rglob("*") if path.is_file()} == {
        *preserved,
        hook,
        runner,
    }
    output = capsys.readouterr().out
    assert f"Installed user-level lifecycle Hooks for {client}." in output
    assert "harness-mem-mcp" in output
