"""Read, retrieval, context, and wake MCP handlers.

This module owns query interpretation and evidence-returning surfaces while
``tool_handlers`` retains dependency binding and the stable registry facade.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Literal, cast

from harness_mem.commands import support as _support
from harness_mem.commands.support import (
    get_active_project,
)
from harness_mem.commands.wake import (
    DEFAULT_SKILL_HINT_LIMIT,
    build_wake_snapshot,
    cmd_wake_up,
)
from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.file_context import build_file_context
from harness_mem.guided_flow import build_guided_flow, guided_flow_drilldown_hint
from harness_mem.read_api import (
    parse_relative_time_window,
    query_temporal_truth,
    regex_search_observations,
    search_skills,
    serialize_memory_entry_search_result,
    serialize_observation,
    serialize_observation_search_result,
    serialize_regex_observation_match,
    serialize_relation_fact_search_result,
    serialize_relation_path,
    serialize_skill,
    serialize_temporal_query_result,
    serialize_timeline_observation,
    timeline_observations,
    trace_relation_paths,
)
from harness_mem.recall import build_search_recall_result, build_trace_recall_result
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.task_context_runtime import orchestrate_task_context
from harness_mem.mcp.response_views import (
    status_triage_hints,
)

from .handler_facade_proxy import tool_handlers_facade as _core


def _get_backend():
    return _core._get_backend()


def _observer_data_dir():
    return _core._observer_data_dir()


def _cost_surface_budgets(project_name):
    return _core._cost_surface_budgets(project_name)


def _record_state_event(*args, **kwargs):
    return _core._record_state_event(*args, **kwargs)


def _run_command_to_payload(coro):
    return _core._run_command_to_payload(coro)


async def _gather_project_status(*args, **kwargs):
    return await _core._gather_project_status(*args, **kwargs)


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})
VALID_CONTEXT_OUTCOMES: frozenset[str] = frozenset({"used", "ignored", "misleading"})
CONTEXT_OUTCOME_VALUES: dict[str, float] = {
    "used": 1.0,
    "ignored": 0.0,
    "misleading": -1.0,
}
VALID_RETRIEVAL_PROFILES: frozenset[str] = frozenset({"light", "quality"})
RetrievalProfile = Literal["light", "quality"]


def _quality_signal_target(*parts: str | None) -> str:
    payload = "\x1f".join(part or "" for part in parts).encode("utf-8")
    return f"query:{hashlib.sha256(payload).hexdigest()[:16]}"


async def _record_search_quality_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    entries: list[Any],
    response: Any,
    context_plan: Any,
    historical_excluded: int = 0,
) -> None:
    """Write bounded, content-free shadow metrics for one search call."""

    for entry in entries:
        entry_id = str(getattr(entry, "id", "") or "")
        if not entry_id:
            continue
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=entry_id,
            context={"surface": "search_memory"},
        )

    if historical_excluded > 0:
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_excluded",
            target_kind="context_source",
            target_id=_quality_signal_target(project_name, query, "historical"),
            value=float(historical_excluded),
            context={"surface": "search_memory", "reason": "historical"},
        )

    reason: str | None = None
    if not list(getattr(response, "results", []) or []):
        reason = "no_evidence"
    elif context_plan is not None and not bool(
        getattr(context_plan.context_sufficiency, "safe_to_answer", False)
    ):
        reason = "insufficient_context"
    if reason is None:
        return
    await record_retrieval_signal(
        backend,
        project_name=project_name,
        signal_type="retrieval_abstained",
        target_kind="context_source",
        target_id=_quality_signal_target(project_name, query),
        value=1.0,
        context={
            "surface": "search_memory",
            "reason": reason,
            "result_count": len(list(getattr(response, "results", []) or [])),
        },
    )


async def _count_mainline_historical_exclusions(
    backend: LocalMemoryBackend,
    *,
    query: str,
    project_name: str,
    mode: str,
    memory_type: list[str] | None,
    include_provisional: bool,
    time_window: tuple[datetime | None, datetime | None] | None,
) -> int:
    """Count bounded history matches hidden by the current-only search default."""

    entries = await backend.structured_store.search_memory_entries(
        query,
        project_name=project_name,
        limit=100,
        mode=mode,
        memory_type=memory_type,
        include_history=True,
        deep_recall=True,
        time_window=time_window,
        include_provisional=include_provisional,
    )
    facts = await backend.structured_store.search_relation_facts(
        query,
        project_name=project_name,
        limit=100,
        include_history=True,
        time_window=time_window,
        include_provisional=include_provisional,
    )
    now = datetime.now(timezone.utc)

    def historical(item: Any) -> bool:
        if list(getattr(item, "superseded_by", []) or []):
            return True
        valid_to = getattr(item, "valid_to", None)
        if valid_to is None:
            return False
        if valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        return valid_to <= now

    return sum(historical(item) for item in [*entries, *facts])


async def _record_temporal_quality_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    result: Any,
    mode: str,
    identity_parts: tuple[str | None, ...],
) -> None:
    """Record temporal abstention/exclusion evidence without storing query text."""

    target_id = _quality_signal_target(project_name, *identity_parts)
    reason = str(getattr(result, "abstention_reason", "") or "")
    if bool(getattr(result, "abstain", False)):
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_abstained",
            target_kind="context_source",
            target_id=target_id,
            value=1.0,
            context={"surface": "temporal_query", "reason": reason or "no_evidence"},
        )

    timeline = tuple(getattr(result, "timeline", ()) or ())
    if reason == "temporal_conflict":
        conflict_count = sum(bool(getattr(record, "is_current", False)) for record in timeline)
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_excluded",
            target_kind="context_source",
            target_id=target_id,
            value=float(max(1, conflict_count)),
            context={"surface": "temporal_query", "reason": "temporal_conflict"},
        )

    if mode == "current":
        stale_count = sum(not bool(getattr(record, "is_current", False)) for record in timeline)
        if stale_count:
            await record_retrieval_signal(
                backend,
                project_name=project_name,
                signal_type="retrieval_excluded",
                target_kind="context_source",
                target_id=target_id,
                value=float(stale_count),
                context={"surface": "temporal_query", "reason": "historical"},
            )


def _action(label: str, surface: str, reason: str) -> dict[str, str]:
    return {"label": label, "surface": surface, "reason": reason}


def _autopilot_dx_metadata(
    *,
    should_search: bool,
    trigger: str | None,
    search_executed: bool,
    missing_project: bool = False,
) -> dict[str, Any]:
    if missing_project:
        return {
            "why_this_result": (
                "Autopilot detected a search-worthy event but no project was "
                "available. Open the intended workspace or pass project_name."
            ),
            "next_actions": [
                _action(
                    "resolve_project_context",
                    "get_project_status",
                    "Open the intended workspace so project context can be resolved before runtime ticks.",
                )
            ],
            "degraded_reason": "missing_project",
        }
    if search_executed:
        return {
            "why_this_result": (
                f"Autopilot search ran because trigger={trigger}; inject the "
                "returned answer_ready_context or context_plan into the next "
                "agent context."
            ),
            "next_actions": [
                _action(
                    "inject_next_context",
                    "answer_ready_context",
                    "Use bounded, source-attributed context in the next provider request.",
                ),
                _action(
                    "record_outcome",
                    "record_context_outcome",
                    "After the task, mark surfaced source ids used/ignored/misleading.",
                ),
            ],
            "degraded_reason": None,
        }
    return {
        "why_this_result": (
            "Autopilot search skipped this event because no concrete "
            "memory-backed uncertainty was detected."
            if not should_search
            else "Autopilot search was skipped by policy."
        ),
        "next_actions": [],
        "degraded_reason": None,
    }


_AS_OF_TERMS: tuple[str, ...] = (
    "as of",
    "at the time",
    "back then",
    "当时",
    "那时",
)
_HISTORY_TERMS: tuple[str, ...] = (
    "previous",
    "previously",
    "formerly",
    "legacy",
    "old",
    "history",
    "historical",
    "before",
    "以前",
    "之前",
    "历史",
    "过去",
    "旧",
)
_DATE_PATTERN = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?)?\b"
)


def _temporal_intent_mode(query: str | None) -> Literal["as_of", "history"] | None:
    normalized = (query or "").strip().lower()
    if not normalized:
        return None
    if any(term in normalized for term in _AS_OF_TERMS):
        return "as_of"
    if _DATE_PATTERN.search(normalized):
        return "as_of"
    if any(term in normalized for term in _HISTORY_TERMS):
        return "history"
    return None


def _extract_as_of_hint(query: str | None) -> str | None:
    match = _DATE_PATTERN.search(query or "")
    if not match:
        return None
    try:
        return (
            datetime.fromisoformat(match.group(1))
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        return None


def _temporal_query_action(mode: str) -> dict[str, str]:
    return _action(
        "inspect_temporal_truth",
        "temporal_query",
        (
            f"Query looks time-scoped; use temporal_query mode={mode} before "
            "treating old-state answers as current truth."
        ),
    )


def _temporal_intent_drilldown_hint(
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> dict[str, Any] | None:
    if mode is None:
        return None
    as_of = _extract_as_of_hint(query) if mode == "as_of" else None
    arguments: dict[str, Any] = {
        "project_name": project_name,
        "query": query,
        "mode": mode,
        "limit": 20,
    }
    if mode == "as_of":
        arguments["as_of"] = as_of
        arguments["requires_as_of"] = as_of is None
    return {
        "source_id": None,
        "source_kind": "temporal_intent",
        "read_surface": "mcp.temporal_query",
        "tool": "temporal_query",
        "arguments": arguments,
        "why": (
            "The query appears to ask about historical or as-of truth. "
            "Use temporal_query and preserve its abstention_reason if no evidence matches."
        ),
        "abstention": "no_evidence",
    }


def _with_temporal_intent_hint(
    hints: list[dict[str, Any]],
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> list[dict[str, Any]]:
    hint = _temporal_intent_drilldown_hint(
        project_name=project_name,
        query=query,
        mode=mode,
    )
    if hint is None:
        return list(hints)
    return [*hints, hint]


def _is_historical_truth(record: object) -> bool:
    valid_to = getattr(record, "valid_to", None)
    if not isinstance(valid_to, datetime):
        return False
    return valid_to <= datetime.now(timezone.utc)


def _is_superseded_truth(record: object) -> bool:
    return _is_historical_truth(record) and bool(
        list(getattr(record, "superseded_by", []) or [])
    )


def _normalize_retrieval_profile(value: object) -> RetrievalProfile | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_RETRIEVAL_PROFILES:
        return cast(RetrievalProfile, profile)
    return None


async def _resolve_retrieval_profile(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    requested: str | None,
) -> dict[str, Any]:
    if requested is not None:
        normalized = _normalize_retrieval_profile(requested)
        if normalized is None:
            valid = ", ".join(sorted(VALID_RETRIEVAL_PROFILES))
            return {
                "success": False,
                "error": f"retrieval_profile must be one of: {valid}",
            }
        return {
            "success": True,
            "active": normalized,
            "configured": None,
            "source": "argument",
        }

    configured: RetrievalProfile | None = None
    if project_name:
        from harness_mem.commands import support as _support

        profile = await LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(
            project_name
        )
        if profile is not None:
            configured = _normalize_retrieval_profile(profile.retrieval_profile)

    return {
        "success": True,
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
    }


def _retrieval_profile_status(
    *,
    active_profile: str | None,
    memory_entry_count: int,
) -> dict[str, Any]:
    configured = _normalize_retrieval_profile(active_profile)
    suggested = None if configured else ("quality" if memory_entry_count > 0 else None)
    return {
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
        "suggested": suggested,
        "available": [
            {
                "name": "light",
                "default": True,
                "reranker": "noop",
                "query_rewriting_enabled": False,
                "multi_query_enabled": False,
                "hyde_enabled": False,
                "summary": "Default lightweight retrieval path.",
            },
            {
                "name": "quality",
                "default": False,
                "reranker": "noop",
                "query_rewriting_enabled": True,
                "multi_query_enabled": True,
                "hyde_enabled": False,
                "summary": (
                    "Opt-in deterministic query rewrite/fanout trace; no "
                    "heavy reranker, HyDE, ANN, Tantivy, or LanceDB is enabled."
                ),
            },
        ],
        "auto_enabled": False,
        "default_profile": "light",
        "claim_boundary": (
            "retrieval_profile=quality is component-level retrieval behavior; "
            "it does not unlock broad_memory_answer_quality"
        ),
    }


def _search_dx_metadata(
    *,
    memory_entry_count: int,
    relation_fact_count: int,
    observation_count: int,
    effective_mode: str,
    fallback_reason: str | None,
    project_name: str | None,
    query: str,
    include_history: bool,
    deep_recall: bool,
    temporal_intent_mode: Literal["as_of", "history"] | None,
) -> dict[str, Any]:
    total = memory_entry_count + relation_fact_count + observation_count
    next_actions: list[dict[str, str]] = []
    if total == 0:
        next_actions.append(
            _action(
                "distill_recent_sessions",
                "/hm:distill",
                "No confirmed memory matched this query; run /hm:distill before relying on search.",
            )
        )
        next_actions.append(
            _action(
                "search_raw_evidence",
                "search_raw",
                "Use raw evidence search if you need exact transcript snippets before distill.",
            )
        )
    else:
        next_actions.append(
            _action(
                "inspect_sources",
                "drilldown_hints",
                "Use returned source ids and read surfaces when a result needs proof.",
            )
        )
        next_actions.append(
            _action(
                "record_outcome",
                "record_context_outcome",
                "After the task, record used/ignored/misleading so future opt-in ranking is explainable.",
            )
        )
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "harness-mem doctor",
                "Search degraded to a fallback path; inspect local runtime health before claiming quality.",
            )
        )
    if include_history or deep_recall:
        next_actions.append(
            _action(
                "inspect_temporal_chain",
                "temporal_query",
                "History-capable search was requested; use temporal_query for current/history/as_of proof.",
            )
        )
    elif temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))

    project_fragment = f" for {project_name}" if project_name else ""
    why = (
        f"Returned {memory_entry_count} memory entries, {relation_fact_count} "
        f"relation facts, and {observation_count} observations{project_fragment} "
        f"using {effective_mode} mode for query {query!r}."
    )
    if include_history:
        why += " Historical structured truth was included because include_history=true."
    elif deep_recall:
        why += " Historical structured truth may be included because deep_recall=true."
    elif temporal_intent_mode:
        why += " Query appears temporal; current results remain current-only unless history is requested."
    return {
        "why_this_result": why,
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


def _wake_dx_metadata(
    *,
    success: bool,
    fallback_reason: str | None,
    source_coverage: dict[str, int] | None,
    temporal_intent_mode: Literal["as_of", "history"] | None = None,
) -> dict[str, Any]:
    if not success:
        return {
            "why_this_result": "Wake did not complete, so no context packet was generated.",
            "next_actions": [
                _action(
                    "check_status",
                    "get_project_status",
                    "Status explains whether the project is missing ingest, review, or local setup.",
                )
            ],
            "degraded_reason": fallback_reason or "wake_failed",
            "drilldown_hints": [],
        }
    coverage = source_coverage or {}
    next_actions = [
        _action(
            "answer_with_sources",
            "supporting_evidence",
            "Use the returned evidence ids when the task needs proof.",
        ),
        _action(
            "search_specific_gap",
            "/hm:search",
            "If the wake packet is too broad, search for the exact subsystem or decision.",
        ),
    ]
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "harness-mem doctor",
                "Wake used a fallback search path; inspect local health before release claims.",
            )
        )
    if temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))
    return {
        "why_this_result": (
            "Generated wake context from project profile, rules, "
            f"handoffs, and task-aware retrieval; source coverage: {coverage}."
        ),
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


# Status decision metadata lives in response_views.py.


def tool_search_memory(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    mode: str = "auto",
    memory_type: list[str] | None = None,
    include_history: bool = False,
    include_provisional: bool = False,
    deep_recall: bool = False,
    retrieval_profile: str | None = None,
    task: str | None = None,
    budget_tokens: int = 6000,
) -> dict:
    """Search structured memory entries + verbatim observations.

    v1.6.1: ``memory_type`` is an optional list filter ({episodic, semantic,
    procedural}). Empty / None disables the filter; values are OR-ed.
    """
    backend = _get_backend()

    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    if memory_type:
        normalized = [str(value).strip().lower() for value in memory_type]
        invalid = [value for value in normalized if value not in VALID_MEMORY_TYPES]
        if invalid:
            return {
                "success": False,
                "error": (
                    "unknown memory_type: "
                    + ", ".join(sorted(set(invalid)))
                    + ". Valid: episodic | semantic | procedural."
                ),
            }
        memory_type = normalized
    else:
        memory_type = None

    profile_info = asyncio.run(
        _resolve_retrieval_profile(
            backend,
            project_name=project_name if scope == "project" else None,
            requested=retrieval_profile,
        )
    )
    if not profile_info["success"]:
        return profile_info

    parsed_time = parse_relative_time_window(query)
    runtime = asyncio.run(
        orchestrate_task_context(
            backend,
            query=parsed_time.query,
            project_name=project_name,
            scope=scope,
            mode=mode,
            memory_type=memory_type,
            include_history=include_history,
            include_provisional=include_provisional,
            time_window=parsed_time.time_window,
            deep_recall=deep_recall,
            current_task=task,
            budget_tokens=budget_tokens,
            auto_deep_recall=True,
            retrieval_profile=profile_info["active"],
        )
    )
    response = runtime.response
    entries = runtime.entries
    obs_list = runtime.observations
    relation_facts = runtime.relation_facts
    if scope == "project" and project_name:
        historical_excluded = 0
        if not include_history and not deep_recall:
            historical_excluded = asyncio.run(
                _count_mainline_historical_exclusions(
                    backend,
                    query=parsed_time.query,
                    project_name=project_name,
                    mode=mode,
                    memory_type=memory_type,
                    include_provisional=include_provisional,
                    time_window=parsed_time.time_window,
                )
            )
        asyncio.run(
            _record_search_quality_signals(
                backend,
                project_name=project_name,
                query=query,
                entries=entries,
                response=response,
                context_plan=runtime.context_plan,
                historical_excluded=historical_excluded,
            )
        )
    tech_stack_by_project = runtime.tech_stack_by_project
    effective_mode = response.effective_mode
    fallback_reason = response.fallback_metadata.get("fallback_reason")
    temporal_intent = _temporal_intent_mode(query)
    drilldown_hints = _with_temporal_intent_hint(
        response.drilldown_hints,
        project_name=project_name,
        query=query,
        mode=temporal_intent,
    )
    context_payload: dict[str, Any] = {}
    if runtime.context_plan is not None:
        context_plan = runtime.context_plan
        context_plan_payload = context_plan.to_dict()
        context_plan_payload["drilldown_hints"] = drilldown_hints
        context_plan_payload["iterative_retrieval_trace"]["retrieval_quality"] = (
            response.retrieval_quality
        )
        context_payload = {
            "context_sufficiency": context_plan.context_sufficiency.to_dict(),
            "retrieval_plan": context_plan.retrieval_plan.to_dict(),
            "context_plan": context_plan_payload,
            "iterative_retrieval_trace": (
                context_plan.iterative_retrieval_trace.to_dict()
            ),
            "wake_packet": context_plan.wake_packet.to_dict(),
        }
    dx_metadata = _search_dx_metadata(
        memory_entry_count=len(entries),
        relation_fact_count=len(relation_facts),
        observation_count=len(obs_list),
        effective_mode=effective_mode,
        fallback_reason=fallback_reason,
        project_name=project_name,
        query=query,
        include_history=include_history,
        deep_recall=deep_recall,
        temporal_intent_mode=temporal_intent,
    )
    serialized_memory_entries = [
        serialize_memory_entry_search_result(entry, mode, tech_stack_by_project)
        for entry in entries
    ]
    serialized_relation_facts = [
        serialize_relation_fact_search_result(fact, tech_stack_by_project)
        for fact in relation_facts
    ]
    serialized_observations = [
        serialize_observation_search_result(
            observation,
            mode,
            query,
            tech_stack_by_project,
        )
        for observation in obs_list
    ]
    recall_result = build_search_recall_result(
        project_name=project_name,
        query=query,
        effective_query=parsed_time.query,
        requested_mode=mode,
        effective_mode=effective_mode,
        memory_entries=serialized_memory_entries,
        relation_facts=serialized_relation_facts,
        observations=serialized_observations,
        drilldown_hints=drilldown_hints,
        context=context_payload or None,
        answer_ready_context=runtime.answer_ready_context,
        warnings=[fallback_reason] if fallback_reason else [],
        effort="dynamic",
    )

    return {
        "project_name": project_name,
        "query": query,
        "effective_query": parsed_time.query,
        "scope": scope,
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "include_history": include_history,
        "deep_recall": deep_recall,
        "effective_deep_recall": runtime.effective_deep_recall,
        "orchestration_actions": runtime.orchestration_actions,
        "retrieval_profile": {
            "active": profile_info["active"],
            "configured": profile_info["configured"],
            "source": profile_info["source"],
        },
        "retrieval_quality": {
            **response.retrieval_quality,
            "active": profile_info["active"],
            "source": profile_info["source"],
            "configured": profile_info["configured"],
            "can_disable": True,
        },
        "time_window": (
            {
                "start": parsed_time.start.isoformat() if parsed_time.start else None,
                "end": parsed_time.end.isoformat() if parsed_time.end else None,
                "phrase": parsed_time.phrase,
            }
            if parsed_time.time_window
            else None
        ),
        "memory_entries": serialized_memory_entries,
        "relation_facts": serialized_relation_facts,
        "observations": serialized_observations,
        "memory_entry_count": len(entries),
        "relation_fact_count": len(relation_facts),
        "observation_count": len(obs_list),
        "backend_budget": response.budget,
        "backend_truncation": response.truncation,
        "source_coverage": response.source_coverage,
        "drilldown_hints": drilldown_hints,
        **dx_metadata,
        "supporting_evidence": runtime.supporting_evidence,
        "answer_ready_context": runtime.answer_ready_context,
        "recall": recall_result.to_dict(),
        **context_payload,
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
    include_provisional: bool = False,
    budget_tokens: int = 1600,
    retrieval_profile: str | None = None,
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
        include_provisional=include_provisional,
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
        mode="auto",
        include_history=decision.include_history,
        include_provisional=decision.include_provisional,
        deep_recall=decision.deep_recall,
        retrieval_profile=retrieval_profile,
        task=current_task,
        budget_tokens=decision.budget_tokens,
    )
    source_ids = [
        source_id
        for source_id in search_payload.get("context_plan", {}).get("source_ids", [])
        if isinstance(source_id, str)
    ]
    context_injection = {
        "target": decision.injection_target,
        "trigger": decision.trigger,
        "query": decision.query,
        "source_ids": source_ids,
        "answer_ready_context": search_payload.get("answer_ready_context"),
        "context_plan": search_payload.get("context_plan"),
        "supporting_evidence": search_payload.get("supporting_evidence", []),
        "drilldown_hints": search_payload.get("drilldown_hints", []),
        "record_outcome_call": {
            "tool": "record_context_outcome",
            "arguments": {
                "project_name": resolved_project,
                "surface": "autopilot_search_tick",
                "source_ids": source_ids,
                "outcome": "used",
            },
        },
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
    source_ids: list[str],
    outcome: str,
    reason: str | None = None,
) -> dict:
    """Record whether surfaced context helped the task without mutating truth."""
    resolved_project = (project_name or "").strip()
    if not resolved_project:
        return {
            "success": False,
            "error": "project_name must not be empty",
            "truth_mutated": False,
        }
    normalized_surface = (surface or "").strip()
    if not normalized_surface:
        return {
            "success": False,
            "error": "surface must not be empty",
            "truth_mutated": False,
        }
    normalized_outcome = (outcome or "").strip().lower()
    if normalized_outcome not in VALID_CONTEXT_OUTCOMES:
        return {
            "success": False,
            "error": "outcome must be one of: used, ignored, misleading",
            "truth_mutated": False,
        }
    cleaned_source_ids = [
        str(source_id).strip()
        for source_id in (source_ids or [])
        if str(source_id).strip()
    ]
    if not cleaned_source_ids:
        return {
            "success": False,
            "error": "source_ids must contain at least one id",
            "truth_mutated": False,
        }

    backend = _get_backend()
    signal_ids: list[str] = []
    failed_source_ids: list[str] = []
    context = {
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "reason": (reason or "").strip()[:500] or None,
    }
    value = CONTEXT_OUTCOME_VALUES[normalized_outcome]
    for source_id in cleaned_source_ids:
        signal = asyncio.run(
            record_retrieval_signal(
                backend,
                project_name=resolved_project,
                signal_type="context_outcome",
                target_kind="context_source",
                target_id=source_id,
                value=value,
                context=context,
            )
        )
        if signal is None:
            failed_source_ids.append(source_id)
        else:
            signal_ids.append(signal.id)

    return {
        "success": not failed_source_ids,
        "project_name": resolved_project,
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "recorded_count": len(signal_ids),
        "failed_count": len(failed_source_ids),
        "signal_ids": signal_ids,
        "failed_source_ids": failed_source_ids,
        "truth_mutated": False,
        "next_actions": [
            _action(
                "search_again",
                "/hm:search",
                "Opt-in projects can use outcome signals as a small explainable ranking hint.",
            )
        ],
        "why_this_result": (
            f"Recorded {len(signal_ids)} context outcome signals; confirmed truth was not changed."
        ),
        "degraded_reason": "signal_write_failed" if failed_source_ids else None,
    }


def tool_timeline(project_name: str, limit: int = 50) -> dict:
    """Return chronological observation timeline for a project."""
    backend = _get_backend()
    obs_list = asyncio.run(
        timeline_observations(backend, project_name=project_name, limit=limit)
    )

    return {
        "project_name": project_name,
        "limit": limit,
        "observations": [
            serialize_timeline_observation(observation) for observation in obs_list
        ],
        "count": len(obs_list),
    }


def tool_trace_relations(
    project_name: str,
    source_entity: str,
    relation_type: str | None = None,
    max_depth: int = 2,
    limit: int = 10,
    min_confidence: float = 0.0,
    include_history: bool = False,
) -> dict:
    """Return bounded relation paths starting at a source entity."""
    backend = _get_backend()
    try:
        paths = asyncio.run(
            trace_relation_paths(
                backend,
                project_name=project_name,
                source_entity=source_entity,
                relation_type=relation_type,
                max_depth=max_depth,
                limit=limit,
                min_confidence=min_confidence,
                include_history=include_history,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    serialized_paths = [serialize_relation_path(path) for path in paths]
    recall_result = build_trace_recall_result(
        project_name=project_name,
        source_entity=source_entity,
        relation_type=relation_type,
        paths=serialized_paths,
    )
    return {
        "success": True,
        "project_name": project_name,
        "source_entity": source_entity,
        "relation_type": relation_type,
        "max_depth": max_depth,
        "limit": limit,
        "include_history": include_history,
        "paths": serialized_paths,
        "path_count": len(paths),
        "recall": recall_result.to_dict(),
    }


def tool_temporal_query(
    project_name: str,
    query: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    truth_type: str | None = None,
    mode: str = "current",
    as_of: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    recorded_from: str | None = None,
    recorded_to: str | None = None,
    limit: int = 20,
    require_unique_current: bool = False,
) -> dict:
    """Query the v3.3 temporal read model without mutating truth."""
    if mode not in {"current", "history", "as_of"}:
        return {
            "success": False,
            "error": "mode must be one of: current, history, as_of",
        }
    if truth_type not in {None, "memory_entry", "relation_fact", "confirmed_rule"}:
        return {
            "success": False,
            "error": "truth_type must be one of: memory_entry, relation_fact, confirmed_rule",
        }
    parsed_as_of, error = _parse_optional_iso_datetime(as_of, "as_of")
    if error:
        return {"success": False, "error": error}
    if mode == "as_of" and parsed_as_of is None:
        return {"success": False, "error": "as_of is required when mode=as_of"}
    parsed_valid_from, error = _parse_optional_iso_datetime(valid_from, "valid_from")
    if error:
        return {"success": False, "error": error}
    parsed_valid_to, error = _parse_optional_iso_datetime(valid_to, "valid_to")
    if error:
        return {"success": False, "error": error}
    parsed_recorded_from, error = _parse_optional_iso_datetime(
        recorded_from, "recorded_from"
    )
    if error:
        return {"success": False, "error": error}
    parsed_recorded_to, error = _parse_optional_iso_datetime(recorded_to, "recorded_to")
    if error:
        return {"success": False, "error": error}

    backend = _get_backend()
    result = asyncio.run(
        query_temporal_truth(
            backend,
            project_name=project_name,
            query=query,
            subject=subject,
            predicate=predicate,
            truth_type=truth_type,
            mode=mode,
            as_of=parsed_as_of,
            valid_range=(parsed_valid_from, parsed_valid_to),
            recorded_range=(parsed_recorded_from, parsed_recorded_to),
            limit=limit,
            require_unique_current=require_unique_current,
        )
    )
    asyncio.run(
        _record_temporal_quality_signals(
            backend,
            project_name=project_name,
            result=result,
            mode=mode,
            identity_parts=(query, subject, predicate, truth_type, mode),
        )
    )
    payload = serialize_temporal_query_result(result)
    payload.update(
        {
            "project_name": project_name,
            "query": query,
            "subject": subject,
            "predicate": predicate,
            "truth_type": truth_type,
            "mode": mode,
            "as_of": parsed_as_of.isoformat() if parsed_as_of else None,
            "valid_range": {
                "start": parsed_valid_from.isoformat() if parsed_valid_from else None,
                "end": parsed_valid_to.isoformat() if parsed_valid_to else None,
            },
            "recorded_range": {
                "start": parsed_recorded_from.isoformat()
                if parsed_recorded_from
                else None,
                "end": parsed_recorded_to.isoformat() if parsed_recorded_to else None,
            },
        }
    )
    return payload


def _parse_optional_iso_datetime(
    value: str | None, field_name: str
) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{field_name} must be an ISO datetime"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, None


def tool_search_raw(
    pattern: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 20,
) -> dict:
    """Regex search raw observation evidence."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    backend = _get_backend()
    try:
        matches = asyncio.run(
            regex_search_observations(
                backend,
                project_name=project_name,
                pattern=pattern,
                scope=scope,
                limit=limit,
            )
        )
    except re.error as exc:
        return {"success": False, "error": f"invalid regex: {exc}"}

    return {
        "success": True,
        "project_name": project_name,
        "pattern": pattern,
        "scope": scope,
        "limit": limit,
        "matches": [serialize_regex_observation_match(match) for match in matches],
        "count": len(matches),
    }


def tool_search_skills(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 10,
    include_shared: bool = False,
    shared_scope: str = "exclude",
) -> dict:
    """Search confirmed procedural skills."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }
    if shared_scope not in {"exclude", "include", "only"}:
        return {
            "success": False,
            "error": "shared_scope must be one of: exclude, include, only",
        }

    effective_shared_scope = shared_scope
    if include_shared and shared_scope == "exclude":
        effective_shared_scope = "include"

    backend = _get_backend()
    skills = asyncio.run(
        search_skills(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            limit=limit,
            shared_scope=effective_shared_scope,
        )
    )
    return {
        "success": True,
        "project_name": project_name,
        "query": query,
        "scope": scope,
        "include_shared": include_shared,
        "shared_scope": effective_shared_scope,
        "limit": limit,
        "skills": [serialize_skill(skill) for skill in skills],
        "count": len(skills),
    }


def tool_get_skill(skill_id: str) -> dict:
    """Return a full confirmed skill payload by id."""
    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.get_skill(skill_id))
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    return {
        "success": True,
        "skill": serialize_skill(skill),
    }


def tool_get_observations(
    project_name: str,
    session_id: str | None = None,
    observation_ids: list[str] | None = None,
) -> dict:
    """Return project observations by session id or explicit observation ids."""

    requested_ids = [
        value.removeprefix("O-").strip()
        for value in observation_ids or []
        if value and value.strip()
    ]
    if not session_id and not requested_ids:
        return {
            "success": False,
            "project_name": project_name,
            "error": "session_id or observation_ids is required",
        }

    backend = _get_backend()
    project_obs = asyncio.run(
        backend.verbatim_store.list(limit=10000, project_name=project_name)
    )
    unresolved_ids: list[str] = []
    if requested_ids:
        selected: list[Any] = []
        for requested_id in requested_ids:
            matches = [
                observation
                for observation in project_obs
                if observation.id == requested_id
                or observation.id.startswith(requested_id)
            ]
            if len(matches) == 1:
                selected.append(matches[0])
            else:
                unresolved_ids.append(requested_id)
        observations = selected
    else:
        observations = [
            observation
            for observation in project_obs
            if observation.session_id == session_id
        ]

    return {
        "success": True,
        "project_name": project_name,
        "session_id": session_id,
        "observation_ids": requested_ids,
        "unresolved_ids": unresolved_ids,
        "observations": [
            serialize_observation(observation) for observation in observations
        ],
        "count": len(observations),
    }


def tool_get_task_handoffs(project_name: str, limit: int = 5) -> dict:
    """Return recent task handoffs for a project."""
    backend = _get_backend()
    handoffs = asyncio.run(
        backend.structured_store.get_latest_handoffs(project_name, limit=limit)
    )
    return {
        "project_name": project_name,
        "limit": limit,
        "handoffs": [
            {
                "id": h.id,
                "task_id": h.task_id,
                "summary": h.summary,
                "status": h.status,
                "next_steps": h.next_steps,
                "blockers": h.blockers,
                "last_activity": h.last_activity.isoformat()
                if h.last_activity
                else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "provenance": h.provenance,
            }
            for h in handoffs
        ],
        "count": len(handoffs),
    }


def tool_get_confirmed_rules(project_name: str, include_history: bool = False) -> dict:
    """Return all confirmed rules for a project."""
    backend = _get_backend()
    rules = asyncio.run(
        backend.structured_store.list_confirmed_rules(
            project_name,
            include_history=include_history,
        )
    )
    return {
        "project_name": project_name,
        "include_history": include_history,
        "rules": [
            {
                "id": r.id,
                "pattern": r.pattern,
                "trigger": r.trigger,
                "examples": r.examples,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "supersedes": r.supersedes,
                "superseded_by": r.superseded_by,
                "is_historical": bool(
                    r.valid_to and r.valid_to <= datetime.now(timezone.utc)
                ),
                "tags": r.tags,
                "provenance": r.provenance,
            }
            for r in rules
        ],
        "count": len(rules),
    }


def tool_get_project_profile(project_name: str) -> dict:
    """Return the project profile for a project."""

    store = asyncio.run(
        LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name)
    )
    if store is None:
        return {"project_name": project_name, "found": False}

    profile = store
    return {
        "found": True,
        "project_name": profile.project_name,
        "description": profile.description,
        "stacks": profile.stacks,
        "key_files": profile.key_files,
        "retrieval_profile": profile.retrieval_profile,
    }


def tool_file_context(
    path: str,
    project_name: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Return compact, source-attributed memory already associated with a path."""
    backend = _get_backend()
    try:
        result = asyncio.run(
            build_file_context(
                backend,
                project_name=project_name,
                path=path,
                project_root=project_root,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    payload = result.to_dict()
    payload["success"] = True
    return payload


def tool_wake(
    project_name: str | None = None,
    no_auto_ingest: bool = False,
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    deep_recall: bool = False,
    include_provisional: bool = False,
) -> dict:
    """Generate recent context plus stable truth and active handoffs.

    Captures the printed wake-up summary as ``output`` so the agent can
    ingest it directly without spawning a CLI subprocess.
    """
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
    command_payload = _run_command_to_payload(
        cmd_wake_up(
            resolved,
            no_auto_ingest=no_auto_ingest,
            include_skill_hints=include_skill_hints,
            skill_hint_limit=skill_hint_limit,
        )
    )
    snapshot_payload: dict[str, Any] = {}
    temporal_intent = _temporal_intent_mode(current_task)
    if command_payload.get("success"):
        effective_skill_hint_limit = (
            DEFAULT_SKILL_HINT_LIMIT if skill_hint_limit is None else skill_hint_limit
        )
        runtime = asyncio.run(
            orchestrate_task_context(
                _get_backend(),
                query=current_task or "wake context",
                project_name=resolved,
                scope="project",
                mode="auto",
                include_history=deep_recall,
                include_provisional=include_provisional,
                deep_recall=deep_recall,
                current_task=current_task,
                budget_tokens=budget_tokens,
                search_limit=10,
                context_limit=10,
                auto_deep_recall=True,
            )
        )
        snapshot_payload = asyncio.run(
            build_wake_snapshot(
                _get_backend(),
                resolved,
                include_skill_hints=bool(include_skill_hints),
                skill_hint_limit=effective_skill_hint_limit,
            )
        )
        context_plan = runtime.context_plan
        if context_plan is None:
            raise RuntimeError("project-scoped wake runtime returned no context plan")
        drilldown_hints = _with_temporal_intent_hint(
            runtime.response.drilldown_hints,
            project_name=resolved,
            query=current_task or "wake context",
            mode=temporal_intent,
        )
        status_counts = asyncio.run(_gather_project_status(_get_backend(), resolved))
        status_triage = status_triage_hints(status_counts)
        guided_flow = build_guided_flow(
            phase=str(status_triage.get("phase") or "ready"),
            observation_count=int(status_counts.get("observation_count", 0) or 0),
            pending_candidate_count=int(
                status_counts.get("pending_candidate_count", 0) or 0
            ),
            memory_entry_count=int(status_counts.get("memory_entry_count", 0) or 0),
            project_name=resolved,
            active_project=get_active_project(),
        )
        drilldown_hints = [
            guided_flow_drilldown_hint(guided_flow),
            *drilldown_hints,
        ]
        snapshot_payload.update(
            {
                "context_sufficiency": context_plan.context_sufficiency.to_dict(),
                "retrieval_plan": context_plan.retrieval_plan.to_dict(),
                "iterative_retrieval_trace": (
                    context_plan.iterative_retrieval_trace.to_dict()
                ),
                "context_plan": {
                    **context_plan.to_dict(),
                    "drilldown_hints": drilldown_hints,
                },
                "wake_packet": context_plan.wake_packet.to_dict(),
                "requested_mode": runtime.response.requested_mode,
                "effective_mode": runtime.response.effective_mode,
                "fallback_reason": runtime.response.fallback_metadata.get(
                    "fallback_reason"
                ),
                "backend_budget": runtime.response.budget,
                "backend_truncation": runtime.response.truncation,
                "source_coverage": runtime.response.source_coverage,
                "drilldown_hints": drilldown_hints,
                "guided_flow": guided_flow,
                "supporting_evidence": runtime.supporting_evidence,
                "answer_ready_context": runtime.answer_ready_context,
                "effective_deep_recall": runtime.effective_deep_recall,
                "orchestration_actions": runtime.orchestration_actions,
            }
        )
    wake_dx = _wake_dx_metadata(
        success=bool(command_payload.get("success")),
        fallback_reason=snapshot_payload.get("fallback_reason"),
        source_coverage=snapshot_payload.get("source_coverage"),
        temporal_intent_mode=temporal_intent,
    )
    return {
        "project_name": resolved,
        **snapshot_payload,
        **wake_dx,
        "include_skill_hints": include_skill_hints,
        "skill_hint_limit": skill_hint_limit,
        "current_task": current_task,
        "budget_tokens": budget_tokens,
        "deep_recall": deep_recall,
        **command_payload,
    }
