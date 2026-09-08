"""Compatibility facade for split read-side MCP handlers."""

from __future__ import annotations

from harness_mem.mcp.read_query_support import _action  # noqa: F401
from harness_mem.mcp.read_search_handlers import (  # noqa: F401
    tool_autopilot_search_tick,
    tool_search_memory,
)
from harness_mem.mcp.read_feedback_handlers import tool_record_context_outcome  # noqa: F401
from harness_mem.mcp.read_evidence_handlers import (  # noqa: F401
    tool_file_context,
    tool_get_observations,
    tool_get_project_profile,
    tool_get_task_handoffs,
    tool_search_raw,
    tool_timeline,
)
from harness_mem.mcp.read_wake_handlers import tool_wake  # noqa: F401

__all__ = [
    "tool_autopilot_search_tick",
    "tool_file_context",
    "tool_get_observations",
    "tool_get_project_profile",
    "tool_get_task_handoffs",
    "tool_record_context_outcome",
    "tool_search_memory",
    "tool_search_raw",
    "tool_timeline",
    "tool_wake",
]
