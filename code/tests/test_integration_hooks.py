from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

import pytest

import harness_mem.commands.integration_cmds as integration_cmds
import harness_mem.integration.installer as installer
from harness_mem.commands.integration_cmds import cmd_install_hook_suite
from harness_mem.integration.installer import HookSpec, install_hermes_hook_suite, install_hook, install_hook_suite


@pytest.fixture(autouse=True)
def hook_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep template tests independent of a locally installed console script."""

    runner = tmp_path / "harness-mem-hook"
    monkeypatch.setattr(installer, "verified_hook_runner", lambda: runner)
    monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: runner)
    return runner


def _template_vars(tmp_path: Path) -> dict[str, str]:
    project_root = tmp_path.resolve().as_posix()
    runner = (tmp_path / "harness-mem-hook").resolve().as_posix()
    return {
        "WAKE_COMMAND_JSON": json.dumps(
            f"{shlex.quote(runner)} --action wake-start --project-root {shlex.quote(project_root)} "
            "--source ide_hook --trigger-id template-wake --client grok"
        ),
        "POST_TURN_COMMAND_JSON": json.dumps(
            f"{shlex.quote(runner)} --action post-turn-maintenance --project-root "
            f"{shlex.quote(project_root)} --source ide_hook --trigger-id template-stop --client grok"
        ),
        "STOP_COMMAND_JSON": json.dumps(
            f"{shlex.quote(runner)} --adapter codex-stop --project-root {shlex.quote(project_root)}"
        ),
    }


def _install_template(
    tmp_path: Path,
    template_name: str,
    *,
    template_vars: dict[str, str] | None = None,
) -> str:
    target = tmp_path / template_name.replace(".template", "")
    written = install_hook(
        template_name=template_name,
        target_path=target,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        doc_pointer="docs/quickstart.md",
        template_vars=template_vars,
    )
    return written.read_text(encoding="utf-8")


def test_post_turn_hook_templates_bind_the_verified_runner(tmp_path: Path, hook_runner: Path) -> None:
    for template in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        body = _install_template(tmp_path, template)

        assert hook_runner.as_posix() in body
        assert "python -m harness_mem.host_entry" not in body
        assert "--action post-turn-maintenance" in body
        assert "--client" in body
        assert ">/dev/null 2>&1" in body
        assert "HARNESS_MEM_HOOK_DEBUG" in body
        assert "harness-mem-hook failed" in body
        assert "reflection" not in body.lower()
        assert "metabolism" not in body.lower()


def test_wake_start_hook_templates_keep_stdout_for_injection(tmp_path: Path, hook_runner: Path) -> None:
    for template in ("cursor_session_start.sh.template", "claude_code_session_start.sh.template"):
        body = _install_template(tmp_path, template)

        assert hook_runner.as_posix() in body
        assert "python -m harness_mem.host_entry" not in body
        assert "--action wake-start" in body
        assert ">/dev/null 2>&1" not in body
        assert "2>/dev/null" in body
        assert "HARNESS_MEM_HOOK_DEBUG" in body
        assert "harness-mem-hook failed" in body


def test_shell_hook_templates_shell_quote_project_root(tmp_path: Path) -> None:
    dangerous_root = tmp_path / "proj $(touch owned) $HOME"
    dangerous_root.mkdir()
    quoted_root = shlex.quote(dangerous_root.resolve().as_posix())

    for template in (
        "cursor_after_agent.sh.template",
        "claude_code_hook.sh.template",
        "cursor_session_start.sh.template",
        "claude_code_session_start.sh.template",
    ):
        body = _install_template(dangerous_root, template)
        assert f"PROJECT_ROOT={quoted_root}" in body
        assert f'PROJECT_ROOT="{dangerous_root.resolve().as_posix()}"' not in body


def test_json_and_opencode_templates_bind_the_verified_runner(tmp_path: Path, hook_runner: Path) -> None:
    shared_vars = _template_vars(tmp_path)
    grok = _install_template(tmp_path, "grok_hooks.json.template", template_vars=shared_vars)
    assert '"SessionStart"' in grok
    assert '"Stop"' in grok
    assert hook_runner.as_posix() in grok
    assert "python -m harness_mem.host_entry" not in grok

    codex = _install_template(tmp_path, "codex_hooks.json.template", template_vars=shared_vars)
    assert '"SessionStart"' in codex
    assert '"Stop"' in codex
    assert hook_runner.as_posix() in codex
    assert "--adapter codex-stop" in codex
    assert "harness_mem_stop.py" not in codex

    opencode = _install_template(tmp_path, "opencode_plugin.ts.template")
    assert "session.created" in opencode
    assert "session.idle" in opencode
    assert f'const hookRunner = "{hook_runner.as_posix()}"' in opencode
    assert "$${hookRunner}" not in opencode
    assert "${hookRunner}" in opencode
    assert "python -m harness_mem.host_entry" not in opencode


def test_hook_suite_installer_creates_cursor_and_claude_suites(tmp_path: Path, hook_runner: Path) -> None:
    specs = (
        HookSpec("cursor_session_start.sh.template", tmp_path / ".cursor" / "hooks" / "session-start.sh"),
        HookSpec("cursor_after_agent.sh.template", tmp_path / ".cursor" / "hooks" / "after-agent.sh"),
    )
    results = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [result.status for result in results] == ["installed", "installed"]
    assert hook_runner.as_posix() in results[0].target_path.read_text(encoding="utf-8")
    assert "--action post-turn-maintenance" in results[1].target_path.read_text(encoding="utf-8")


def test_hook_suite_installer_upgrades_legacy_managed_hooks(tmp_path: Path, hook_runner: Path) -> None:
    target = tmp_path / ".cursor" / "hooks" / "after-agent.sh"
    target.parent.mkdir(parents=True)
    target.write_text("python -m harness_mem.host_entry --action post-turn-maintenance", encoding="utf-8")

    results = install_hook_suite(
        specs=(HookSpec("cursor_after_agent.sh.template", target),),
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [result.status for result in results] == ["updated"]
    body = target.read_text(encoding="utf-8")
    assert hook_runner.as_posix() in body
    assert "python -m harness_mem.host_entry" not in body


def test_hook_suite_installer_is_idempotent(tmp_path: Path) -> None:
    specs = (
        HookSpec("cursor_session_start.sh.template", tmp_path / ".cursor" / "hooks" / "session-start.sh"),
        HookSpec("cursor_after_agent.sh.template", tmp_path / ".cursor" / "hooks" / "after-agent.sh"),
    )
    first = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert [item.status for item in first] == ["installed", "installed"]
    assert [item.status for item in second] == ["unchanged", "unchanged"]


def test_hook_suite_rejects_unverified_existing_file(tmp_path: Path) -> None:
    target = tmp_path / ".cursor" / "hooks" / "after-agent.sh"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="was not installed by this harness-mem setup"):
        install_hook_suite(
            specs=(HookSpec("cursor_after_agent.sh.template", target),),
            project_root=tmp_path,
            force=False,
            harness_mem_version="test",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho unrelated\n"


def test_hook_suite_force_reports_existing_targets_as_updated(tmp_path: Path) -> None:
    target = tmp_path / ".cursor" / "hooks" / "after-agent.sh"
    specs = (HookSpec("cursor_after_agent.sh.template", target),)
    install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    results = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=True,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert [item.status for item in results] == ["updated"]


def test_cmd_install_hook_suite_supports_project_local_clients(tmp_path: Path, hook_runner: Path) -> None:
    assert cmd_install_hook_suite("grok", str(tmp_path), False) == 0
    grok_body = (tmp_path / ".grok" / "hooks" / "harness-mem.json").read_text(encoding="utf-8")
    assert hook_runner.as_posix() in grok_body
    assert "--client grok" in grok_body

    assert cmd_install_hook_suite("codex", str(tmp_path), False) == 0
    codex_body = (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
    assert hook_runner.as_posix() in codex_body
    assert "--adapter codex-stop" in codex_body
    assert not (tmp_path / ".codex" / "hooks" / "harness_mem_stop.py").exists()

    assert cmd_install_hook_suite("opencode", str(tmp_path), False) == 0
    plugin_body = (tmp_path / ".opencode" / "plugins" / "harness-mem.ts").read_text(encoding="utf-8")
    assert hook_runner.as_posix() in plugin_body

    assert cmd_install_hook_suite("antigravity", str(tmp_path), False) == 0
    antigravity = json.loads((tmp_path / ".agents" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in antigravity["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert any("--adapter antigravity-pre" in command for command in commands)
    assert any("--adapter antigravity-stop" in command for command in commands)
    assert all(hook_runner.as_posix() in command for command in commands)


def test_antigravity_hook_install_preserves_existing_events(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".agents" / "hooks.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"hooks": {"PostInvocation": [{"hooks": [{"command": "keep-me"}]}]}}),
        encoding="utf-8",
    )

    assert cmd_install_hook_suite("antigravity", str(tmp_path), False) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["hooks"]["PostInvocation"][0]["hooks"][0]["command"] == "keep-me"
    assert len(manifest["hooks"]["PreInvocation"]) == 1
    assert len(manifest["hooks"]["Stop"]) == 1


def test_hook_suite_command_strings_shell_quote_project_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dangerous_root = tmp_path / "proj $(touch owned) $HOME"
    dangerous_root.mkdir()
    quoted_root = shlex.quote(dangerous_root.resolve().as_posix())

    assert cmd_install_hook_suite("grok", str(dangerous_root), False) == 0
    capsys.readouterr()
    grok = json.loads((dangerous_root / ".grok" / "hooks" / "harness-mem.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for event in grok["hooks"].values()
        for group in event
        for hook in group["hooks"]
    ]
    assert commands
    assert all(quoted_root in command for command in commands)
    assert all(f'"{dangerous_root.resolve().as_posix()}"' not in command for command in commands)

    assert cmd_install_hook_suite("codex", str(dangerous_root), False) == 0
    capsys.readouterr()
    codex = json.loads((dangerous_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    codex_commands = [
        hook["command"]
        for event in codex["hooks"].values()
        for group in event
        for hook in group["hooks"]
    ]
    assert any(quoted_root in command for command in codex_commands)


def test_cmd_install_hook_suite_supports_hermes_global_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_runner: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 0
    config_path = home / ".hermes" / "config.yaml"
    config_body = config_path.read_text(encoding="utf-8")
    assert hook_runner.as_posix() in config_body
    assert "--adapter hermes-pre" in config_body
    assert "--adapter hermes-post" in config_body
    assert "--project-root" not in config_body
    assert "python " not in config_body


def test_hermes_hook_suite_normalizes_empty_inline_hooks_config(tmp_path: Path, hook_runner: Path) -> None:
    home = tmp_path / "home"
    config_path = home / ".hermes" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("hooks: []\nother: true\n", encoding="utf-8")

    install_hermes_hook_suite(
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        home_dir=home,
    )
    config_body = config_path.read_text(encoding="utf-8")
    assert "hooks: []" not in config_body
    assert "hooks:\n" in config_body
    assert "  pre_llm_call:" in config_body
    assert "  post_llm_call:" in config_body
    assert hook_runner.as_posix() in config_body
    assert "other: true" in config_body
