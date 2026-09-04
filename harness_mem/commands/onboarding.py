"""One-time user-level onboarding."""

from __future__ import annotations

from typing import cast

from harness_mem.commands.support import detect_runtime_client
from harness_mem.integration.command_sync import (
    CommandHost,
    command_hint,
    sync_host_commands,
)


def cmd_quickstart(client: str = "auto") -> int:
    """Install the current host's global memory entry once."""

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
    except (FileNotFoundError, OSError) as exc:
        print(f"Could not install the memory entry: {exc}")
        return 1

    hint = command_hint(host_client)
    print(f"Installed {hint} for {host_client}. Start a new Agent task to use it.")
    return 0
