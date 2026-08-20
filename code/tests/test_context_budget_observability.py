from __future__ import annotations

from harness_mem.core.schemas.context_sufficiency import (
    RetrievalPlan,
    context_plan_from_response,
)
from harness_mem.search.backend import (
    BackendSearchResult,
    SearchBackendResponse,
)


def test_context_plan_records_budget_breakdown_and_compaction_outcome() -> None:
    response = SearchBackendResponse(
        query="migration",
        requested_mode="fts",
        effective_mode="fts",
        results=[
            BackendSearchResult(
                source_id="memory-1",
                source_kind="memory_entry",
                score=1.0,
                preview="compact migration summary",
            ),
            BackendSearchResult(
                source_id="observation-1",
                source_kind="observation",
                score=0.8,
                preview="raw migration evidence",
            ),
        ],
        fallback_metadata={},
        budget={"estimated_tokens": 8},
        truncation={"available": 3, "included": 2, "dropped": 1, "truncated": True},
        source_coverage={"memory_entry": 1, "observation": 1},
        drilldown_hints=[],
    )
    plan = context_plan_from_response(
        project_name="demo",
        response=response,
        retrieval_plan=RetrievalPlan(query="migration", budget_tokens=12),
    )

    assert plan.compaction_outcome == "result_truncated"
    assert plan.context_budget == {
        "raw_tokens": 5,
        "summary_tokens": 6,
        "retrieved_tokens": 8,
        "total_tokens": 8,
        "budget_tokens": 12,
    }
    assert plan.wake_packet.context_budget == plan.context_budget
    restored = type(plan).from_dict(plan.to_dict())
    assert restored.context_budget == plan.context_budget
    assert restored.compaction_outcome == "result_truncated"
