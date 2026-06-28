"""v4.1 task-aware retrieval planning and sufficiency runtime helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_mem.core.schemas.context_sufficiency import (
    ContextPlan,
    IterativeRetrievalTrace,
    MetadataFilter,
    RetrievalPlan,
    SufficiencyReport,
    build_retrieval_plan,
    context_plan_from_response,
    evaluate_sufficiency,
    retrieval_round_from_response,
)
from harness_mem.search.backend import SearchFilters, SQLiteSearchBackend
from harness_mem.search.retrieval_quality import build_quality_trace, build_query_variants
from harness_mem.search.backend import SearchBackendResponse
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@dataclass(frozen=True)
class TaskAwareRetrievalRuntime:
    effective_query: str
    retrieval_plan: RetrievalPlan
    response: SearchBackendResponse
    sufficiency: SufficiencyReport
    iterative_trace: IterativeRetrievalTrace
    context_plan: ContextPlan


async def build_task_aware_retrieval_runtime(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    mode: str = "auto",
    scope: str = "project",
    memory_type: list[str] | None = None,
    include_history: bool = False,
    include_provisional: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
    deep_recall: bool = False,
    metadata_filter: MetadataFilter | None = None,
    limit: int = 20,
    retrieval_profile: str = "light",
) -> TaskAwareRetrievalRuntime:
    """Run bounded retrieval once and return both response and plan state."""

    explicit_quality_pack = retrieval_profile == "quality"
    effective_query = _effective_query(query, current_task)
    retrieval_plan = build_retrieval_plan(
        query=effective_query,
        project_name=project_name,
        metadata_filter=metadata_filter,
        budget_tokens=budget_tokens,
        mode=mode,
        deep_recall=deep_recall,
    )
    filters = SearchFilters(
        project_name=project_name,
        scope=scope,
        memory_type=memory_type,
        include_history=include_history or deep_recall,
        include_provisional=include_provisional,
        time_window=time_window,
        deep_recall=deep_recall,
        corpus_id=retrieval_plan.filters.corpus_id,
        tier=retrieval_plan.filters.tiers,
        truth_status=retrieval_plan.filters.truth_status,
    )
    backend_search = SQLiteSearchBackend(backend)
    first = await backend_search.search(
        effective_query,
        filters=filters,
        mode=mode,  # type: ignore[arg-type]
        limit=limit,
        budget_tokens=budget_tokens,
    )
    first_report = evaluate_sufficiency(
        query=effective_query,
        results=first.results,
        required_slots=[current_task] if current_task else None,
    )
    rounds = [
        retrieval_round_from_response(
            first,
            round_number=1,
            retrieval_plan=retrieval_plan,
            sufficiency=first_report,
        )
    ]
    final_response = first
    final_report = first_report
    stopped_reason = "sufficient" if first_report.safe_to_answer else "insufficient"
    estimated = int(first.budget.get("estimated_tokens") or 0)
    budget_remaining = max(0, budget_tokens - estimated)

    quality_trace = build_quality_trace(
        query=effective_query,
        classifier=retrieval_plan.classifier,
        source_ids=[result.source_id for result in first.results],
        insufficient=not first_report.safe_to_answer,
        explicit_quality_pack=explicit_quality_pack,
        insufficiency_queries=first_report.next_queries,
    )
    variants = build_query_variants(
        effective_query,
        classifier=retrieval_plan.classifier,
        insufficiency_queries=first_report.next_queries,
        profile=quality_trace.profile,
    )

    should_run_second_query = (
        (
            not first_report.safe_to_answer
            and bool(first_report.next_queries)
        )
        or (explicit_quality_pack and len(variants) > 1)
    )
    if should_run_second_query and budget_remaining > 0 and retrieval_plan.max_rounds > 1:
        second_query = variants[1] if len(variants) > 1 else first_report.next_queries[0]
        second = await backend_search.search(
            second_query,
            filters=filters,
            mode=mode,  # type: ignore[arg-type]
            limit=limit,
            budget_tokens=budget_remaining,
        )
        combined_results = _merge_results(first.results, second.results)
        final_response = type(first)(
            query=second_query,
            requested_mode=second.requested_mode,
            effective_mode=second.effective_mode,
            results=combined_results[:limit],
            fallback_metadata=second.fallback_metadata,
            budget={
                "requested_tokens": budget_tokens,
                "estimated_tokens": int(first.budget.get("estimated_tokens") or 0)
                + int(second.budget.get("estimated_tokens") or 0),
                "result_limit": limit,
            },
            truncation={
                "available": len(combined_results),
                "included": min(limit, len(combined_results)),
                "dropped": max(0, len(combined_results) - limit),
                "truncated": len(combined_results) > limit,
            },
            source_coverage=second.source_coverage,
            drilldown_hints=[*first.drilldown_hints, *second.drilldown_hints],
        )
        final_report = evaluate_sufficiency(
            query=effective_query,
            results=final_response.results,
            required_slots=[current_task] if current_task else None,
        )
        rounds.append(
            retrieval_round_from_response(
                second,
                round_number=2,
                retrieval_plan=retrieval_plan,
                sufficiency=final_report,
            )
        )
        stopped_reason = "sufficient" if final_report.safe_to_answer else "max_rounds"
        budget_remaining = max(
            0,
            budget_tokens - int(final_response.budget.get("estimated_tokens") or 0),
        )
        quality_trace = build_quality_trace(
            query=effective_query,
            classifier=retrieval_plan.classifier,
            source_ids=[result.source_id for result in final_response.results],
            insufficient=not final_report.safe_to_answer,
            explicit_quality_pack=explicit_quality_pack,
            insufficiency_queries=first_report.next_queries,
        )
        variants = build_query_variants(
            effective_query,
            classifier=retrieval_plan.classifier,
            insufficiency_queries=first_report.next_queries,
            profile=quality_trace.profile,
        )
    final_response = type(final_response)(
        query=final_response.query,
        requested_mode=final_response.requested_mode,
        effective_mode=final_response.effective_mode,
        results=final_response.results,
        fallback_metadata=final_response.fallback_metadata,
        budget=final_response.budget,
        truncation=final_response.truncation,
        source_coverage=final_response.source_coverage,
        drilldown_hints=final_response.drilldown_hints,
        retrieval_quality={
            "active": retrieval_profile,
            "source": "runtime",
            "claim_boundary": (
                "component-level retrieval profile metadata only; not broad "
                "answer-quality, token/cost, or production ranking proof"
            ),
            **quality_trace.to_dict(),
            "query_variants": variants,
        },
    )

    trace = IterativeRetrievalTrace(
        rounds=rounds,
        max_rounds=retrieval_plan.max_rounds,
        stopped_reason=stopped_reason,
        budget_remaining=budget_remaining,
        retrieval_quality=quality_trace.to_dict(),
    )
    context_plan = context_plan_from_response(
        project_name=project_name,
        response=final_response,
        retrieval_plan=retrieval_plan,
        sufficiency=final_report,
        iterative_trace=trace,
    )
    return TaskAwareRetrievalRuntime(
        effective_query=effective_query,
        retrieval_plan=retrieval_plan,
        response=final_response,
        sufficiency=final_report,
        iterative_trace=trace,
        context_plan=context_plan,
    )


async def assemble_task_aware_context_plan(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    mode: str = "auto",
    scope: str = "project",
    memory_type: list[str] | None = None,
    include_history: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
    deep_recall: bool = False,
    metadata_filter: MetadataFilter | None = None,
    limit: int = 20,
    retrieval_profile: str = "light",
) -> ContextPlan:
    """Build a read-only v4.1 context plan with bounded iterative retrieval."""

    runtime = await build_task_aware_retrieval_runtime(
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
        metadata_filter=metadata_filter,
        limit=limit,
        retrieval_profile=retrieval_profile,
    )
    return runtime.context_plan


def _effective_query(query: str, current_task: str | None) -> str:
    if current_task and current_task.strip() and current_task.strip() not in query:
        return f"{query} {current_task.strip()}"
    return query


def _merge_results(first, second):  # noqa: ANN001
    merged = []
    seen = set()
    for result in [*first, *second]:
        key = (result.source_kind, result.source_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return merged


__all__ = [
    "TaskAwareRetrievalRuntime",
    "assemble_task_aware_context_plan",
    "build_task_aware_retrieval_runtime",
]
