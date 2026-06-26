"""MCP tool profile and registry helpers."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal, TypedDict, cast

from harness_mem.mcp.tool_specs import (
    MINIMAL_TOOL_NAMES,
    PROFILE_TOOL_NAMES,
    ToolSpec,
    VALID_TOOL_PROFILES,
)
from harness_mem.commands.support import get_active_project
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

logger = logging.getLogger("harness_mem_mcp")

McpToolProfile = Literal[
    "core-read",
    "minimal",
    "distill-suggest",
    "review-write",
    "maintenance",
    "labs",
    "full",
]


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


def profile_project_name(params: dict[str, Any]) -> str | None:
    project_name = params.get("project_name")
    if not project_name and isinstance(params.get("arguments"), dict):
        project_name = params["arguments"].get("project_name")
    if isinstance(project_name, str) and project_name.strip():
        return project_name.strip()
    return get_active_project()


def project_profile_mcp_tool_profile(project_name: str | None) -> McpToolProfile | None:
    if not project_name:
        return None
    try:
        from harness_mem.commands import support as _support

        profile = asyncio.run(LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name))
    except Exception:
        logger.exception("Failed to read project MCP tool profile for %s", project_name)
        return None
    if profile is None:
        return None
    return normalize_mcp_tool_profile(profile.mcp_tool_profile)


def resolve_mcp_tool_profile(params: dict[str, Any]) -> McpToolProfileResolution:
    profile: McpToolProfile = "core-read"
    source = "default"
    degraded_reason = None

    requested_profile = params.get("mcp_tool_profile") or params.get("profile")
    if not requested_profile and isinstance(params.get("arguments"), dict):
        requested_profile = params["arguments"].get("mcp_tool_profile")
    if requested_profile:
        normalized = normalize_mcp_tool_profile(requested_profile)
        if normalized is None:
            degraded_reason = "invalid_requested_profile"
        else:
            profile = normalized
            source = "request"
            degraded_reason = None

    env_profile = os.environ.get("HARNESS_MEM_MCP_TOOL_PROFILE")
    if env_profile:
        normalized = normalize_mcp_tool_profile(env_profile)
        if normalized is None:
            degraded_reason = "invalid_env_profile"
        else:
            profile = normalized
            source = "env"

    project_name = profile_project_name(params)
    project_profile = project_profile_mcp_tool_profile(project_name)
    if project_profile is not None:
        profile = project_profile
        source = "project_profile"
        degraded_reason = None

    return {
        "profile": profile,
        "source": source,
        "project_name": project_name,
        "degraded_reason": degraded_reason,
    }


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
