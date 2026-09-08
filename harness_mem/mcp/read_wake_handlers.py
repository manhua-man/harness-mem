"""Wake orchestration MCP handler."""

from __future__ import annotations

import asyncio

from harness_mem.commands.support import get_active_project
from harness_mem.commands.wake import _build_distill_maintenance_offer
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge
from harness_mem.mcp.read_projection import project_memory_entries

from .handler_facade_proxy import tool_handlers_facade as _core
from .read_query_support import _action


def _get_backend():
    return _core._get_backend()


def tool_wake(
    project_name: str | None = None,
    current_task: str | None = None,
) -> dict:
    """Return current project knowledge and whether maintenance is waiting."""
    resolved = project_name or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            "why_this_result": "Wake cannot resolve a project without project_name or an active project.",
            "next_actions": [
                _action(
                    "resolve_project_context",
                    "get_project_status",
                    "Open the intended workspace so wake/search/status can resolve project-scoped memory.",
                )
            ],
            "degraded_reason": "missing_project",
            "drilldown_hints": [],
        }
    backend = _get_backend()
    if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
        return {
            "success": False,
            "project_name": resolved,
            "message": "Project memory storage is not ready.",
            "action": "Run harness-mem doctor.",
        }
    try:
        current_entries = asyncio.run(
            search_current_knowledge(
                backend,
                project_name=resolved,
                query=current_task,
            )
            if current_task
            else list_current_knowledge(
                backend,
                project_name=resolved,
            )
        )
    except ValueError:
        current_entries = []
    maintenance = _build_distill_maintenance_offer(
        backend,
        resolved,
        record_offer=True,
    )
    return {
        "success": True,
        "project_name": resolved,
        "long_term_memory": project_memory_entries(current_entries),
        "active_context": [],
        "maintenance_available": bool(maintenance.get("agent_execution_required")),
    }
