"""Public search and retrieval-feedback MCP handlers."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from harness_mem.commands.support import (
    get_active_project,
)
from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.read_api import (
    parse_relative_time_window,
    serialize_memory_entry_search_result,
    serialize_observation_search_result,
    serialize_relation_fact_search_result,
)
from harness_mem.recall import build_search_recall_result
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.task_context_runtime import orchestrate_task_context

from .handler_facade_proxy import tool_handlers_facade as _core
from harness_mem.mcp.read_query_support import (
    _action,
    _autopilot_dx_metadata,
    _count_mainline_historical_exclusions,
    _new_retrieval_id,
    _record_search_quality_signals,
    _resolve_retrieval_profile,
    _search_dx_metadata,
    _temporal_intent_mode,
    _with_temporal_intent_hint,
)


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
    retrieval_id = _new_retrieval_id()
    retrieval_receipt: dict[str, Any] = {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": retrieval_id,
        "surface": "search_memory",
        "attempted": 0,
        "recorded": 0,
        "failed": 0,
        "state": "not_applicable",
        "source_ids": [],
        "content_recorded": False,
    }
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
        retrieval_receipt = asyncio.run(
            _record_search_quality_signals(
                backend,
                project_name=project_name,
                query=query,
                entries=entries,
                relation_facts=relation_facts,
                observations=obs_list,
                response=response,
                context_plan=runtime.context_plan,
                historical_excluded=historical_excluded,
                retrieval_id=retrieval_id,
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
    source_ids = list(retrieval_receipt.get("source_ids") or [])
    record_outcome_call = (
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
        if project_name and source_ids
        else None
    )

    return {
        "project_name": project_name,
        "retrieval_id": retrieval_id,
        "retrieval_receipt": retrieval_receipt,
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
        "record_outcome_call": record_outcome_call,
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
    source_ids: list[str],
    outcome: str,
    reason: str | None = None,
    retrieval_id: str | None = None,
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
    normalized_retrieval_id = (retrieval_id or "").strip()[:128] or None

    backend = _get_backend()
    signal_ids: list[str] = []
    failed_source_ids: list[str] = []
    context = {
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "reason": (reason or "").strip()[:500] or None,
        "retrieval_id": normalized_retrieval_id,
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
        "retrieval_id": normalized_retrieval_id,
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
