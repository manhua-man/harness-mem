"""Wake orchestration MCP handler."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from harness_mem.commands.support import (
    get_active_project,
)
from harness_mem.commands.wake import (
    DEFAULT_SKILL_HINT_LIMIT,
    build_wake_snapshot,
    cmd_wake_up,
)
from harness_mem.guided_flow import build_guided_flow, guided_flow_drilldown_hint
from harness_mem.task_context_runtime import orchestrate_task_context
from harness_mem.mcp.response_views import (
    status_triage_hints,
)

from .handler_facade_proxy import tool_handlers_facade as _core
from .read_query_support import (
    _action,
    _new_retrieval_id,
    _temporal_intent_mode,
    _wake_dx_metadata,
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


def tool_wake(
    project_name: str | None = None,
    no_auto_ingest: bool = False,
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    deep_recall: bool = False,
    include_provisional: bool = False,
    detail_level: str = "compact",
) -> dict:
    """Generate recent context plus stable truth and active handoffs.

    Captures the printed wake-up summary as ``output`` so the agent can
    ingest it directly without spawning a CLI subprocess.
    """
    if detail_level not in {"compact", "full"}:
        return {
            "success": False,
            "error": "detail_level must be one of: compact, full",
        }
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
    distill_maintenance: dict[str, Any] = {}
    retrieval_id = _new_retrieval_id()
    retrieval_receipt: dict[str, Any] = {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": retrieval_id,
        "surface": "wake",
        "attempted": 0,
        "recorded": 0,
        "failed": 0,
        "state": "not_recorded",
        "source_ids": [],
        "content_recorded": False,
    }
    command_payload = _run_command_to_payload(
        cmd_wake_up(
            resolved,
            no_auto_ingest=no_auto_ingest,
            include_skill_hints=include_skill_hints,
            skill_hint_limit=skill_hint_limit,
            maintenance_capture=distill_maintenance,
            retrieval_id=retrieval_id,
            retrieval_capture=retrieval_receipt,
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
                auto_deep_recall=False,
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
                "retrieval_id": retrieval_id,
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
                "record_outcome_call": (
                    {
                        "tool": "record_context_outcome",
                        "arguments": {
                            "project_name": resolved,
                            "surface": "wake",
                            "source_ids": list(
                                retrieval_receipt.get("source_ids") or []
                            ),
                            "retrieval_id": retrieval_id,
                        },
                        "required_argument": "outcome",
                        "allowed_outcomes": sorted(VALID_CONTEXT_OUTCOMES),
                    }
                    if retrieval_receipt.get("source_ids")
                    else None
                ),
            }
        )
        if detail_level == "compact":
            snapshot_payload = _compact_wake_snapshot(snapshot_payload)
            command_payload = _compact_wake_command_payload(command_payload)
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
        "detail_level": detail_level,
        "retrieval_receipt": retrieval_receipt,
        "distill_maintenance": distill_maintenance,
        **command_payload,
    }


def _compact_wake_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project one authoritative wake context without repeated content trees."""

    context_plan = dict(snapshot.get("context_plan") or {})
    answer_ready = snapshot.get("answer_ready_context")
    diagnostics = {
        key: context_plan.get(key)
        for key in (
            "context_sufficiency",
            "retrieval_plan",
            "iterative_retrieval_trace",
            "context_budget",
            "compaction_outcome",
        )
        if context_plan.get(key) is not None
    }
    return {
        "context_contract_version": "wake-context-v2",
        "retrieval_id": snapshot.get("retrieval_id"),
        "authoritative_context_field": "answer_ready_context",
        "answer_ready_context": answer_ready,
        "context_diagnostics": diagnostics,
        "requested_mode": snapshot.get("requested_mode"),
        "effective_mode": snapshot.get("effective_mode"),
        "fallback_reason": snapshot.get("fallback_reason"),
        "backend_budget": snapshot.get("backend_budget"),
        "backend_truncation": snapshot.get("backend_truncation"),
        "source_coverage": snapshot.get("source_coverage"),
        "guided_flow": snapshot.get("guided_flow"),
        "effective_deep_recall": snapshot.get("effective_deep_recall"),
        "orchestration_actions": snapshot.get("orchestration_actions"),
        "record_outcome_call": snapshot.get("record_outcome_call"),
        "details_available": [
            "context_plan",
            "wake_packet",
            "supporting_evidence",
            "iterative_retrieval_trace",
        ],
        "full_detail_hint": {
            "tool": "wake",
            "arguments": {"detail_level": "full"},
            "why": "Request full diagnostics only when compact wake needs investigation.",
        },
    }


def _compact_wake_command_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep command status while removing a duplicate rendered context block."""

    if not bool(payload.get("success")):
        return dict(payload)
    return {
        "success": True,
        "exit_code": payload.get("exit_code"),
        "rendered_output_available_in_full": bool(payload.get("output")),
    }
