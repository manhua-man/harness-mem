from __future__ import annotations

import json
from pathlib import Path


def test_install_script_installs_runtime_without_managing_agent_connections() -> None:
    script = Path("code/plugins/harness-mem/scripts/install.ps1").read_text(encoding="utf-8")

    assert "pip install -e" in script
    assert "harness-mem quickstart once" in script
    assert "sync-commands.ps1" not in script
    assert "mcp add" not in script
    assert "RegisterClaude" not in script


def test_packaged_runtime_includes_only_the_single_command_asset() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'code/plugins/harness-mem/commands/hm/hm.md' in pyproject
    assert 'commands/hm/daily/*.md' not in pyproject


def test_plugin_mcp_config_uses_installed_console_script() -> None:
    config = json.loads(
        Path("code/plugins/harness-mem/.mcp.json").read_text(encoding="utf-8")
    )

    server = config["mcpServers"]["harness_mem"]
    assert server["command"] == "harness-mem-mcp"
    assert server.get("args", []) == []


def test_single_command_and_canonical_distill_skill_use_logical_tool_names() -> None:
    command = Path("code/plugins/harness-mem/commands/hm/hm.md").read_text(
        encoding="utf-8"
    )
    skill = Path("code/tools/hm-distill/SKILL.md").read_text(encoding="utf-8")

    assert "get_project_status" in command
    assert "prepare_session_distill" in command
    assert "finalize_session_distill" in command
    assert "mcp__mcp_router__" not in command
    assert "mcp__harness_mem__" not in command
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


def test_public_source_install_examples_use_converged_code_path() -> None:
    paths = (
        Path("README.md"),
        Path("README.zh-CN.md"),
        Path("docs/quickstart.md"),
        Path("docs/mcp-setup.md"),
        Path("code/plugins/harness-mem/README.md"),
    )

    for path in paths:
        body = path.read_text(encoding="utf-8")
        assert r".\plugins\harness-mem\scripts\install.ps1" not in body
        if r"scripts\install.ps1" in body:
            assert r".\code\plugins\harness-mem\scripts\install.ps1" in body

    plugin = Path("code/plugins/harness-mem/README.md").read_text(encoding="utf-8")
    assert r".\code\plugins\harness-mem\scripts\install.ps1" in plugin
