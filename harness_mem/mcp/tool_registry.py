"""MCP public tool registry helpers."""

from __future__ import annotations

from typing import Any, Literal

from harness_mem.mcp.tool_specs import (
    PUBLIC_MCP_TOOL_NAMES,
    ToolSpec,
)

McpToolProfile = Literal["memory"]
PUBLIC_MCP_SURFACE: McpToolProfile = "memory"


def visible_tool_names(tools: dict[str, ToolSpec]) -> list[str]:
    return [name for name in tools if name in PUBLIC_MCP_TOOL_NAMES]


def visible_tool_name_set(tools: dict[str, ToolSpec]) -> set[str]:
    return set(tools).intersection(PUBLIC_MCP_TOOL_NAMES)


def tool_descriptor(name: str, spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
        "annotations": {
            "harness_mem": {
                "cluster": spec["cluster"],
                "surface": PUBLIC_MCP_SURFACE,
                "listed_in_surface": name in visible_tool_name_set({name: spec}),
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


def hidden_tool_error(req_id: Any, tool_name: str) -> dict[str, Any]:
    message = f"Tool is outside the public MCP memory surface: {tool_name}"
    hint = (
        "Use the public MCP surface for memory read, distill, candidate "
        "review, and dream. Operator maintenance and skill lifecycle "
        "management are not public MCP tools."
    )
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": message,
            "data": {
                "error_code": "HM-MCP-TOOL-HIDDEN",
                "surface": PUBLIC_MCP_SURFACE,
                "tool_name": tool_name,
                "hint": hint,
            },
        },
    }
