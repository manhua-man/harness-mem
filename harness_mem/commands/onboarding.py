"""One-time user-level onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from harness_mem.config.errors import ConfigError
from harness_mem.config.writer import set_value
from harness_mem.commands.support import detect_runtime_client
from harness_mem.integration.command_sync import (
    CommandHost,
    command_hint,
    sync_host_commands,
)
from harness_mem.integration.repair import repair_project_hooks


def cmd_quickstart(client: str = "auto", *, confirm: bool = False) -> int:
    """Install native session learning once; confirm background model use explicitly."""

    selected_client = detect_runtime_client() if client == "auto" else client
    if selected_client is None:
        print(
            "Could not detect the current app. Run quickstart again with --client "
            "and the app name, for example: harness-mem quickstart --client cursor."
        )
        return 1

    host_client = cast(CommandHost, selected_client)
    try:
        sync_host_commands(client=host_client)
        report = repair_project_hooks(clients=(host_client,), scope="user", project_root=Path.cwd())
        if not report.success:
            print(f"Automatic memory setup failed: {report.results[0].error}")
            return 1
        if confirm:
            set_value(scope="user", project_root="", key_path="distill.autonomous.enabled", value="true")
    except (FileNotFoundError, OSError, ValueError, ConfigError) as exc:
        print(f"Could not prepare automatic memory: {exc}")
        return 1

    hint = command_hint(host_client)
    print(f"Installed {hint} and user-level lifecycle Hooks for {host_client}.")
    if confirm:
        print("Background learning is enabled for task endings; explicit project settings still take precedence.")
    else:
        print("Background authorization is unchanged. Use quickstart --confirm to authorize automatic model processing once.")
    if host_client == "codex":
        print("Review and trust the user Hooks in Codex Settings > Hooks, then start a new task.")
    elif host_client == "hermes":
        print("On first use, review Hermes' native confirmation for these shell Hooks.")
    print(
        f"Then converse normally. Use {hint} to inspect, review or correct stored memory."
    )
    print(
        "Otherwise, ask the Agent, MCP Router, plugin, or existing setup tool "
        "that manages your MCP connection to connect harness-mem. "
        "See docs/mcp-setup.md."
    )
    print("Quickstart does not inspect or change MCP connections.")
    return 0
