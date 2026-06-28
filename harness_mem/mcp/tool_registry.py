"""MCP public tool registry helpers."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, ToolSpec

McpToolProfile = Literal["memory"]
PUBLIC_MCP_SURFACE: McpToolProfile = "memory"


class McpSurfaceResolution(TypedDict):
    surface: McpToolProfile
    source: str
    degraded_reason: str | None


def resolve_mcp_surface(_params: dict[str, Any]) -> McpSurfaceResolution:
    """Return the single public MCP memory surface.

    Historical profile parameters are intentionally ignored so MCP clients do not
    need to understand surface modes.
    """
    return {
        "surface": PUBLIC_MCP_SURFACE,
        "source": "public",
        "degraded_reason": None,
    }


def visible_tool_name_set(
    tools: dict[str, ToolSpec],
    _surface: str = PUBLIC_MCP_SURFACE,
) -> set[str]:
    return set(tools).intersection(PUBLIC_MCP_TOOL_NAMES)


def visible_tool_names(
    tools: dict[str, ToolSpec],
    surface: str = PUBLIC_MCP_SURFACE,
) -> list[str]:
    visible = visible_tool_name_set(tools, surface)
    return [name for name in tools if name in visible]


def tool_descriptor(
    name: str,
    spec: ToolSpec,
    surface: str = PUBLIC_MCP_SURFACE,
) -> dict[str, Any]:
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
    return {
        "surface": surface,
        "tool_count": len(visible_names),
        "tools": [
            tool_descriptor(name, tools[name], surface)
            for name in visible_names
        ],
    }
