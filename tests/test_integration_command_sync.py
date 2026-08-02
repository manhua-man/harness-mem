from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.support.host_contracts import HOST_COMMAND_HINT_CASES, HOST_NAMES

from harness_mem.commands.integration_cmds import cmd_sync_commands
from harness_mem.integration.command_sync import (
    COMMAND_HOSTS,
    command_hint,
    default_host_commands_dir,
    known_command_names,
    resolve_command_names,
    source_path_for_command,
    sync_host_commands,
    sync_slash_commands,
)


def _write_command_sources(source_dir: Path) -> None:
    groups = {
        "daily": (
            "status",
            "wake",
            "search",
            "search-all",
            "distill",
            "review",
            "dream",
        ),
    }
    for command in known_command_names():
        for group, commands in groups.items():
            if command in commands:
                command_dir = source_dir / group
                command_dir.mkdir(parents=True, exist_ok=True)
                break
        else:
            raise AssertionError(f"missing group for command {command}")
        (command_dir / f"{command}.md").write_text(
            f"# /hm:{command}\n",
            encoding="utf-8",
        )


def test_command_sync_is_daily_only() -> None:
    assert resolve_command_names(profile="daily") == (
        "status",
        "wake",
        "search",
        "search-all",
        "distill",
        "review",
        "dream",
    )
    assert "mark" not in resolve_command_names(profile="daily")
    assert "prune" not in resolve_command_names(profile="daily")
    assert "metabolism" not in resolve_command_names(profile="daily")
    assert "metabolism" not in known_command_names()
    with pytest.raises(ValueError, match="optional slash command groups were removed"):
        resolve_command_names(profile="daily", include=("maintenance",))
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="maintenance")
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="full")
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="labs")
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="product-doc")


def test_source_path_for_command_uses_profile_subdirectories(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)

    assert (
        source_path_for_command(source_dir, "status")
        == source_dir / "daily" / "status.md"
    )
    assert (
        source_path_for_command(source_dir, "dream")
        == source_dir / "daily" / "dream.md"
    )
    with pytest.raises(ValueError, match="unknown slash command"):
        source_path_for_command(source_dir, "mark")


def test_sync_slash_commands_removes_commands_outside_selected_profile(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "mark.md").write_text(
        "# optional maintenance command\n", encoding="utf-8"
    )
    (target_dir / "prune.md").write_text(
        "# optional maintenance command\n", encoding="utf-8"
    )

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
    )

    assert "mark" in result.removed_commands
    assert "prune" in result.removed_commands
    assert not (target_dir / "mark.md").exists()
    assert not (target_dir / "prune.md").exists()
    assert (target_dir / "status.md").read_text(encoding="utf-8") == "# /hm:status\n"
    assert not (target_dir / "daily").exists()


def test_sync_slash_commands_dry_run_does_not_mutate_target(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "mark.md").write_text(
        "# optional maintenance command\n", encoding="utf-8"
    )

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
        dry_run=True,
    )

    assert result.dry_run is True
    assert "mark" in result.removed_commands
    assert (target_dir / "mark.md").exists()
    assert not (target_dir / "status.md").exists()


def test_command_sync_reports_install_update_and_unchanged(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)

    installed = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
    )
    unchanged = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
    )
    (source_dir / "daily" / "wake.md").write_text(
        "# updated /hm:wake\n", encoding="utf-8"
    )
    updated = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
    )

    assert installed.status == "installed"
    assert unchanged.status == "unchanged"
    assert updated.status == "updated"


def test_project_command_surfaces_use_native_paths_and_invocation_styles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    expected = {
        "claude-code": project / ".claude" / "commands" / "hm" / "status.md",
        "cursor": project / ".cursor" / "commands" / "hm-status.md",
        "grok": project / ".grok" / "skills" / "hm-status" / "SKILL.md",
        "opencode": project / ".opencode" / "commands" / "hm-status.md",
        "codex": project / ".agents" / "skills" / "hm-status" / "SKILL.md",
        "antigravity": project / ".agents" / "workflows" / "hm-status.md",
    }
    for client in (item for item in COMMAND_HOSTS if item != "hermes"):
        result = sync_host_commands(
            client=client,
            project_root=project,
            scope="project",
            source_dir=source_dir,
        )
        assert result.destination_dir == default_host_commands_dir(
            client, project, scope="project"
        )
        assert expected[client].exists()
        if client in {"codex", "grok"}:
            assert "name: hm-status" in expected[client].read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Hermes commands are user/profile-scoped"):
        sync_host_commands(
            client="hermes",
            project_root=project,
            scope="project",
            source_dir=source_dir,
        )


@pytest.mark.parametrize(
    ("client", "expected"),
    HOST_COMMAND_HINT_CASES,
)
def test_command_hint_uses_exact_host_native_syntax(client: str, expected: str) -> None:
    assert command_hint(client) == expected


def test_command_host_matrix_matches_public_contract() -> None:
    assert len(COMMAND_HOSTS) == len(HOST_NAMES)
    assert set(COMMAND_HOSTS) == set(HOST_NAMES)


def test_codex_distill_skill_preserves_router_and_direct_alias_resolution(
    tmp_path: Path,
) -> None:
    source_dir = Path("plugins/harness-mem/commands/hm")
    project = tmp_path / "project"

    sync_host_commands(
        client="codex",
        project_root=project,
        scope="project",
        source_dir=source_dir,
    )

    rendered = (project / ".agents" / "skills" / "hm-distill" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "mcp__mcp_router__prepare_session_distill" in rendered
    assert "mcp__harness_mem__prepare_session_distill" in rendered
    assert "不能因为 `harness_mem` / `harness-mem` server 名查询" in rendered


def test_user_command_sync_is_visible_from_unrelated_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    home = tmp_path / "home"
    local_appdata = tmp_path / "local-appdata"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    expected = {
        "claude-code": home / ".claude" / "commands" / "hm" / "status.md",
        "cursor": home / ".cursor" / "skills" / "hm-status" / "SKILL.md",
        "grok": home / ".grok" / "skills" / "hm-status" / "SKILL.md",
        "codex": home / ".codex" / "skills" / "hm-status" / "SKILL.md",
        "hermes": (
            local_appdata / "hermes" / "skills" / "hm-status" / "SKILL.md"
            if sys.platform == "win32"
            else home / ".hermes" / "skills" / "hm-status" / "SKILL.md"
        ),
        "opencode": home / ".config" / "opencode" / "commands" / "hm-status.md",
        "antigravity": (
            home / ".gemini" / "antigravity" / "global_workflows" / "hm-status.md"
        ),
    }

    for client in COMMAND_HOSTS:
        first = sync_host_commands(
            client=client,
            project_root=project_a,
            scope="user",
            source_dir=source_dir,
        )
        second_destination = default_host_commands_dir(client, project_b, scope="user")
        assert first.destination_dir == second_destination
        assert expected[client].exists()
        assert not (project_a / ".agents").exists()
        assert not (project_b / ".agents").exists()


@pytest.mark.parametrize("client", COMMAND_HOSTS)
def test_all_host_wake_entries_execute_one_bounded_agent_offer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
) -> None:
    source_dir = Path("plugins/harness-mem/commands/hm")
    home = tmp_path / "home"
    local_appdata = tmp_path / "local-appdata"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    result = sync_host_commands(
        client=client,
        scope="user",
        source_dir=source_dir,
    )
    if client in {"codex", "cursor", "grok", "hermes"}:
        wake_path = result.destination_dir / "hm-wake" / "SKILL.md"
    elif client == "claude-code":
        wake_path = result.destination_dir / "wake.md"
    else:
        wake_path = result.destination_dir / "hm-wake.md"
    rendered = wake_path.read_text(encoding="utf-8")

    assert "agent_execution_required=true" in rendered
    assert "distill_job_id=<offered id>" in rendered
    assert "run_ingest=false" in rendered
    assert "defer_job_id=<offered id>" in rendered
    assert "这是只读操作" not in rendered


def test_generated_skill_strips_bom_and_uses_host_native_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    status = source_dir / "daily" / "status.md"
    status.write_text(
        '\ufeff---\nname: canonical\n---\nUse `/hm:wake` and host_client="claude-code".\n',
        encoding="utf-8",
    )
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)

    sync_host_commands(client="codex", scope="user", source_dir=source_dir)
    rendered = (home / ".codex" / "skills" / "hm-status" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert rendered.count("---") == 2
    assert "$hm-wake" in rendered
    assert 'host_client="codex"' in rendered
    assert "\ufeff" not in rendered

    sync_host_commands(client="antigravity", scope="user", source_dir=source_dir)
    workflow = (
        home / ".gemini" / "antigravity" / "global_workflows" / "hm-status.md"
    ).read_text(encoding="utf-8")
    assert "/hm-wake" in workflow
    assert 'host_client="antigravity"' in workflow


def test_hermes_user_commands_honor_profile_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    profile_home = tmp_path / "hermes-profile"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    result = sync_host_commands(client="hermes", scope="user", source_dir=source_dir)

    assert result.destination_dir == profile_home / "skills"
    assert (profile_home / "skills" / "hm-wake" / "SKILL.md").exists()


def test_cli_sync_defaults_can_install_all_hosts_at_user_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    home = tmp_path / "home"
    local_appdata = tmp_path / "local-appdata"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    exit_code = cmd_sync_commands(
        profile="daily",
        include=[],
        source_dir=str(source_dir),
        target_dir=None,
        client="all",
        project_root=str(tmp_path / "unrelated-project"),
        scope="user",
        dry_run=False,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.count("Synced 7") == len(COMMAND_HOSTS)
    assert "codex Daily commands" in output
    assert "antigravity Daily commands" in output
    assert (home / ".codex" / "skills" / "hm-wake" / "SKILL.md").exists()
    assert (
        home / ".gemini" / "antigravity" / "global_workflows" / "hm-wake.md"
    ).exists()


def test_cli_rejects_all_hosts_project_scope_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)
    project = tmp_path / "project"

    exit_code = cmd_sync_commands(
        profile="daily",
        include=[],
        source_dir=str(source_dir),
        target_dir=None,
        client="all",
        project_root=str(project),
        scope="project",
        dry_run=False,
    )

    assert exit_code == 1
    assert "--client all supports only --scope user" in capsys.readouterr().err
    assert not project.exists()


def test_cli_target_dir_preserves_legacy_claude_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "claude-commands"
    _write_command_sources(source_dir)

    exit_code = cmd_sync_commands(
        profile="daily",
        include=[],
        source_dir=str(source_dir),
        target_dir=str(target_dir),
        client="all",
        project_root=None,
        scope="user",
        dry_run=False,
    )

    assert exit_code == 0
    assert "claude-code Daily commands" in capsys.readouterr().out
    assert (target_dir / "wake.md").exists()
