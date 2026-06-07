"""Version and compatibility constants for runtime surfaces."""

from __future__ import annotations

from harness_mem import __version__

WIRE_FORMAT_VERSION = "hm-wire-v3.4"
PLUGIN_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
SKILL_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
CLI_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
MCP_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION


def runtime_version_payload() -> dict[str, str]:
    """Return the stable version payload exposed by CLI, MCP, plugin and skills."""
    return {
        "runtime_version": __version__,
        "wire_format_version": WIRE_FORMAT_VERSION,
        "plugin_wire_format_version": PLUGIN_WIRE_FORMAT_VERSION,
        "skill_wire_format_version": SKILL_WIRE_FORMAT_VERSION,
        "cli_wire_format_version": CLI_WIRE_FORMAT_VERSION,
        "mcp_wire_format_version": MCP_WIRE_FORMAT_VERSION,
    }


__all__ = [
    "CLI_WIRE_FORMAT_VERSION",
    "MCP_WIRE_FORMAT_VERSION",
    "PLUGIN_WIRE_FORMAT_VERSION",
    "SKILL_WIRE_FORMAT_VERSION",
    "WIRE_FORMAT_VERSION",
    "runtime_version_payload",
]
