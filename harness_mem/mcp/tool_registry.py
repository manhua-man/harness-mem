"""MCP public tool registry helpers."""

from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from harness_mem.mcp.tool_specs import (
    PUBLIC_MCP_TOOL_NAMES,
    ToolSpec,
    VALID_TOOL_PROFILES,
)

McpToolProfile = Literal["memory"]


class McpToolProfileResolution(TypedDict):
    profile: McpToolProfile
    source: str
    project_name: str | None
    degraded_reason: str | None


def normalize_mcp_tool_profile(value: object) -> McpToolProfile | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_TOOL_PROFILES:
        return cast(McpToolProfile, profile)
    return None


def _requested_profile(params: dict[str, Any]) -> object | None:
    requested = params.get("mcp_tool_profile") or params.get("profile")
    if not requested and isinstance(params.get("arguments"), dict):
        requested = params["arguments"].get("mcp_tool_profile")
    return requested


def _project_name(params: dict[str, Any]) -> str | None:
    project_name = params.get("project_name")
    if not project_name and isinstance(params.get("arguments"), dict):
        project_name = params["arguments"].get("project_name")
    if isinstance(project_name, str) and project_name.strip():
        return project_name.strip()
    return None


def resolve_mcp_tool_profile(params: dict[str, Any]) -> McpToolProfileResolution:
    requested = _requested_profile(params)
    return {
        "profile": "memory",
        "source": "single-public-surface",
        "project_name": _project_name(params),
        "degraded_reason": (
            "profile_ignored_single_public_surface" if requested else None
        ),
    }


def visible_tool_names(tools: dict[str, ToolSpec], profile: str) -> list[str]:
    return [name for name in tools if name in PUBLIC_MCP_TOOL_NAMES]


def visible_tool_name_set(tools: dict[str, ToolSpec], profile: str) -> set[str]:
    return set(tools).intersection(PUBLIC_MCP_TOOL_NAMES)


def tool_descriptor(name: str, spec: ToolSpec, profile: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
        "annotations": {
            "harness_mem": {
                "cluster": spec["cluster"],
                "surface": "memory",
                "listed_in_public_surface": name
                in visible_tool_name_set({name: spec}, profile),
            }
        },
    }


def list_tools_result(
    tools: dict[str, ToolSpec],
    profile_info: McpToolProfileResolution,
) -> dict[str, Any]:
    profile = profile_info["profile"]
    visible_names = visible_tool_names(tools, profile)
    return {
        "profile": profile,
        "profile_source": profile_info["source"],
        "profile_project_name": profile_info["project_name"],
        "degraded_reason": profile_info["degraded_reason"],
        "tool_count": len(visible_names),
        "total_tool_count": len(tools),
        "hidden_tool_count": len(tools) - len(visible_names),
        "tools": [
            tool_descriptor(name, tools[name], profile)
            for name in visible_names
        ],
    }


def hidden_tool_error(req_id: Any, tool_name: str, profile: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Tool is outside the public MCP memory surface: {tool_name}",
            "data": {
                "error_code": "HM-MCP-TOOL-HIDDEN",
                "profile": "memory",
                "tool_name": tool_name,
                "hint": (
                    "Use the public MCP surface for memory read, distill, "
                    "candidate review, and dream. Operator maintenance and "
                    "skill lifecycle management are not public MCP tools."
                ),
            },
        },
    }
