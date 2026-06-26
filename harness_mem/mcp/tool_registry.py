"""MCP tool profile and registry helpers."""

from __future__ import annotations

from typing import Any, cast

from harness_mem.mcp.tool_specs import (
    MINIMAL_TOOL_NAMES,
    PROFILE_TOOL_NAMES,
    ToolSpec,
    VALID_TOOL_PROFILES,
)


def normalize_mcp_tool_profile(value: object) -> str | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_TOOL_PROFILES:
        return cast(str, profile)
    return None


def visible_tool_names(tools: dict[str, ToolSpec], profile: str) -> list[str]:
    if profile != "full":
        visible = PROFILE_TOOL_NAMES.get(profile, MINIMAL_TOOL_NAMES)
        return [name for name in tools if name in visible]
    return list(tools)


def visible_tool_name_set(tools: dict[str, ToolSpec], profile: str) -> set[str]:
    if profile == "full":
        return set(tools)
    return set(PROFILE_TOOL_NAMES.get(profile, MINIMAL_TOOL_NAMES))


def tool_descriptor(name: str, spec: ToolSpec, profile: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
        "annotations": {
            "harness_mem": {
                "cluster": spec["cluster"],
                "profile": profile,
                "listed_in_profile": name in visible_tool_name_set({name: spec}, profile),
            }
        },
    }


def hidden_tool_error(req_id: Any, tool_name: str, profile: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Tool hidden by MCP tool profile '{profile}': {tool_name}",
            "data": {
                "error_code": "HM-MCP-TOOL-HIDDEN",
                "profile": profile,
                "tool_name": tool_name,
                "hint": (
                    "Use an explicit MCP profile for this surface: "
                    "distill-suggest for candidate suggestion, review-write "
                    "for confirm/reject, maintenance/labs for opt-in tools, "
                    "or full for every registered tool."
                ),
            },
        },
    }
