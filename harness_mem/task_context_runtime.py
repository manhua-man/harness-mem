from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from harness_mem.context_assembly import assemble_context_plan
from harness_mem.context_sufficiency import (
    TaskAwareRetrievalRuntime,
    build_task_aware_retrieval_runtime,
)
from harness_mem.core.schemas.context_assembly_plan import ContextAssemblyPlan, LayerId
from harness_mem.core.schemas.context_sufficiency import ContextPlan
from harness_mem.read_api import build_search_project_context_map, preview_search_text
from harness_mem.search.backend import SearchBackendResponse, hydrate_backend_results
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

_HISTORY_HINT_WORDS = (
    "history",
    "historical",
    "previous",
    "before",
    "after",
    "changed",
    "legacy",
    "archive",
    "timeline",
    "old",
)


@dataclass(frozen=True)
class TaskContextRuntime:
    response: SearchBackendResponse
    context_plan: ContextPlan | None
    context_assembly_plan: ContextAssemblyPlan | None
    entries: list[Any]
    observations: list[Any]
    relation_facts: list[Any]
    tech_stack_by_project: dict[str, list[str]]
    requested_deep_recall: bool
    effective_deep_recall: bool
    orchestration_actions: list[str]
    supporting_evidence: list[dict[str, Any]]
    answer_ready_context: dict[str, Any] | None


async def orchestrate_task_context(
    backend: LocalMemoryBackend,
    *,
    query: str,
    project_name: str | None,
    scope: str = "project",
    mode: str = "auto",
    memory_type: list[str] | None = None,
    include_history: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
    deep_recall: bool = False,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    search_limit: int = 60,
    context_limit: int = 20,
    auto_deep_recall: bool = False,
) -> TaskContextRuntime:
    actions: list[str] = []
    effective_deep_recall = deep_recall

    if scope == "project" and project_name:
        retrieval = await build_task_aware_retrieval_runtime(
            backend,
            project_name=project_name,
            query=query,
            current_task=current_task,
            budget_tokens=budget_tokens,
            mode=mode,
            scope=scope,
            memory_type=memory_type,
            include_history=include_history,
            time_window=time_window,
            deep_recall=deep_recall,
            limit=context_limit,
        )
        assembly_plan = await assemble_context_plan(
            backend,
            project_name=project_name,
            query=retrieval.context_plan.query,
        )
        actions.extend(_assembly_actions(assembly_plan))

        if auto_deep_recall and _should_auto_deep_recall(
            query=query,
            current_task=current_task,
            retrieval=retrieval,
            assembly_plan=assembly_plan,
            requested_deep_recall=deep_recall,
        ):
            retrieval = await build_task_aware_retrieval_runtime(
                backend,
                project_name=project_name,
                query=query,
                current_task=current_task,
                budget_tokens=budget_tokens,
                mode=mode,
                scope=scope,
                memory_type=memory_type,
                include_history=include_history,
                time_window=time_window,
                deep_recall=True,
                limit=context_limit,
            )
            assembly_plan = await assemble_context_plan(
                backend,
                project_name=project_name,
                query=retrieval.context_plan.query,
            )
            actions.append("auto_deep_recall")
            actions.extend(_assembly_actions(assembly_plan))
            effective_deep_recall = True

        response = _extend_response_with_assembly_hints(retrieval.response, assembly_plan)
        context_plan = _enrich_context_plan(
            retrieval.context_plan,
            assembly_plan=assembly_plan,
            drilldown_hints=response.drilldown_hints,
        )
    else:
        assembly_plan = None
        retrieval = await build_task_aware_retrieval_runtime(
            backend,
            project_name=project_name or "",
            query=query,
            current_task=current_task,
            budget_tokens=budget_tokens,
            mode=mode,
            scope=scope,
            memory_type=memory_type,
            include_history=include_history,
            time_window=time_window,
            deep_recall=deep_recall,
            limit=search_limit,
        )
        response = retrieval.response
        context_plan = None

    hydrated = await hydrate_backend_results(backend, response)
    entries = list(hydrated["memory_entry"])[:20]
    observations = list(hydrated["observation"])[:20]
    relation_facts = list(hydrated["relation_fact"])[:20]
    for entry in entries:
        await backend.structured_store.touch_memory_entry(entry.id)
    tech_stack_by_project = await build_search_project_context_map(
        backend,
        entries=entries,
        observations=observations,
        relation_facts=relation_facts,
    )
    supporting_evidence = (
        await _build_supporting_evidence(
            backend,
            query=response.query,
            assembly_plan=assembly_plan,
        )
        if assembly_plan is not None
        else []
    )
    answer_ready_context = (
        _build_answer_ready_context(
            response=response,
            current_task=current_task,
            context_plan=context_plan,
            assembly_plan=assembly_plan,
            supporting_evidence=supporting_evidence,
            effective_deep_recall=effective_deep_recall,
            orchestration_actions=_dedupe(actions),
        )
        if context_plan is not None and assembly_plan is not None
        else None
    )
    return TaskContextRuntime(
        response=response,
        context_plan=context_plan,
        context_assembly_plan=assembly_plan,
        entries=entries,
        observations=observations,
        relation_facts=relation_facts,
        tech_stack_by_project=tech_stack_by_project,
        requested_deep_recall=deep_recall,
        effective_deep_recall=effective_deep_recall,
        orchestration_actions=_dedupe(actions),
        supporting_evidence=supporting_evidence,
        answer_ready_context=answer_ready_context,
    )


def _should_auto_deep_recall(
    *,
    query: str,
    current_task: str | None,
    retrieval: TaskAwareRetrievalRuntime,
    assembly_plan: ContextAssemblyPlan,
    requested_deep_recall: bool,
) -> bool:
    if requested_deep_recall:
        return False
    report = retrieval.context_plan.context_sufficiency
    if report.safe_to_answer:
        return False
    if "expand_observations" not in report.recommended_action:
        return False
    if retrieval.iterative_trace.budget_remaining == 0:
        return False
    if retrieval.retrieval_plan.classifier == "temporal":
        return True
    combined = " ".join(
        part.strip().lower() for part in (query, current_task or "", *report.missing_evidence) if part
    )
    if any(marker in combined for marker in _HISTORY_HINT_WORDS):
        return True
    return False


def _extend_response_with_assembly_hints(
    response: SearchBackendResponse,
    assembly_plan: ContextAssemblyPlan,
) -> SearchBackendResponse:
    hints = list(response.drilldown_hints)
    seen = {
        (str(hint.get("source_id")), str(hint.get("read_surface")))
        for hint in hints
    }
    for entry in assembly_plan.layer("L4").entries:
        if entry.drilldown is None:
            continue
        hint = {
            "source_id": entry.drilldown.source_id,
            "source_kind": "context_assembly",
            "read_surface": entry.drilldown.read_surface,
            "locator": dict(entry.drilldown.locator),
            "why_included": entry.why_included,
            "truth_status": entry.truth_status,
            "layer": entry.layer,
        }
        key = (str(hint["source_id"]), str(hint["read_surface"]))
        if key in seen:
            continue
        seen.add(key)
        hints.append(hint)
    return SearchBackendResponse(
        query=response.query,
        requested_mode=response.requested_mode,
        effective_mode=response.effective_mode,
        results=response.results,
        fallback_metadata=response.fallback_metadata,
        budget=response.budget,
        truncation=response.truncation,
        source_coverage=response.source_coverage,
        drilldown_hints=hints,
    )


def _enrich_context_plan(
    context_plan: ContextPlan,
    *,
    assembly_plan: ContextAssemblyPlan,
    drilldown_hints: list[dict[str, Any]],
) -> ContextPlan:
    l4_entries = assembly_plan.layer("L4").entries
    if not l4_entries:
        return context_plan.model_copy(update={"drilldown_hints": list(drilldown_hints)})

    extra_source_ids = [
        source_id
        for entry in l4_entries
        for source_id in entry.source_ids
    ]
    extra_why_included = [
        {"source_id": entry.source_ids[0], "reason": entry.why_included}
        for entry in l4_entries
    ]
    wake_packet = context_plan.wake_packet.model_copy(
        update={
            "soft_include": _dedupe([*context_plan.wake_packet.soft_include, *extra_source_ids]),
            "why_included": [*context_plan.wake_packet.why_included, *extra_why_included],
        }
    )
    return context_plan.model_copy(
        update={
            "source_ids": _dedupe([*context_plan.source_ids, *extra_source_ids]),
            "why_included": [*context_plan.why_included, *extra_why_included],
            "drilldown_hints": list(drilldown_hints),
            "wake_packet": wake_packet,
        }
    )


def _assembly_actions(assembly_plan: ContextAssemblyPlan) -> list[str]:
    l4 = assembly_plan.layer("L4")
    if not l4.entries:
        return []
    return ["background_evidence_expansion"]


async def _build_supporting_evidence(
    backend: LocalMemoryBackend,
    *,
    query: str,
    assembly_plan: ContextAssemblyPlan,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in assembly_plan.layer("L4").entries:
        drilldown = entry.drilldown
        if drilldown is None:
            continue
        key = (drilldown.source_id, drilldown.read_surface)
        if key in seen:
            continue
        seen.add(key)
        if drilldown.read_surface == "read_api.get_observations":
            observation = await backend.verbatim_store.get(drilldown.source_id)
            if observation is None:
                continue
            evidence.append(
                {
                    "source_id": observation.id,
                    "source_kind": "observation",
                    "reason": entry.why_included,
                    "preview": preview_search_text(observation.raw_content, query, max_chars=200),
                    "read_surface": drilldown.read_surface,
                    "locator": dict(drilldown.locator),
                    "truth_status": entry.truth_status,
                }
            )
        elif drilldown.read_surface == "read_api.get_memory_entry":
            memory_entry = await backend.structured_store.get_memory_entry(drilldown.source_id)
            if memory_entry is None:
                continue
            evidence.append(
                {
                    "source_id": memory_entry.id,
                    "source_kind": "memory_entry",
                    "reason": entry.why_included,
                    "preview": preview_search_text(memory_entry.content, query, max_chars=200),
                    "read_surface": drilldown.read_surface,
                    "locator": dict(drilldown.locator),
                    "truth_status": entry.truth_status,
                }
            )
    return evidence[:8]


def _build_answer_ready_context(
    *,
    response: SearchBackendResponse,
    current_task: str | None,
    context_plan: ContextPlan,
    assembly_plan: ContextAssemblyPlan,
    supporting_evidence: list[dict[str, Any]],
    effective_deep_recall: bool,
    orchestration_actions: list[str],
) -> dict[str, Any]:
    report = context_plan.context_sufficiency
    return {
        "project_name": context_plan.project_name,
        "query": context_plan.query or response.query,
        "current_task": current_task,
        "safe_to_answer": report.safe_to_answer,
        "sufficiency_status": report.status,
        "support_level": report.support_level,
        "effective_deep_recall": effective_deep_recall,
        "orchestration_actions": list(orchestration_actions),
        "project_profile": _layer_summaries(assembly_plan, "L0", limit=3),
        "truth": _layer_summaries(assembly_plan, "L1", limit=6),
        "active_task": _layer_summaries(assembly_plan, "L2", limit=6),
        "topic_recall": _layer_summaries(assembly_plan, "L3", limit=6),
        "supporting_evidence": list(supporting_evidence),
        "caveats": list(report.missing_evidence),
        "recommended_action": list(report.recommended_action),
        "drilldown_hints": list(context_plan.drilldown_hints),
    }


def _layer_summaries(
    assembly_plan: ContextAssemblyPlan,
    layer_id: LayerId,
    *,
    limit: int,
) -> list[dict[str, str]]:
    return [
        {
            "source_id": entry.source_ids[0],
            "reason": entry.why_included,
            "summary": entry.summary,
        }
        for entry in assembly_plan.layer(layer_id).entries[:limit]
        if entry.summary
    ]


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


__all__ = ["TaskContextRuntime", "orchestrate_task_context"]
