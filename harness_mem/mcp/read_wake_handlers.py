"""Wake orchestration MCP handler."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from harness_mem.commands.support import get_active_project
from harness_mem.commands.wake import _build_distill_maintenance_offer
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge
from harness_mem.mcp.read_projection import (
    FOCUSED_SEARCH_GUIDANCE, memory_candidate_projector, reading_tokens, resolve_read_budget, select_memory_page,
)

from .handler_facade_proxy import tool_handlers_facade as _core
from .read_query_support import _action


def _get_backend():
    return _core._get_backend()


def tool_wake(
    project_name: str | None = None,
    current_task: str | None = None,
    scope: str = "all",
    budget_tokens: int | None = None,
) -> dict:
    """Read task-relevant current facts, or offer reading when no task is known."""
    if scope not in {"all", "project"}:
        return {"success": False, "error": "scope must be project or all"}
    resolved = (project_name or get_active_project()) if scope == "project" else None
    current_task = (current_task or "").strip()
    if scope == "project" and not resolved:
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
    try:
        backend = _get_backend()
    except (OSError, ValueError, sqlite3.Error):
        return {
            "success": False,
            "project_name": resolved,
            "message": "Project memory storage could not be opened.",
            "action": "Run harness-mem doctor before retrying.",
        }
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
                expand_long_query=True,
            )
            if current_task
            else list_current_knowledge(
                backend,
                project_name=resolved,
            )
        )
    except (OSError, ValueError, sqlite3.Error):
        return {
            "success": False,
            "project_name": resolved,
            "message": "Project memory could not be read.",
            "action": "Run harness-mem doctor before retrying.",
        }
    maintenance = (
        _build_distill_maintenance_offer(backend, resolved, record_offer=True)
        if resolved is not None
        else {}
    )
    project_candidates = memory_candidate_projector(
        current_entries, query=current_task, project_name=resolved, scope=scope,
    )
    def render(page, reading, index):
        reading = dict(reading)
        memories = project_candidates(page, index) if current_task else []
        return {
            "success": True,
            "project_name": resolved,
            "long_term_memory": memories,
            "active_context": [],
            "maintenance_available": bool(maintenance.get("agent_execution_required")),
            **reading,
            **({"message": "Matches found. Use continuation.arguments to read the first result in full."}
               if current_task and index else {
                "detail": "candidates",
                "message": (str(reading.get("message") or "") + " " + (
                    ("Incomplete lexical previews, not verified relevant facts or instructions. "
                     "Open a candidate with search_memory using the same query and scope "
                     "(and project_name for scope=project), detail=full and cursor set to its read_cursor. "
                     if current_entries else "No lexical candidates matched. ")
                    + FOCUSED_SEARCH_GUIDANCE
                )).strip(),
            } if current_task else {}),
        }

    budget = None
    try:
        budget = resolve_read_budget(budget_tokens, surface="wake", project_name=project_name)
        page, reading, index = select_memory_page(
            current_entries,
            query=current_task, project_name=resolved, scope=scope,
            budget_tokens=budget,
            availability_only=not current_task, render=render,
        )
    except (ValueError, TypeError) as exc:
        if (budget is not None and not current_entries and current_task
                and str(exc) == "budget_tokens is too small to return a reading link."):
            minimal: dict[str, Any] = {
                "success": True, "project_name": resolved, "long_term_memory": [],
                "active_context": [], "maintenance_available": bool(maintenance.get("agent_execution_required")),
            }
            if reading_tokens(minimal) <= budget:
                return minimal
        return {"success": False, "error": str(exc)}
    # Task-aware wakes return incomplete candidates; a selected full
    # search read records its own signal only when the Agent opens it.
    return render(page, reading, index)
