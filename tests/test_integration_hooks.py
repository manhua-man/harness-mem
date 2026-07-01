from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.commands.integration_cmds import cmd_install_hook_suite
from harness_mem.integration.installer import install_hook


def _template_vars(tmp_path: Path) -> dict[str, str]:
    project_root = tmp_path.resolve().as_posix()
    return {
        "WAKE_COMMAND_JSON": json.dumps(
            "python -m harness_mem.host_entry "
            f'--action wake-start --project-root "{project_root}" '
            "--source ide_hook --trigger-id template-wake"
        ),
        "POST_TURN_COMMAND_JSON": json.dumps(
            "python -m harness_mem.host_entry "
            f'--action post-turn-maintenance --project-root "{project_root}" '
            "--source ide_hook --trigger-id template-stop"
        ),
        "STOP_COMMAND_JSON": json.dumps(
            'python "'
            + (tmp_path / ".codex" / "hooks" / "harness_mem_stop.py").resolve().as_posix()
            + '"'
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


def test_dream_end_hook_templates_use_explicit_action(tmp_path: Path) -> None:
    for template in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        body = _install_template(tmp_path, template)

        assert "python -m harness_mem.host_entry" in body
        assert "--action post-turn-maintenance" in body
        assert "--session-ids" not in body
        assert "triggers.after_agent" not in body
        assert "reflection" not in body.lower()
        assert "metabolism" not in body.lower()
        assert ">/dev/null 2>&1" in body
        if template == "cursor_after_agent.sh.template":
            assert "install-cursor-suite" in body
        else:
            assert "install-claude-suite" in body


def test_wake_start_hook_templates_keep_stdout_for_injection(tmp_path: Path) -> None:
    for template in (
        "cursor_session_start.sh.template",
        "claude_code_session_start.sh.template",
    ):
        body = _install_template(tmp_path, template)

        assert "python -m harness_mem.host_entry" in body
        assert "--action wake-start" in body
        assert "triggers.after_agent" not in body
        assert "reflection" not in body.lower()
        assert "metabolism" not in body.lower()
        assert ">/dev/null 2>&1" not in body
        assert "2>/dev/null" in body


def test_new_host_adapter_templates_render_expected_protocol_bridges(tmp_path: Path) -> None:
    shared_vars = _template_vars(tmp_path)

    grok = _install_template(
        tmp_path,
        "grok_hooks.json.template",
        template_vars=shared_vars,
    )
    assert '"SessionStart"' in grok
    assert '"Stop"' in grok
    assert "python -m harness_mem.host_entry" in grok
    assert "--action wake-start" in grok
    assert "--action post-turn-maintenance" in grok

    codex_hooks = _install_template(
        tmp_path,
        "codex_hooks.json.template",
        template_vars=shared_vars,
    )
    assert '"SessionStart"' in codex_hooks
    assert '"Stop"' in codex_hooks
    assert "python -m harness_mem.host_entry" in codex_hooks
    assert "harness_mem_stop.py" in codex_hooks

    codex_stop = _install_template(tmp_path, "codex_stop.py.template")
    assert '"harness_mem.host_entry"' in codex_stop
    assert '"post-turn-maintenance"' in codex_stop
    assert 'sys.stdout.write("{}\\n")' in codex_stop

    hermes_pre = _install_template(tmp_path, "hermes_pre_llm_call.py.template")
    assert '"wake-start"' in hermes_pre
    assert '"harness_mem.host_entry"' in hermes_pre
    assert '"context"' in hermes_pre

    hermes_post = _install_template(tmp_path, "hermes_post_llm_call.py.template")
    assert '"post-turn-maintenance"' in hermes_post
    assert '"harness_mem.host_entry"' in hermes_post
    assert 'sys.stdout.write("{}\\n")' in hermes_post

    opencode = _install_template(tmp_path, "opencode_plugin.ts.template")
    assert "session.created" in opencode
    assert "session.idle" in opencode
    assert "python -m harness_mem.host_entry --action wake-start" in opencode
    assert "python -m harness_mem.host_entry --action post-turn-maintenance" in opencode


def test_hook_suite_installer_creates_cursor_and_claude_suites(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from harness_mem.integration.installer import (
        HookSpec,
        install_hook_suite,
    )

    cursor_specs = (
        HookSpec("cursor_session_start.sh.template", tmp_path / ".cursor" / "hooks" / "session-start.sh"),
        HookSpec("cursor_after_agent.sh.template", tmp_path / ".cursor" / "hooks" / "after-agent.sh"),
    )
    results = install_hook_suite(
        specs=cursor_specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [result.status for result in results] == ["installed", "installed"]
    assert results[0].target_path.exists()
    assert results[1].target_path.exists()
    assert "--action wake-start" in results[0].target_path.read_text(encoding="utf-8")
    assert "--action post-turn-maintenance" in results[1].target_path.read_text(encoding="utf-8")


def test_hook_suite_installer_is_idempotent(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from harness_mem.integration.installer import HookSpec, install_hook_suite

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
    assert [item.status for item in second] == ["exists", "exists"]


def test_cmd_install_hook_suite_supports_project_local_new_clients(tmp_path: Path) -> None:
    assert cmd_install_hook_suite("grok", str(tmp_path), False) == 0
    grok_manifest = tmp_path / ".grok" / "hooks" / "harness-mem.json"
    assert grok_manifest.exists()
    grok_body = grok_manifest.read_text(encoding="utf-8")
    assert '"SessionStart"' in grok_body
    assert '"Stop"' in grok_body

    assert cmd_install_hook_suite("codex", str(tmp_path), False) == 0
    codex_hooks = tmp_path / ".codex" / "hooks.json"
    codex_stop = tmp_path / ".codex" / "hooks" / "harness_mem_stop.py"
    assert codex_hooks.exists()
    assert codex_stop.exists()
    assert "harness_mem_stop.py" in codex_hooks.read_text(encoding="utf-8")
    assert '"post-turn-maintenance"' in codex_stop.read_text(encoding="utf-8")

    assert cmd_install_hook_suite("opencode", str(tmp_path), False) == 0
    opencode_plugin = tmp_path / ".opencode" / "plugins" / "harness-mem.ts"
    assert opencode_plugin.exists()
    plugin_body = opencode_plugin.read_text(encoding="utf-8")
    assert "session.created" in plugin_body
    assert "session.idle" in plugin_body


def test_cmd_install_hook_suite_supports_hermes_global_install(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert cmd_install_hook_suite("hermes", str(tmp_path), False) == 0

    config_path = home / ".hermes" / "config.yaml"
    pre_script = home / ".hermes" / "agent-hooks" / "harness_mem_pre_llm_call.py"
    post_script = home / ".hermes" / "agent-hooks" / "harness_mem_post_llm_call.py"

    assert config_path.exists()
    assert pre_script.exists()
    assert post_script.exists()

    config_body = config_path.read_text(encoding="utf-8")
    assert "hooks:" in config_body
    assert "pre_llm_call:" in config_body
    assert "post_llm_call:" in config_body
    assert pre_script.resolve().as_posix() in config_body
    assert post_script.resolve().as_posix() in config_body
