"""Build the authorized background semantic executor for a host client."""

from __future__ import annotations

from typing import Any

from harness_mem.autonomous.authorization import background_ready
from harness_mem.autonomous.executors.constants import AGENT_HOST_CLIENTS
from harness_mem.autonomous.executors.host_cli import HostCliAgentExecutor
from harness_mem.autonomous.provider import ProviderError
from harness_mem.commands.support import normalize_client_name
from harness_mem.config.merge import MergedConfig

__all__ = ["AGENT_HOST_CLIENTS", "build_semantic_executor"]


def build_semantic_executor(config: MergedConfig, client: str) -> Any:
    """Return the host CLI executor when the project is authorized."""

    if not background_ready(config):
        raise ProviderError(
            "Background memory is disabled (distill.autonomous.enabled=false)",
            kind="setup_required",
        )
    host_client = normalize_client_name(client)
    if host_client not in AGENT_HOST_CLIENTS:
        host_client = "codex"
    executor = HostCliAgentExecutor(config=config, host_client=host_client)
    if executor._cli is None:
        raise ProviderError(
            f"{host_client} CLI executable was not found",
            kind="setup_required",
        )
    return executor
