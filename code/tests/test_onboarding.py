from __future__ import annotations

import re
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

import harness_mem.commands.onboarding as onboarding


def test_quickstart_installs_one_global_entry_without_touching_project(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: "codex")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(status="installed"),
    )

    result = onboarding.cmd_quickstart(client="auto")

    assert result == 0
    assert calls == [{"client": "codex"}]
    assert list(workspace.iterdir()) == []
    output = capsys.readouterr().out
    assert "Installed $hm for codex" in output
    assert "Start a new Agent task" in output
    assert "If harness-mem tools are already available, use $hm." in output
    assert "Otherwise, ask the Agent, MCP Router, plugin, or existing setup tool" in output
    assert "that manages your MCP connection to connect harness-mem" in output
    assert "See docs/mcp-setup.md." in output
    assert "Quickstart does not inspect or change MCP connections." in output
    assert "project" not in output.lower()
    assert "Hooks" not in output


def test_quickstart_uses_explicit_host_without_inspecting_workspace(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda *, client: calls.append(client) or SimpleNamespace(status="installed"),
    )

    monkeypatch.chdir(first)
    assert onboarding.cmd_quickstart(client="cursor") == 0
    monkeypatch.chdir(second)
    assert onboarding.cmd_quickstart(client="cursor") == 0

    assert calls == ["cursor", "cursor"]
    assert list(first.iterdir()) == []
    assert list(second.iterdir()) == []
    output = capsys.readouterr().out
    assert output.count("Installed /hm for cursor.") == 2
    assert output.count("If harness-mem tools are already available, use /hm.") == 2
    assert output.count("See docs/mcp-setup.md.") == 2


def test_quickstart_auto_stops_when_current_app_is_unknown(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(onboarding, "detect_runtime_client", lambda: None)
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown host must not install another app's files")
        ),
    )

    assert onboarding.cmd_quickstart(client="auto") == 1
    output = capsys.readouterr().out
    assert "Could not detect the current app" in output
    assert "harness-mem quickstart --client cursor" in output
    assert "Installed" not in output
    assert "docs/mcp-setup.md" not in output


def test_quickstart_does_not_claim_success_when_entry_install_fails(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("permission denied")),
    )

    assert onboarding.cmd_quickstart(client="cursor") == 1
    output = capsys.readouterr().out
    assert "Could not install the memory entry" in output
    assert "Installed /hm" not in output
    assert "docs/mcp-setup.md" not in output


@pytest.mark.parametrize("client", ("codex", "cursor"))
def test_quickstart_handoff_preserves_existing_mcp_project_and_memory(
    monkeypatch,
    tmp_path: Path,
    client: str,
    capsys,
) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "project"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "hm.md").write_text("# HM fixture\n", encoding="utf-8")
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
    sync = onboarding.sync_host_commands
    monkeypatch.setattr(
        onboarding,
        "sync_host_commands",
        lambda *, client: sync(client=client, source_dir=source_dir),
    )

    assert onboarding.cmd_quickstart(client=client) == 0

    entry = home / f".{client}/skills/hm/SKILL.md"
    assert "# HM fixture" in entry.read_text(encoding="utf-8")
    assert all(path.read_bytes() == content for path, content in before.items())
    assert {path for path in tmp_path.rglob("*") if path.is_file()} == {
        *preserved,
        source_dir / "hm.md",
        entry,
    }
    output = capsys.readouterr().out
    assert f"Installed {onboarding.command_hint(client)} for {client}." in output
    assert "docs/mcp-setup.md" in output


@pytest.mark.parametrize(
    ("relative", "expected_count"),
    (("README.md", 1), ("README.zh-CN.md", 1), ("docs/quickstart.md", 2)),
)
def test_install_examples_are_single_line_cross_shell_commands(
    relative: str,
    expected_count: int,
) -> None:
    root = Path(__file__).resolve().parents[2]
    body = (root / relative).read_text(encoding="utf-8")
    commands = re.findall(r"```[^\n]*\n(python -m pip install.*?)\n```", body, re.S)
    assert len(commands) == expected_count
    for command in commands:
        assert len(command.splitlines()) == 1
        tokens = shlex.split(command)
        assert len(tokens) == 7
        assert tokens[:5] == ["python", "-m", "pip", "install", "--find-links"]
        release = re.fullmatch(
            r"https://github\.com/manhua-man/harness-mem/releases/expanded_assets/v(\d+\.\d+\.\d+)",
            tokens[5],
        )
        assert release is not None
        package = "harness-mem[hybrid]" if "[hybrid]" in tokens[6] else "harness-mem"
        assert tokens[6] == f"{package}=={release.group(1)}"
        if package == "harness-mem[hybrid]":
            assert command.endswith(f'"{tokens[6]}"')
