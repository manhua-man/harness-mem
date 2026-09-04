"""Build the authorized background semantic executor for a host client."""

from __future__ import annotations

from typing import Any

from harness_mem.autonomous.authorization import background_on
from harness_mem.autonomous.executors.constants import AGENT_HOST_CLIENTS
from harness_mem.autonomous.executors import host_cli
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.support import normalize_client_name
from harness_mem.config.merge import MergedConfig

__all__ = [
    "AGENT_HOST_CLIENTS",
    "build_semantic_executor",
    "inspect_semantic_executor",
    "resolve_semantic_executor_client",
]


def resolve_semantic_executor_client(config: MergedConfig, current_client: str) -> str:
    """Return the configured CLI, using the current host only by default."""

    configured = str(getattr(config, "distill_autonomous_cli", "current") or "current")
    if configured == "current":
        return normalize_client_name(current_client)
    return normalize_client_name(configured)


def inspect_semantic_executor(
    config: MergedConfig,
    current_client: str,
) -> tuple[str, str]:
    """Return ``(selected_cli, reason)`` without launching the CLI."""

    selected = resolve_semantic_executor_client(config, current_client)
    if selected not in AGENT_HOST_CLIENTS:
        return selected, "unsupported_cli"
    if not host_cli._resolve_executable(selected):
        return selected, "cli_not_found"
    return selected, "ok"


def build_semantic_executor(config: MergedConfig, client: str) -> Any:
    """Return the host CLI executor when the project is authorized."""

    if not background_on(config):
        raise ProviderError(
            "Background memory is disabled (distill.autonomous.enabled=false)",
            kind="setup_required",
        )
    host_client = resolve_semantic_executor_client(config, client)
    if host_client not in AGENT_HOST_CLIENTS:
        raise ProviderError(
            f"No background CLI is implemented for '{host_client}'. "
            "Set distill.autonomous.cli to codex, claude-code, hermes, or opencode.",
            kind="setup_required",
        )
    executable = host_cli._resolve_executable(host_client)
    if not executable:
        raise ProviderError(
            f"{host_client} CLI executable was not found",
            kind="setup_required",
        )
    return HostStructuredCliProvider(
        host_client=host_client,
        executable=executable,
    )
