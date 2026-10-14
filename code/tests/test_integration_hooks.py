from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import harness_mem.commands.integration_cmds as integration_cmds
import harness_mem.integration.installer as installer
from harness_mem.integration.command_sync import default_host_commands_dir, sync_host_commands
from harness_mem.commands.integration_cmds import cmd_install_hook_suite
from harness_mem.integration.installer import HookSpec, install_hermes_hook_suite, install_hook, install_hook_suite


@pytest.fixture(autouse=True)
def hook_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep template tests independent of a locally installed console script."""

    runner = tmp_path / "harness-mem-hook"
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
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
        assert "--adapter" in body and "-stop" in body
        assert "TURN_ID" not in body
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
        assert "--adapter" in body and "-start" in body
        assert "TURN_ID" not in body
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
    assert "event.properties.info.id" in opencode
    assert "event.properties.sessionID" in opencode
    assert "--trigger-id ${sessionId}" in opencode
    assert "appendPrompt({ body:" in opencode
    assert "opencode-session-idle" not in opencode


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
    assert "--adapter cursor-stop" in results[1].target_path.read_text(encoding="utf-8")


def test_hook_suite_preserves_legacy_custom_hooks_until_explicit_force(
    tmp_path: Path, hook_runner: Path,
) -> None:
    target = tmp_path / ".cursor" / "hooks" / "after-agent.sh"
    target.parent.mkdir(parents=True)
    original = "python -m harness_mem.host_entry --action post-turn-maintenance\necho user-customized\n"
    target.write_text(original, encoding="utf-8")

    with pytest.raises(FileExistsError, match="conflicts"):
        install_hook_suite(
            specs=(HookSpec("cursor_after_agent.sh.template", target),),
            project_root=tmp_path,
            harness_mem_version="test",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    with pytest.raises(FileExistsError):
        install_hook(
            template_name="cursor_after_agent.sh.template",
            target_path=target,
            project_root=tmp_path,
            harness_mem_version="test",
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    assert target.read_text(encoding="utf-8") == original

    results = install_hook_suite(
        specs=(HookSpec("cursor_after_agent.sh.template", target),),
        project_root=tmp_path,
        force=True,
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
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert [item.status for item in first] == ["installed", "installed"]
    assert [item.status for item in second] == ["unchanged", "unchanged"]


def test_hook_suite_rejects_unverified_existing_file(tmp_path: Path) -> None:
    target = tmp_path / ".cursor" / "hooks" / "after-agent.sh"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="conflicts"):
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
    assert "--adapter grok-stop" in grok_body

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


@pytest.mark.parametrize(
    ("host", "relative", "start_event", "stop_event"),
    [("claude-code", ".claude/settings.json", "SessionStart", "Stop"),
     ("cursor", ".cursor/hooks.json", "sessionStart", "stop")],
)
def test_shell_host_hooks_are_registered_and_preserve_user_settings(
    tmp_path: Path, host: str, relative: str, start_event: str, stop_event: str,
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    unrelated = {"hooks": [{"type": "command", "command": "echo keep-me"}]} if host == "claude-code" else {"command": "echo keep-me"}
    path.write_text(json.dumps({"user_setting": True, "hooks": {stop_event: [unrelated]}}), encoding="utf-8")

    assert cmd_install_hook_suite(host, str(tmp_path), False) == 0
    first = path.read_text(encoding="utf-8")
    manifest = json.loads(first)
    assert manifest["user_setting"] is True
    assert unrelated in manifest["hooks"][stop_event]
    assert len(manifest["hooks"][start_event]) == 1
    assert len(manifest["hooks"][stop_event]) == 2
    if host == "cursor":
        assert manifest["version"] == 1
    assert cmd_install_hook_suite(host, str(tmp_path), False) == 0
    assert path.read_text(encoding="utf-8") == first


@pytest.mark.parametrize("host,relative", [("claude-code", ".claude/settings.json"), ("cursor", ".cursor/hooks.json")])
def test_invalid_native_manifest_is_rejected_before_writing_scripts(tmp_path: Path, host: str, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert cmd_install_hook_suite(host, str(tmp_path), False) != 0
    assert path.read_text(encoding="utf-8") == "{broken"
    assert not (path.parent / "hooks").exists()


def test_claude_force_preserves_unrelated_hooks_in_a_mixed_group(tmp_path: Path) -> None:
    assert cmd_install_hook_suite("claude-code", str(tmp_path), False) == 0
    path = tmp_path / ".claude/settings.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    managed = manifest["hooks"]["Stop"][0]
    managed["matcher"] = "custom"
    managed["hooks"].append({"type": "command", "command": "echo unrelated"})
    path.write_text(json.dumps(manifest), encoding="utf-8")
    original = path.read_bytes()
    assert cmd_install_hook_suite("claude-code", str(tmp_path), False) != 0
    assert path.read_bytes() == original
    assert cmd_install_hook_suite("claude-code", str(tmp_path), True) == 0
    groups = json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"]
    assert groups[0] == {"matcher": "custom", "hooks": [{"type": "command", "command": "echo unrelated"}]}
    assert len(groups) == 2


def test_script_conflict_does_not_partially_install_a_suite(tmp_path: Path) -> None:
    target = tmp_path / ".cursor/hooks/after-agent.sh"
    target.parent.mkdir(parents=True)
    target.write_text("echo user-owned\n", encoding="utf-8")
    assert cmd_install_hook_suite("cursor", str(tmp_path), False) != 0
    assert target.read_text(encoding="utf-8") == "echo user-owned\n"
    assert not (target.parent / "session-start.sh").exists()
    assert not (tmp_path / ".cursor/hooks.json").exists()


@pytest.mark.parametrize("host,relative,event,script", [
    ("claude-code", ".claude/settings.json", "Stop", ".claude/hooks/after-turn.sh"),
    ("cursor", ".cursor/hooks.json", "stop", ".cursor/hooks/after-agent.sh"),
])
def test_force_preserves_another_projects_same_named_script(tmp_path: Path, host, relative, event, script) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    foreign = tmp_path.parent / "unrelated-project" / script
    entry = {"command": f"bash {shlex.quote(foreign.as_posix())}"}
    wrapped = {"command": f"echo {shlex.quote((tmp_path / script).as_posix())}"}
    if host == "claude-code":
        entry = {"hooks": [{"type": "command", **entry}]}
        wrapped = {"hooks": [{"type": "command", **wrapped}]}
    path.write_text(json.dumps({"hooks": {event: [entry, wrapped]}}), encoding="utf-8")
    assert cmd_install_hook_suite(host, str(tmp_path), True) == 0
    groups = json.loads(path.read_text(encoding="utf-8"))["hooks"][event]
    assert entry in groups
    assert wrapped in groups
    assert len(groups) == 3


def test_hermes_unsupported_valid_indentation_does_not_corrupt_config(tmp_path: Path) -> None:
    path = default_host_commands_dir("hermes").parent / "config.yaml"
    path.parent.mkdir(parents=True)
    original = 'hooks:\n    pre_llm_call:\n        - command: echo custom\n          timeout: 30\nother: true\n'
    path.write_text(original, encoding="utf-8")
    assert cmd_install_hook_suite("hermes", str(tmp_path), True) != 0
    assert path.read_text(encoding="utf-8") == original


def test_generated_opencode_plugin_transmits_distinct_native_sessions(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable for the isolated TypeScript event replay")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True)
    if int(version.stdout.strip().lstrip("v").split(".")[0]) < 22:
        pytest.skip("Node 22+ is needed for built-in TypeScript stripping")
    body = _install_template(tmp_path, "opencode_plugin.ts.template")
    plugin_path = tmp_path / "plugin.mts"
    plugin_path.write_text(body, encoding="utf-8")
    replay = tmp_path / "replay.mjs"
    replay.write_text('''import assert from "node:assert/strict";
import plugin from "./plugin.mts";
const calls = [];
const prompts = [];
const shell = (strings, ...values) => {
  calls.push({ strings: [...strings], values });
  return { text: async () => "known context", quiet: async () => {} };
};
const hooks = await plugin({ $: shell, client: { tui: {
  appendPrompt: async (input) => { assert.equal(typeof input.body.text, "string"); prompts.push(input); }
}}});
for (const id of ["session-one", "session-two"]) {
  await hooks.event({ event: { type: "session.created", properties: { info: { id } } } });
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: id } } });
}
assert.equal(calls.length, 4);
assert.deepEqual(calls.map(call => call.values[2]), ["session-one", "session-one", "session-two", "session-two"]);
assert.equal(prompts.length, 2);
await hooks.event({ event: { type: "session.idle", properties: {} } });
assert.equal(calls.length, 4);
console.log("native session identities and SDK prompt body verified");
''', encoding="utf-8")
    result = subprocess.run([node, "--experimental-strip-types", str(replay)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("client", ["claude-code", "cursor"])
@pytest.mark.parametrize("debug", ["0", "1"])
def test_registered_stop_script_preserves_failure_status_and_stdin(
    tmp_path: Path, hook_runner: Path, monkeypatch: pytest.MonkeyPatch, client: str, debug: str,
) -> None:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is unavailable for native wrapper replay")
    hook_runner.write_text('#!/usr/bin/env bash\nread -r payload\n[ "$payload" = \'{"session_id":"native-17"}\' ] || exit 8\nexit 7\n', encoding="utf-8")
    hook_runner.chmod(0o755)
    assert cmd_install_hook_suite(client, str(tmp_path), False) == 0
    relative = ".claude/hooks/after-turn.sh" if client == "claude-code" else ".cursor/hooks/after-agent.sh"
    monkeypatch.setenv("HARNESS_MEM_HOOK_DEBUG", debug)
    result = subprocess.run([bash, (tmp_path / relative).as_posix()], input=b'{"session_id":"native-17"}\n', capture_output=True, timeout=10)
    assert result.returncode == 7, result.stdout + result.stderr
    assert result.stdout == b""


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
    config_path = default_host_commands_dir("hermes").parent / "config.yaml"
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


@pytest.mark.parametrize(
    ("platform", "custom_profile", "local_appdata"),
    [("win32", True, True), ("linux", True, True),
     ("win32", False, True), ("win32", False, False), ("linux", False, True)],
)
def test_hermes_entry_and_hooks_share_only_the_active_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    platform: str, custom_profile: bool, local_appdata: bool,
) -> None:
    home = tmp_path / "home"
    appdata = tmp_path / "local-appdata"
    custom = tmp_path / "custom profile"
    monkeypatch.setattr(sys, "platform", platform)
    if custom_profile:
        monkeypatch.setenv("HERMES_HOME", f"  {custom}  ")
    if not local_appdata:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    expected = custom if custom_profile else (
        (appdata if local_appdata else home / "AppData" / "Local") / "hermes"
        if platform == "win32" else home / ".hermes"
    )
    profiles = {custom, appdata / "hermes", home / "AppData" / "Local" / "hermes",
                home / ".hermes", tmp_path / "other-profile"}
    originals: dict[Path, bytes] = {}
    for profile in profiles:
        config = profile / "config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("model: user-selected\n", encoding="utf-8")
        if profile != expected:
            entry = profile / "skills" / "hm" / "SKILL.md"
            entry.parent.mkdir(parents=True)
            entry.write_text("user profile entry\n", encoding="utf-8")
            originals[config] = config.read_bytes()
            originals[entry] = entry.read_bytes()
    source = tmp_path / "source"
    source.mkdir()
    (source / "hm.md").write_text("# HM\n", encoding="utf-8")

    entry_result = sync_host_commands(client="hermes", source_dir=source)
    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 0

    assert entry_result.destination_dir == expected / "skills"
    assert (expected / "skills" / "hm" / "SKILL.md").is_file()
    config_body = (expected / "config.yaml").read_text(encoding="utf-8")
    assert "--adapter hermes-pre" in config_body
    assert "--adapter hermes-post" in config_body
    assert "model: user-selected" in config_body
    assert all(path.read_bytes() == before for path, before in originals.items())


def test_hermes_explicit_home_dir_retains_compatibility_over_active_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / "active-profile"
    profile.mkdir()
    active_config = profile / "config.yaml"
    active_config.write_text("user-owned\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(profile))
    home = tmp_path / "explicit-home"
    results = install_hermes_hook_suite(
        project_root=tmp_path, home_dir=home,
        harness_mem_version="test", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert results[0].target_path == (home / ".hermes" / "config.yaml").resolve()
    assert active_config.read_text(encoding="utf-8") == "user-owned\n"


@pytest.mark.parametrize("client", ["cursor", "codex", "opencode", "antigravity"])
@pytest.mark.parametrize("change", ["runner", "template", "user_edit"])
def test_hook_upgrade_conflict_preserves_files_then_explicit_force_rechecks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    client: str, change: str,
) -> None:
    mcp = tmp_path / ".mcp.json"
    mcp.write_text('{"mcpServers": {"existing": {"command": "router"}}}', encoding="utf-8")
    mcp_before = mcp.read_bytes()
    assert cmd_install_hook_suite(client, str(tmp_path), False) == 0
    installed = json.loads(capsys.readouterr().out)
    artifacts = [Path(path) for path in installed["results"][0]["artifacts"]]
    if change == "runner":
        runner = tmp_path / "new installation" / "harness-mem-hook"
        monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: runner)
    elif change == "template":
        # Change only isolated copies, keeping packaged templates untouched.
        templates = installer.resources.files(installer._TEMPLATES_PACKAGE)
        fixture_templates = tmp_path / "templates"
        fixture_templates.mkdir()
        for template in templates.iterdir():
            if template.name.endswith(".template"):
                body = template.read_text(encoding="utf-8")
                if template.name.endswith(".json.template"):
                    body = body.replace('"hooks":', '"hooks" :')
                else:
                    body += "\n// template revision\n" if ".ts." in template.name else "\n# template revision\n"
                (fixture_templates / template.name).write_text(body, encoding="utf-8")
        monkeypatch.setattr(installer.resources, "files", lambda _package: fixture_templates)
        if client == "antigravity":
            original_group = installer._antigravity_hook_group

            def revised_group(*args):
                group = original_group(*args)
                group["hooks"][0]["timeout"] = 30
                return group

            monkeypatch.setattr(installer, "_antigravity_hook_group", revised_group)
    else:
        target = artifacts[0]
        body = target.read_text(encoding="utf-8")
        if client in {"codex", "antigravity"}:
            payload = json.loads(body)
            if client == "antigravity":
                payload["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 301
            else:
                payload["user_customization"] = True
            body = json.dumps(payload) + "\n"
        else:
            body += "\n// user customization\n" if client == "opencode" else "\n# user customization\n"
        target.write_text(body, encoding="utf-8")
    before = {path: path.read_bytes() for path in artifacts}

    assert cmd_install_hook_suite(client, str(tmp_path), False) == 1
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["success"] is False
    assert conflict["results"][0]["error_kind"] == "conflict"
    assert "file preserved" in conflict["results"][0]["error"]
    assert "Review ownership" in conflict["results"][0]["error"]
    assert all(path.read_bytes() == old for path, old in before.items())

    assert cmd_install_hook_suite(client, str(tmp_path), True) == 0
    updated = json.loads(capsys.readouterr().out)
    assert updated["results"][0]["status"] == "updated"
    assert any(path.read_bytes() != old for path, old in before.items())
    assert cmd_install_hook_suite(client, str(tmp_path), False) == 0
    rechecked = json.loads(capsys.readouterr().out)
    assert rechecked["results"][0]["status"] == "unchanged"
    assert mcp.read_bytes() == mcp_before


@pytest.mark.parametrize("change", ["runner", "user_edit"])
def test_hermes_upgrade_preserves_whole_config_until_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(profile))
    config = profile / "config.yaml"
    config.parent.mkdir()
    unrelated = 'model: keep\nhooks:\n  pre_llm_call:\n    - command: "echo user-hook"\n      timeout: 9\n'
    config.write_text(unrelated, encoding="utf-8")
    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 0
    capsys.readouterr()
    if change == "runner":
        monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: tmp_path / "new-runner")
    else:
        body = config.read_text(encoding="utf-8").replace("timeout: 300", "timeout: 301")
        config.write_text(body, encoding="utf-8")
    before = config.read_bytes()

    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 1
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["results"][0]["error_kind"] == "conflict"
    assert str(config.resolve()) in conflict["results"][0]["error"]
    assert config.read_bytes() == before

    assert cmd_install_hook_suite("hermes", str(tmp_path), True) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "updated"
    after = config.read_text(encoding="utf-8")
    assert "model: keep" in after
    assert '    - command: "echo user-hook"\n      timeout: 9\n' in after
    assert "timeout: 301" not in after
    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "unchanged"


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("body", [
    'hooks: {pre_llm_call: [{command: "echo keep"}]}\n',
    'hooks:\n  pre_llm_call: [{command: "echo keep"}]\n',
    'hooks:\n  pre_llm_call:\n    # harness-mem:begin pre_llm_call\n    - command: "echo keep"\n',
])
def test_hermes_unsafe_merge_retains_user_config(
    tmp_path: Path, body: str, force: bool,
) -> None:
    home = tmp_path / "explicit-home"
    config = home / ".hermes" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(body, encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(ValueError, match="cannot safely merge"):
        install_hermes_hook_suite(
            project_root=tmp_path, home_dir=home, force=force,
            harness_mem_version="test", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    assert config.read_bytes() == before
