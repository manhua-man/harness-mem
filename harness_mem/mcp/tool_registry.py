"""MCP public tool registry helpers."""

from __future__ import annotations

import os
from typing import Any, Literal, TypedDict

from harness_mem.mcp.tool_specs import (
    MAINTENANCE_MCP_TOOL_NAMES,
    PUBLIC_MCP_TOOL_NAMES,
    ToolSpec,
)

McpToolProfile = Literal["memory", "maintenance"]
PUBLIC_MCP_SURFACE: McpToolProfile = "memory"
MAINTENANCE_PROFILE_ENV = "HARNESS_MEM_MCP_MAINTENANCE"


class McpSurfaceResolution(TypedDict):
    surface: McpToolProfile
    source: str
    degraded_reason: str | None


def maintenance_profile_enabled() -> bool:
    return os.getenv(MAINTENANCE_PROFILE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _requested_profile(params: dict[str, Any]) -> str | None:
    requested = params.get("profile") or params.get("mcp_tool_profile")
    if not requested and isinstance(params.get("arguments"), dict):
        requested = params["arguments"].get("profile") or params["arguments"].get(
            "mcp_tool_profile"
        )
    if isinstance(requested, str) and requested.strip():
        return requested.strip().lower()
    return None


def resolve_mcp_surface(params: dict[str, Any]) -> McpSurfaceResolution:
    requested = _requested_profile(params)
    if requested == "maintenance":
        if maintenance_profile_enabled():
            return {
                "surface": "maintenance",
                "source": "maintenance-env",
                "degraded_reason": None,
            }
        return {
            "surface": PUBLIC_MCP_SURFACE,
            "source": "public",
            "degraded_reason": "maintenance_profile_disabled",
        }
    return {
        "surface": PUBLIC_MCP_SURFACE,
        "source": "public",
        "degraded_reason": (
            "profile_ignored_single_public_surface"
            if requested and requested != PUBLIC_MCP_SURFACE
            else None
        ),
    }


def visible_tool_name_set(tools: dict[str, ToolSpec], surface: str) -> set[str]:
    if surface == "maintenance":
        return set(tools).intersection(MAINTENANCE_MCP_TOOL_NAMES)
    return set(tools).intersection(PUBLIC_MCP_TOOL_NAMES)


def visible_tool_names(tools: dict[str, ToolSpec], surface: str) -> list[str]:
    visible = visible_tool_name_set(tools, surface)
    return [name for name in tools if name in visible]


def tool_descriptor(name: str, spec: ToolSpec, surface: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
        "annotations": {
            "harness_mem": {
                "cluster": spec["cluster"],
                "surface": surface,
                "listed_in_surface": True,
            }
        },
    }


def list_tools_result(
    tools: dict[str, ToolSpec],
    surface_info: McpSurfaceResolution | None = None,
) -> dict[str, Any]:
    surface_info = surface_info or {
        "surface": PUBLIC_MCP_SURFACE,
        "source": "public",
        "degraded_reason": None,
    }
    surface = surface_info["surface"]
    visible_names = visible_tool_names(tools, surface)
    result: dict[str, Any] = {
        "surface": surface,
        "tool_count": len(visible_names),
        "tools": [
            tool_descriptor(name, tools[name], surface)
            for name in visible_names
        ],
    }
    if surface == "maintenance" or surface_info["degraded_reason"] is not None:
        result["surface_source"] = surface_info["source"]
        result["degraded_reason"] = surface_info["degraded_reason"]
    return result
