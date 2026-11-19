from __future__ import annotations

import json
from pathlib import Path


def test_install_script_installs_runtime_without_managing_agent_connections() -> None:
    script = Path("code/plugins/harness-mem/scripts/install.ps1").read_text(encoding="utf-8")

    assert "pip install -e" in script
    assert "connect harness-mem-mcp" in script.lower()
    assert "sync-commands.ps1" not in script
    assert "mcp add" not in script
    assert "RegisterClaude" not in script


def test_packaged_runtime_does_not_require_the_retired_command_asset() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'code/plugins/harness-mem/commands/hm/hm.md' not in pyproject
    assert 'commands/hm/daily/*.md' not in pyproject


def test_plugin_mcp_config_uses_installed_console_script() -> None:
    config = json.loads(
        Path("code/plugins/harness-mem/.mcp.json").read_text(encoding="utf-8")
    )

    server = config["mcpServers"]["harness_mem"]
    assert server["command"] == "harness-mem-mcp"
    assert server.get("args", []) == []
