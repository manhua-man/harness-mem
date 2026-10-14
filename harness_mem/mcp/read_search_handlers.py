"""Public search and retrieval-feedback MCP handlers."""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any, Callable

from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge

from .handler_facade_proxy import tool_handlers_facade as _core
from harness_mem.mcp.read_query_support import (
    _new_retrieval_id,
    _record_search_quality_signals,
)
from harness_mem.mcp.read_projection import (
    project_memory_entries,
    resolve_read_budget,
    select_memory_page,
)
from harness_mem.mcp.read_feedback_handlers import (
    VALID_CONTEXT_OUTCOMES,
    tool_record_context_outcome as _tool_record_context_outcome,
)


def _get_backend():
    return _core._get_backend()


def tool_search_memory(
    query: str,
    project_name: str | None = None,
    scope: str = "all",
    _include_diagnostics: bool = False,
    budget_tokens: int | None = None,
    cursor: str | None = None,
    detail: str = "auto",
    _render_response: Callable[[dict[str, Any]], Any] | None = None,
) -> dict:
    """Read useful current facts, with whole-entry continuation for larger sets."""
    if scope not in {"all", "project"}:
        return {"success": False, "error": "scope must be project or all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}
    selected_project = project_name if scope == "project" else None
    query = query.strip()
    try:
        backend = _get_backend()
        if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
            return {
                "project_name": selected_project, "query": query,
                "status": "unavailable", "memories": [],
                "reason": "Memory storage is not ready. Run harness-mem doctor.",
            }
        entries = asyncio.run(
            search_current_knowledge(backend, project_name=selected_project, query=query)
            if query else list_current_knowledge(backend, project_name=selected_project)
        )
    except (OSError, ValueError, sqlite3.Error):
        return {
            "project_name": selected_project, "query": query,
            "status": "unavailable", "memories": [],
            "reason": "Current memory could not be read. Run harness-mem doctor before retrying.",
        }

    retrieval_id = _new_retrieval_id()
    surface = "search_memory" if scope == "project" else "search_all"

    def groups(surfaced: list[KnowledgeEntry]) -> dict[str, list[KnowledgeEntry]]:
        grouped: dict[str, list[KnowledgeEntry]] = {}
        for entry in surfaced:
            grouped.setdefault(entry.project_name, []).append(entry)
        if selected_project is not None:
            grouped.setdefault(selected_project, [])
        return grouped

    def build_payload(
        page: list[KnowledgeEntry],
        reading: dict[str, Any],
        index: bool,
        receipts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        memories = project_memory_entries(
            page, include_project=scope == "all", include_modules=not query,
        )
        if index:
            memories = [{key: value for key, value in row.items() if key != "statement"}
                        for row in memories]
        payload = {
            "project_name": selected_project,
            "query": query,
            "status": "available" if index else "answered" if memories else "empty",
            "memories": memories,
            **reading,
        }
        if scope == "project" and query and not entries:
            payload["message"] = (
                "No match within this project filter. A task about a project can use global knowledge. "
                "Unless the user requested project-only memory, repeat this query with scope='all' "
                "before changing keywords."
            )
        if not _include_diagnostics:
            return payload
        surfaced = [] if index else page
        if receipts is None:
            # Size selection precedes writes. Model the longest receipt state
            # with every source retained; real write failures only remove refs.
            receipts = [
                {
                    "project_name": name,
                    "contract_version": "retrieval-signal-receipt-v1",
                    "retrieval_id": retrieval_id, "surface": surface,
                    "attempted": max(1, len(rows)), "recorded": max(1, len(rows)),
                    "failed": max(1, len(rows)), "state": "degraded",
                    "source_ids": sorted({row.id for row in rows}),
                    "content_recorded": False,
                }
                for name, rows in ({} if index else groups(surfaced)).items()
            ]
        source_ids = sorted({source_id for item in receipts for source_id in item["source_ids"]})
        outcome_calls = [
            {
                "tool": "record_context_outcome",
                "arguments": {
                    "project_name": item["project_name"], "surface": surface,
                    "source_ids": item["source_ids"], "retrieval_id": retrieval_id,
                },
                "required_argument": "outcome",
                "allowed_outcomes": sorted(VALID_CONTEXT_OUTCOMES),
            }
            for item in receipts if item["source_ids"]
        ]
        failed = sum(item["failed"] for item in receipts)
        receipt = {
            "contract_version": "retrieval-signal-receipt-v1",
            "retrieval_id": retrieval_id, "surface": surface,
            "attempted": sum(item["attempted"] for item in receipts),
            "recorded": sum(item["recorded"] for item in receipts),
            "failed": failed, "state": "degraded" if failed else "ok",
            "source_ids": source_ids, "content_recorded": False,
        }
        truth = [
            {
                "source_id": entry.id,
                "reason": ("current project knowledge matched the query"
                           if scope == "project" else "current knowledge matched the query"),
                "summary": f"{memory['title']}: {memory['statement']}",
                **({"project_name": entry.project_name} if scope == "all" else {}),
            }
            for entry, memory in zip(surfaced, [] if index else memories)
        ]
        return {
            **payload,
            "retrieval_id": retrieval_id,
            "retrieval_receipt": receipt,
            "memory_count": len(surfaced),
            "context_plan": {
                "project_name": selected_project, "query": query, "source_ids": source_ids,
            },
            "answer_ready_context": {
                "project_name": selected_project, "query": query, "current_task": None,
                "safe_to_answer": bool(surfaced),
                "sufficiency_status": "sufficient" if surfaced else "empty",
                "support_level": "current_truth" if surfaced else "none",
                "orchestration_actions": ["current_knowledge_search"],
                "project_profile": [], "truth": truth, "active_task": [],
                "topic_recall": [], "supporting_evidence": [], "caveats": [],
                "recommended_action": [], "drilldown_hints": [],
            },
            "supporting_evidence": [], "drilldown_hints": [],
            "record_outcome_call": outcome_calls[0] if len(outcome_calls) == 1 else None,
            **({"record_outcome_calls": outcome_calls, "retrieval_receipts": receipts}
               if scope == "all" else {}),
        }

    def render(page: list[KnowledgeEntry], reading: dict[str, Any], index: bool) -> Any:
        payload = build_payload(page, reading, index)
        return _render_response(payload) if _render_response else payload

    try:
        page, reading, index = select_memory_page(
            entries,
            query=query, project_name=selected_project, scope=scope,
            budget_tokens=resolve_read_budget(
                budget_tokens, surface="search", project_name=project_name,
            ),
            cursor=cursor, detail=detail, render=render,
        )
    except (ValueError, TypeError) as exc:
        return {
            "project_name": selected_project, "query": query,
            "status": "invalid", "memories": [], "reason": str(exc),
        }

    # Only whole facts actually returned receive search hits. An index is a
    # reading aid, not evidence that its hidden statement reached the Agent.
    receipts: list[dict[str, Any]] = []
    for source_project, surfaced in ({} if index else groups(page)).items():
        project_receipt = asyncio.run(
            _record_search_quality_signals(
                backend,
                project_name=source_project, query=query, entries=surfaced,
                response=SimpleNamespace(results=surfaced), context_plan=None,
                historical_excluded=0, retrieval_id=retrieval_id, surface=surface,
            )
        )
        receipts.append({"project_name": source_project, **project_receipt})
    return build_payload(page, reading, index, receipts)


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

    resolved_project = project_name
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
        }
    def render(search_payload: dict[str, Any]) -> dict[str, Any]:
        source_ids = [
            source_id
            for source_id in search_payload.get("context_plan", {}).get("source_ids", [])
            if isinstance(source_id, str)
        ]
        calls = search_payload.get("record_outcome_calls", [])
        receipt = search_payload.get("retrieval_receipt") or {}
        context_injection = {
            "target": decision.injection_target,
            "trigger": decision.trigger,
            "query": decision.query,
            "source_ids": source_ids,
            "status": search_payload["status"],
            "memories": search_payload["memories"],
            "retrieval_id": search_payload.get("retrieval_id"),
            "record_outcome_call": search_payload.get("record_outcome_call"),
            # A single call already carries its project and sources. Keep the
            # plural form only for multiple projects, and avoid repeating ids
            # and correlation fields inside a second full receipt.
            "record_outcome_calls": calls if len(calls) > 1 else [],
            "retrieval_receipt": {
                key: receipt[key] for key in ("state", "attempted", "recorded", "failed", "content_recorded")
                if key in receipt
            },
            **{key: search_payload[key] for key in ("total", "detail", "continuation", "message")
               if key in search_payload},
        }
        return {
            "success": True,
            "project_name": resolved_project,
            "search_executed": True,
            "decision": decision_payload,
            "context_injection": context_injection,
        }

    search_payload = tool_search_memory(
        query=decision.query or "", project_name=resolved_project, scope="all",
        _include_diagnostics=True, budget_tokens=budget_tokens, _render_response=render,
    )
    if search_payload.get("status") in {"unavailable", "invalid"} or search_payload.get("success") is False:
        return {
            "success": False,
            "project_name": resolved_project,
            "search_executed": True,
            "decision": decision_payload,
            "context_injection": None,
            "error": search_payload.get("reason") or search_payload.get("error"),
        }
    return render(search_payload)


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
