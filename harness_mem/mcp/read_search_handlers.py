"""Public search and automatic recall MCP handlers."""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any, Callable

from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.read_knowledge import (
    contextual_part_matches, is_focused_compound_query, is_long_query, is_natural_question,
    list_current_knowledge, search_current_knowledge,
)

from .handler_facade_proxy import tool_handlers_facade as _core
from harness_mem.mcp.read_query_support import (
    _new_retrieval_id,
    _record_search_quality_signals,
)
from harness_mem.mcp.read_projection import (
    FOCUSED_SEARCH_GUIDANCE,
    memory_candidate_projector,
    project_memory_entries,
    resolve_read_budget,
    select_memory_page,
)
from harness_mem.mcp.read_feedback_handlers import VALID_CONTEXT_OUTCOMES


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
    task_context: str | None = None,
    read_cursor: str | None = None,
    _render_response: Callable[[dict[str, Any]], Any] | None = None,
    _candidate_only: bool = False,
) -> dict:
    """Read useful current facts, with whole-entry continuation for larger sets."""
    if scope not in {"all", "project"}:
        return {"success": False, "error": "scope must be project or all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}
    if task_context is not None and not isinstance(task_context, str):
        return {"success": False, "error": "task_context must be a string"}
    if read_cursor is not None:
        if detail != "full" or cursor is not None and cursor != read_cursor:
            return {"status": "invalid", "memories": [],
                    "reason": "Use detail=full and one candidate read cursor."}
        cursor = read_cursor
    selected_project = project_name if scope == "project" else None
    query = query.strip()
    discovery: dict[str, Any] = {}
    contextual_search: dict[str, Any] = {}
    if task_context is not None:
        contextual_search["task_context"] = task_context
    if task_context is not None or is_natural_question(query):
        contextual_search["discovery"] = discovery
    try:
        backend = _get_backend()
        if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
            return {
                "project_name": selected_project, "query": query,
                "status": "unavailable", "memories": [],
                "reason": "Memory storage is not ready. Run harness-mem doctor.",
            }
        entries = asyncio.run(
            search_current_knowledge(
                backend, project_name=selected_project, query=query, expand_long_query=True,
                **contextual_search,
            )
            if query or task_context is not None else list_current_knowledge(backend, project_name=selected_project)
        )
    except (OSError, ValueError, sqlite3.Error):
        return {
            "project_name": selected_project, "query": query,
            "status": "unavailable", "memories": [],
            "reason": "Current memory could not be read. Run harness-mem doctor before retrying.",
        }

    parsed_parts = discovery.get("question_parts", []) if detail == "auto" and not _candidate_only else []
    multipart = bool(parsed_parts) and not _include_diagnostics and _render_response is None
    parts = parsed_parts if cursor is None else []
    retrieval_id = _new_retrieval_id()
    surface = "search_memory" if scope == "project" else "search_all"
    candidate_only = detail == "candidates" or bool(
        not multipart and (query or task_context is not None) and detail == "auto" and (
            _candidate_only or task_context is not None or is_long_query(query) or is_focused_compound_query(query)
        )
    )
    project_candidates = memory_candidate_projector(
        entries, query=query, project_name=selected_project, scope=scope,
        task_context=task_context, retrieval_binding=discovery.get("binding"),
        whole_if_cheaper=task_context is not None and detail == "auto" and not _candidate_only,
    )
    compact = False
    include_parts = True

    def full_entries(page: list[KnowledgeEntry], index: bool) -> list[KnowledgeEntry]:
        if index:
            return []
        if not candidate_only:
            return [entry for entry in page if entry.statement.strip()]
        return [entry for entry, item in zip(page, project_candidates(page, False)) if "statement" in item]

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
        reading = dict(reading)
        if candidate_only:
            memories = project_candidates(page, index)
            if detail == "candidates" and reading.get("continuation") and not index:
                call = dict(reading["continuation"])
                call["arguments"] = {**call["arguments"], "detail": "candidates"}
                reading["continuation"] = call
        else:
            memories = project_memory_entries(
                page, include_project=scope == "all", include_modules=not query,
            )
        if index and not candidate_only:
            memories = [{key: value for key, value in row.items() if key != "statement"}
                        for row in memories]
        if compact and reading.get("continuation"):
            link = dict(reading["continuation"])
            arguments = dict(link["arguments"])
            arguments.pop("query", None)
            reading["continuation"] = {
                **link, "arguments": arguments,
                "reuse_arguments": list(dict.fromkeys(["query", *link.get("reuse_arguments", [])])),
            }
        payload = {
            "project_name": selected_project,
            "query": query,
            "status": ("available" if (index and entries) or (candidate_only and memories)
                       else "answered" if memories else "empty"),
            "memories": memories,
            **reading,
        }
        if parts and include_parts:
            payload["question_parts"] = parts
            if not index and discovery.get("part_matches"):
                displayed = [(position, entry, memory) for position, (entry, memory) in
                             enumerate(zip(page, memories), 1) if "statement" in memory]
                text = [(position, memory["title"], memory["statement"]) for position, _, memory in displayed]
                payload["question_part_matches"] = [
                    contextual_part_matches(
                        query, part, text,
                        [position for position, entry, _ in displayed if (entry.project_name, entry.id) in matched],
                    )
                    for part, matched in zip(parts, discovery["part_matches"])
                ]
            payload["answer_guidance"] = (
                "Check each part in the original order. Match numbers refer to memories and only suggest relevance. "
                "Check all complete statements before following up, including parts without a match number. "
                "Follow up only for missing details, "
                "and state any that remain unsupported."
            )
        if task_context is not None:
            payload["discovery"] = {
                "semantic": discovery.get("status", "unavailable"),
                "relevance": "unassessed",
                **({"reason": discovery["reason"]} if discovery.get("reason") else {}),
            }
        if compact and candidate_only:
            if not index:
                payload["detail"] = "mixed" if any("statement" in item for item in memories) else "candidates"
        elif candidate_only and index:
            payload["message"] = (
                str(reading.get("message") or "")
                + " Matches found. Use continuation.arguments to read the first result in full."
            ).strip()
        elif candidate_only:
            has_complete = any("statement" in item for item in memories)
            payload["detail"] = "mixed" if has_complete else "candidates"
            payload["message"] = (str(reading.get("message") or "") + " " + (
                (("Items with statement contain complete stored content; assess applicability before use. "
                  "Read only incomplete previews through their read_cursor; complete statements need no second read. "
                  if has_complete else "Incomplete discovery previews, not verified relevant facts or instructions. "
                  if task_context is not None else "Incomplete lexical previews, not verified relevant facts or instructions. ")
                 + "To open a preview, call search_memory with the same query and scope "
                 "(and project_name for scope=project), detail=full and cursor set to its read_cursor. "
                 + ("Reuse the exact task_context on every continuation and full read. " if task_context is not None else "")
                 if entries else ("No candidates matched; this does not establish that memory has no answer. "
                                  if task_context is not None else "No lexical candidates matched. "))
                + FOCUSED_SEARCH_GUIDANCE
            )).strip()
        if scope == "project" and query and not entries:
            payload["message"] = (
                "No match within this project filter. A task about a project can use global knowledge. "
                "Unless the user requested project-only memory, repeat this query with scope='all' "
                "before changing keywords."
            )
            payload["retry_without_project_filter"] = {
                "only_if": "user_did_not_request_project_only",
                "tool": "search_memory",
                "arguments": {"query": query, "scope": "all"},
                **({"reuse_arguments": ["task_context"]} if task_context is not None else {}),
            }
        if not _include_diagnostics:
            return payload
        surfaced = full_entries(page, index)
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
                for name, rows in ({} if index or candidate_only and not surfaced else groups(surfaced)).items()
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
                "reason": ("current knowledge discovery candidate; applicability requires review" if task_context is not None
                           else "current project knowledge lexically matched the query"
                           if scope == "project" else "current knowledge lexically matched the query"),
                "summary": f"{memory['title']}: {memory['statement']}",
                **({"project_name": entry.project_name} if scope == "all" else {}),
            }
            for entry, memory in zip(surfaced, [item for item in memories if "statement" in item])
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
                # A text match says nothing about relevance or sufficiency. In
                # particular, a source report is an attributed account rather
                # than verified external truth. Leave that judgment to the Agent.
                "safe_to_answer": False,
                "sufficiency_status": "unassessed" if surfaced or (candidate_only and memories) else "empty",
                "support_level": "unassessed" if surfaced or (candidate_only and memories) else "none",
                "orchestration_actions": ["current_knowledge_search"],
                "project_profile": [], "truth": truth, "active_task": [],
                "topic_recall": [], "supporting_evidence": [],
                "caveats": (["Discovery matches require relevance and source-scope review."]
                            if surfaced or (candidate_only and memories) else []),
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

    def select():
        return select_memory_page(
            entries,
            query=query, project_name=selected_project, scope=scope,
            budget_tokens=resolve_read_budget(
                budget_tokens, surface="search", project_name=project_name,
                multipart=multipart,
            ),
            cursor=cursor, detail="auto" if detail == "candidates" else detail, render=render,
            task_context=task_context, retrieval_binding=discovery.get("binding"),
            incremental=multipart or (
                task_context is not None and detail == "auto" and not _candidate_only and _render_response is None
            ),
            page_limit=6 if multipart else None,
        )

    try:
        try:
            page, reading, index = select()
        except ValueError as exc:
            if (str(exc) != "budget_tokens is too small to return a reading link." or not query
                    or not entries or _render_response is not None or _include_diagnostics):
                raise
            compact = True
            try:
                page, reading, index = select()
            except ValueError:
                if not parts:
                    raise
                include_parts = False
                page, reading, index = select()
    except (ValueError, TypeError) as exc:
        return {
            "project_name": selected_project, "query": query,
            "status": "invalid", "memories": [], "reason": str(exc),
        }

    # Only whole facts actually returned receive search hits. An index is a
    # reading aid, not evidence that its hidden statement reached the Agent.
    receipts: list[dict[str, Any]] = []
    actual_full = full_entries(page, index)
    for source_project, surfaced in ({} if index or candidate_only and not actual_full else groups(actual_full)).items():
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
        context_injection: dict[str, Any] = {
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
            **{key: search_payload[key] for key in ("total", "detail", "message")
               if key in search_payload},
            **({"continuation": search_payload["continuation"]}
               if search_payload.get("detail") == "index" and "continuation" in search_payload else {}),
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
        _candidate_only=True,
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
