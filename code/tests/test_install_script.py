from __future__ import annotations

import json
from pathlib import Path


def test_install_script_passes_named_profile_argument() -> None:
    script = Path("code/plugins/harness-mem/scripts/install.ps1").read_text(encoding="utf-8")

    assert '& $syncCommands -Profile "Daily" -Client "all" -Scope "user"' in script
    assert "@syncArgs" not in script


def test_packaged_runtime_includes_daily_command_assets() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'code/plugins/harness-mem/commands/hm/daily/*.md' in pyproject


def test_plugin_mcp_config_uses_installed_console_script() -> None:
    config = json.loads(
        Path("code/plugins/harness-mem/.mcp.json").read_text(encoding="utf-8")
    )

    server = config["mcpServers"]["harness_mem"]
    assert server["command"] == "harness-mem-mcp"
    assert server.get("args", []) == []


def test_distill_command_resolves_aliases_and_canonical_skill_uses_logical_names() -> None:
    command = Path(
        "code/plugins/harness-mem/commands/hm/daily/distill.md"
    ).read_text(encoding="utf-8")
    skill = Path("code/tools/hm-distill/SKILL.md").read_text(encoding="utf-8")

    assert "mcp__mcp_router__prepare_session_distill" in command
    assert "mcp__harness_mem__prepare_session_distill" in command
    assert "先检查当前 task 的可调用工具" in command
    assert "prepare_session_distill" in skill
    assert "finalize_session_distill" in skill
    assert "answer_packet" in skill
    assert "promoted_items" in skill
    assert "never copy an Agent-authored status" in skill
    assert "mcp__mcp_router__" not in skill
    assert "mcp__harness_mem__" not in skill


def test_mcp_setup_explains_router_namespace_and_task_refresh() -> None:
    setup = Path("docs/mcp-setup.md").read_text(encoding="utf-8")

    assert "mcp__mcp_router__get_project_status" in setup
    assert "mcp__harness_mem__get_project_status" in setup
    assert "existing tasks keep the tool snapshot" in setup
