"""Version and compatibility constants for runtime surfaces."""

from __future__ import annotations

from harness_mem import __version__

WIRE_FORMAT_VERSION = "hm-wire-v3.5"
PLUGIN_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
SKILL_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
CLI_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION
MCP_WIRE_FORMAT_VERSION = WIRE_FORMAT_VERSION

# Legacy JSON storage reader lifecycle. Removal requires both the version and
# calendar gates, plus the data/readiness gates documented by Doctor.
LEGACY_STORAGE_DEPRECATED_SINCE = "0.9.6"
LEGACY_STORAGE_DEPRECATED_ON = "2026-07-30"
LEGACY_STORAGE_SUPPORTED_THROUGH = "0.9.x"
LEGACY_STORAGE_REMOVAL_EARLIEST_VERSION = "1.0.0"
LEGACY_STORAGE_REMOVAL_EARLIEST_DATE = "2027-01-31"


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


def legacy_storage_support_policy() -> dict[str, str]:
    """Return the release policy for legacy JSON storage readers."""

    return {
        "deprecated_since": LEGACY_STORAGE_DEPRECATED_SINCE,
        "deprecated_on": LEGACY_STORAGE_DEPRECATED_ON,
        "supported_through": LEGACY_STORAGE_SUPPORTED_THROUGH,
        "earliest_removal_version": LEGACY_STORAGE_REMOVAL_EARLIEST_VERSION,
        "earliest_removal_date": LEGACY_STORAGE_REMOVAL_EARLIEST_DATE,
    }


__all__ = [
    "CLI_WIRE_FORMAT_VERSION",
    "MCP_WIRE_FORMAT_VERSION",
    "LEGACY_STORAGE_DEPRECATED_ON",
    "LEGACY_STORAGE_DEPRECATED_SINCE",
    "LEGACY_STORAGE_REMOVAL_EARLIEST_DATE",
    "LEGACY_STORAGE_REMOVAL_EARLIEST_VERSION",
    "LEGACY_STORAGE_SUPPORTED_THROUGH",
    "PLUGIN_WIRE_FORMAT_VERSION",
    "SKILL_WIRE_FORMAT_VERSION",
    "WIRE_FORMAT_VERSION",
    "legacy_storage_support_policy",
    "runtime_version_payload",
]
