"""Shared host executor constants."""

from __future__ import annotations

AGENT_HOST_CLIENTS = frozenset({"codex", "claude-code", "hermes", "opencode"})


def host_cli_provider_name(host_client: str) -> str:
    return f"{host_client}_cli"


__all__ = ["AGENT_HOST_CLIENTS", "host_cli_provider_name"]
