"""Public search and retrieval-feedback MCP handlers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from harness_mem.commands.support import get_active_project
from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.read_knowledge import search_current_knowledge

from .handler_facade_proxy import tool_handlers_facade as _core
from harness_mem.mcp.read_query_support import (
    _autopilot_dx_metadata,
    _new_retrieval_id,
    _record_search_quality_signals,
)
from harness_mem.mcp.read_projection import project_memory_entries
from harness_mem.mcp.read_feedback_handlers import (
    VALID_CONTEXT_OUTCOMES,
    tool_record_context_outcome as _tool_record_context_outcome,
)


def _get_backend():
    return _core._get_backend()


def tool_search_memory(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    _include_diagnostics: bool = False,
) -> dict:
    """Search only current project memory.

    Raw conversations and processing records have their own explicit tools and
    never enter this result, including its internal diagnostic projection.
    """
    backend = _get_backend()

    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    if scope == "project" and project_name:
        try:
            entries = asyncio.run(
                search_current_knowledge(
                    backend,
                    project_name=project_name,
                    query=query,
                )
            )
        except ValueError as error:
            return {
                "project_name": project_name,
                "query": query,
                "status": "unavailable",
                "memories": [],
                "reason": str(error),
            }
        retrieval_id = _new_retrieval_id()
        receipt = asyncio.run(
            _record_search_quality_signals(
                backend,
                project_name=project_name,
                query=query,
                entries=entries,
                response=SimpleNamespace(results=entries),
                context_plan=None,
                historical_excluded=0,
                retrieval_id=retrieval_id,
            )
        )
        memories = project_memory_entries(entries)
        payload = {
            "project_name": project_name,
            "query": query,
            "status": "answered" if entries else "empty",
            "memories": memories,
        }
        if not _include_diagnostics:
            return payload

        source_ids = list(receipt.get("source_ids") or [])
        truth = [
            {
                "source_id": entry.id,
                "reason": "current project knowledge matched the query",
                "summary": f"{memory['title']}: {memory['statement']}",
            }
            for entry, memory in zip(entries, memories, strict=True)
        ]
        return {
            **payload,
            "retrieval_id": retrieval_id,
            "retrieval_receipt": receipt,
            "memory_count": len(memories),
            "context_plan": {
                "project_name": project_name,
                "query": query,
                "source_ids": source_ids,
            },
            "answer_ready_context": {
                "project_name": project_name,
                "query": query,
                "current_task": None,
                "safe_to_answer": bool(memories),
                "sufficiency_status": "sufficient" if memories else "empty",
                "support_level": "current_truth" if memories else "none",
                "orchestration_actions": ["current_knowledge_search"],
                "project_profile": [],
                "truth": truth,
                "active_task": [],
                "topic_recall": [],
                "supporting_evidence": [],
                "caveats": [],
                "recommended_action": [],
                "drilldown_hints": [],
            },
            "supporting_evidence": [],
            "drilldown_hints": [],
            "record_outcome_call": (
                {
                    "tool": "record_context_outcome",
                    "arguments": {
                        "project_name": project_name,
                        "surface": "search_memory",
                        "source_ids": source_ids,
                        "retrieval_id": retrieval_id,
                    },
                    "required_argument": "outcome",
                    "allowed_outcomes": sorted(VALID_CONTEXT_OUTCOMES),
                }
                if source_ids
                else None
            ),
        }

    if scope == "all":
        entries = []
        entries_by_project: dict[str, list[Any]] = {}
        for known_project in asyncio.run(
            backend.structured_store.knowledge_store.known_projects()
        ):
            try:
                project_entries = asyncio.run(
                    search_current_knowledge(
                        backend,
                        project_name=known_project,
                        query=query,
                    )
                )
            except ValueError:
                # A deleted or moved authority is unavailable, not permission
                # to fall back to legacy rows from canonical SQLite.
                continue
            entries_by_project[known_project] = project_entries
            entries.extend(project_entries)
        entries = sorted(
            entries,
            key=lambda entry: (entry.project_name, entry.title, entry.id),
        )
        surfaced_ids = {entry.id for entry in entries}
        retrieval_id = _new_retrieval_id()
        for known_project, project_entries in entries_by_project.items():
            surfaced = [entry for entry in project_entries if entry.id in surfaced_ids]
            if not surfaced:
                continue
            asyncio.run(
                _record_search_quality_signals(
                    backend,
                    project_name=known_project,
                    query=query,
                    entries=surfaced,
                    response=SimpleNamespace(results=surfaced),
                    context_plan=None,
                    retrieval_id=retrieval_id,
                    surface="search_all",
                )
            )
        return {
            "project_name": None,
            "query": query,
            "status": "answered" if entries else "empty",
            "memories": project_memory_entries(
                entries,
                include_project=True,
            ),
        }

    return {
        "success": False,
        "error": "scope must be project or all",
    }


def tool_autopilot_search_tick(
    event_name: str,
    project_name: str | None = None,
    current_task: str | None = None,
    user_prompt: str | None = None,
    messages: list[Any] | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_result: Any = None,
    is_error: bool = False,
    candidate_claims: list[str] | None = None,
    changed_files: list[str] | None = None,
    recent_queries: list[str] | None = None,
    budget_tokens: int = 1600,
) -> dict:
    """Decide whether an agent runtime event should trigger memory search.

    This is the host-neutral bridge for PI ``transformContext`` /
    ``tool_result`` / save-point hooks, Claude Code ``PostToolUse`` hooks, and
    Cursor after-agent style hooks. It is not a session-start wake replacement.
    """

    resolved_project = project_name or get_active_project()
    decision = plan_autopilot_search(
        event_name=event_name,
        current_task=current_task,
        user_prompt=user_prompt,
        messages=messages,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_result=tool_result,
        is_error=is_error,
        candidate_claims=candidate_claims,
        changed_files=changed_files,
        recent_queries=recent_queries,
        budget_tokens=budget_tokens,
    )
    decision_payload = decision.to_dict()
    if not decision.should_search:
        return {
            "success": True,
            "project_name": resolved_project,
            "search_executed": False,
            "decision": decision_payload,
            "context_injection": None,
            **_autopilot_dx_metadata(
                should_search=False,
                trigger=decision.trigger,
                search_executed=False,
            ),
        }
    if not resolved_project:
        return {
            "success": False,
            "project_name": None,
            "search_executed": False,
            "decision": decision_payload,
            "context_injection": None,
            **_autopilot_dx_metadata(
                should_search=True,
                trigger=decision.trigger,
                search_executed=False,
                missing_project=True,
            ),
        }

    search_payload = tool_search_memory(
        query=decision.query or "",
        project_name=resolved_project,
        scope="project",
        _include_diagnostics=True,
    )
    source_ids = [
        source_id
        for source_id in search_payload.get("context_plan", {}).get("source_ids", [])
        if isinstance(source_id, str)
    ]
    search_outcome_call = dict(search_payload.get("record_outcome_call") or {})
    search_outcome_arguments = dict(search_outcome_call.get("arguments") or {})
    if search_outcome_arguments:
        search_outcome_arguments["surface"] = "autopilot_search_tick"
        search_outcome_call["arguments"] = search_outcome_arguments
    context_injection = {
        "target": decision.injection_target,
        "trigger": decision.trigger,
        "query": decision.query,
        "source_ids": source_ids,
        "answer_ready_context": search_payload.get("answer_ready_context"),
        "context_plan": search_payload.get("context_plan"),
        "supporting_evidence": search_payload.get("supporting_evidence", []),
        "drilldown_hints": search_payload.get("drilldown_hints", []),
        "retrieval_id": search_payload.get("retrieval_id"),
        "record_outcome_call": search_outcome_call or None,
    }
    return {
        "success": True,
        "project_name": resolved_project,
        "search_executed": True,
        "decision": decision_payload,
        "search": search_payload,
        "context_injection": context_injection,
        **_autopilot_dx_metadata(
            should_search=True,
            trigger=decision.trigger,
            search_executed=True,
        ),
    }


def tool_record_context_outcome(
    project_name: str,
    surface: str,
    outcome: str,
    source_ids: list[str] | None = None,
    reason: str | None = None,
    retrieval_id: str | None = None,
) -> dict:
    """Compatibility entry preserving this module's injected backend seam."""

    return _tool_record_context_outcome(
        project_name=project_name,
        surface=surface,
        outcome=outcome,
        source_ids=source_ids,
        reason=reason,
        retrieval_id=retrieval_id,
        _backend=_get_backend(),
    )
