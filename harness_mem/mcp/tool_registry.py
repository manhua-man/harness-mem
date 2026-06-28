"""MCP public tool registry helpers."""

from __future__ import annotations

from typing import Any, Literal

from harness_mem.mcp.tool_specs import (
    ToolSpec,
)

McpToolProfile = Literal["memory"]
PUBLIC_MCP_SURFACE: McpToolProfile = "memory"


def visible_tool_names(tools: dict[str, ToolSpec]) -> list[str]:
    return list(tools)


def tool_descriptor(name: str, spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
        "annotations": {
            "harness_mem": {
                "cluster": spec["cluster"],
                "surface": PUBLIC_MCP_SURFACE,
                "listed_in_surface": True,
            }
        },
    }


def list_tools_result(tools: dict[str, ToolSpec]) -> dict[str, Any]:
    visible_names = visible_tool_names(tools)
    return {
        "surface": PUBLIC_MCP_SURFACE,
        "tool_count": len(visible_names),
        "tools": [
            tool_descriptor(name, tools[name])
            for name in visible_names
        ],
    }
