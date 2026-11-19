"""One-time user-level onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from harness_mem.config.errors import ConfigError
from harness_mem.config.writer import set_value
from harness_mem.commands.support import detect_runtime_client
from harness_mem.integration.installer import HookHost
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

    host_client = cast(HookHost, selected_client)
    try:
        report = repair_project_hooks(clients=(host_client,), scope="user", project_root=Path.cwd())
        if not report.success:
            print(f"Automatic memory setup failed: {report.results[0].error}")
            return 1
        if confirm:
            set_value(scope="user", project_root="", key_path="distill.autonomous.enabled", value="true")
    except (FileNotFoundError, OSError, ValueError, ConfigError) as exc:
        print(f"Could not prepare automatic memory: {exc}")
        return 1

    print(f"Installed user-level lifecycle Hooks for {host_client}.")
    if confirm:
        print("Background learning is enabled for task endings; explicit project settings still take precedence.")
    else:
        print("Background authorization is unchanged. Use quickstart --confirm to authorize automatic model processing once.")
    if host_client == "codex":
        print("Review and trust the user Hooks in Codex Settings > Hooks, then start a new task.")
    elif host_client == "hermes":
        print("On first use, review Hermes' native confirmation for these shell Hooks.")
    print("For manual memory tools, connect harness-mem-mcp in your Agent's MCP settings.")
    return 0
