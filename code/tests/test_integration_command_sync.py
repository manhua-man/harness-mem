from __future__ import annotations

import sys
from pathlib import Path

import pytest

from harness_mem.commands.integration_cmds import cmd_sync_commands
from harness_mem.integration.command_sync import (
    COMMAND_HOSTS,
    command_hint,
    default_host_commands_dir,
    sync_host_commands,
)
from harness_mem.plugin_assets import REMOVED_COMMANDS
from tests.support.host_contracts import HOST_COMMAND_HINT_CASES, HOST_NAMES


def _write_source(source_dir: Path, text: str = "# HM\n") -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "hm.md").write_text(text, encoding="utf-8")


def _primary_path(destination: Path, client: str) -> Path:
    if client in {"codex", "cursor", "grok", "hermes"}:
        return destination / "hm" / "SKILL.md"
    return destination / "hm.md"


def _old_path(destination: Path, client: str, command: str) -> Path:
    if client == "claude-code":
        return destination / "hm" / f"{command}.md"
    if client in {"codex", "cursor", "grok", "hermes"}:
        return destination / f"hm-{command}" / "SKILL.md"
    return destination / f"hm-{command}.md"


@pytest.mark.parametrize(("client", "expected"), HOST_COMMAND_HINT_CASES)
def test_command_hint_uses_exact_host_native_syntax(client: str, expected: str) -> None:
    assert command_hint(client) == expected


def test_command_host_matrix_matches_public_contract() -> None:
    assert len(COMMAND_HOSTS) == len(HOST_NAMES)
    assert set(COMMAND_HOSTS) == set(HOST_NAMES)


def test_all_hosts_install_only_one_global_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    _write_source(source_dir)
    home = tmp_path / "home"
    local_appdata = tmp_path / "local-appdata"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    for client in COMMAND_HOSTS:
        result = sync_host_commands(client=client, source_dir=source_dir)
        assert result.destination_dir == default_host_commands_dir(client)
        assert _primary_path(result.destination_dir, client).is_file()
        assert not any(
            _old_path(result.destination_dir, client, command).exists()
            for command in REMOVED_COMMANDS
        )

    expected_hermes = (
        local_appdata / "hermes" / "skills"
        if sys.platform == "win32"
        else home / ".hermes" / "skills"
    )
    assert default_host_commands_dir("hermes") == expected_hermes


@pytest.mark.parametrize("client", COMMAND_HOSTS)
def test_sync_removes_exact_old_entries_but_preserves_unrelated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
) -> None:
    source_dir = tmp_path / "source"
    _write_source(source_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    destination = default_host_commands_dir(client)
    old = _old_path(destination, client, "wake")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("old", encoding="utf-8")
    unrelated = old.parent / "keep.txt"
    unrelated.write_text("user owned", encoding="utf-8")

    result = sync_host_commands(client=client, source_dir=source_dir)

    assert "wake" in result.removed_commands
    assert not old.exists()
    assert unrelated.read_text(encoding="utf-8") == "user owned"
    assert _primary_path(destination, client).exists()


def test_sync_dry_run_reports_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    _write_source(source_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    destination = default_host_commands_dir("codex")
    old = _old_path(destination, "codex", "status")
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")

    result = sync_host_commands(
        client="codex", source_dir=source_dir, dry_run=True
    )

    assert result.dry_run is True
    assert result.removed_commands == ("status",)
    assert old.exists()
    assert not _primary_path(destination, "codex").exists()


def test_sync_reports_install_update_and_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    _write_source(source_dir, "# first\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    installed = sync_host_commands(client="opencode", source_dir=source_dir)
    unchanged = sync_host_commands(client="opencode", source_dir=source_dir)
    _write_source(source_dir, "# second\n")
    updated = sync_host_commands(client="opencode", source_dir=source_dir)

    assert installed.status == "installed"
    assert unchanged.status == "unchanged"
    assert updated.status == "updated"


def test_cli_syncs_all_hosts_at_user_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_dir = tmp_path / "source"
    _write_source(source_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))

    exit_code = cmd_sync_commands(
        client="all", dry_run=False, source_dir=str(source_dir)
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.count("Use:") == len(COMMAND_HOSTS)
    assert "Use: $hm" in output
    assert "Use: /hm" in output
