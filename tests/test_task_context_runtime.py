from datetime import datetime, timezone

from harness_mem.context_sufficiency import TaskAwareRetrievalRuntime
from harness_mem.core.schemas.context_assembly_plan import (
    Budget,
    ContextAssemblyPlan,
    DrilldownPointer,
    Layer,
    PlanEntry,
    TruncationAccounting,
)
from harness_mem.core.schemas.context_sufficiency import (
    ContextPlan,
    IterativeRetrievalTrace,
    MetadataFilter,
    RetrievalPlan,
    SufficiencyReport,
    WakePacket,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.search.backend import BackendSearchResult, SearchBackendResponse
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.task_context_runtime import orchestrate_task_context
from tests.helpers import run


def _runtime(*, query: str, safe_to_answer: bool, source_id: str) -> TaskAwareRetrievalRuntime:
    report = SufficiencyReport(
        status="sufficient" if safe_to_answer else "insufficient",
        support_level="direct" if safe_to_answer else "weak",
        missing_evidence=[] if safe_to_answer else ["historical rollout context"],
        safe_to_answer=safe_to_answer,
        recommended_action=[] if safe_to_answer else ["expand_observations", "ask_user"],
        confidence=1.0 if safe_to_answer else 0.2,
        next_queries=[] if safe_to_answer else ["previous rollout context"],
        checks={},
    )
    retrieval_plan = RetrievalPlan(
        query=query,
        classifier="simple",
        corpora=["default"],
        filters=MetadataFilter(project_id="demo", tiers=["hot", "warm"]),
        budget_tokens=6000,
        mode="auto",
        max_rounds=2,
        reasons=[],
        query_rewrites=[query],
        quality_gates=["required_slots"],
    )
    response = SearchBackendResponse(
        query=query,
        requested_mode="auto",
        effective_mode="fts",
        results=[
            BackendSearchResult(
                source_id=source_id,
                source_kind="memory_entry",
                score=1.0,
                preview=f"{query} evidence",
                metadata={"truth_status": "accepted"},
            )
        ],
        fallback_metadata={
            "backend": "sqlite",
            "requested_mode": "auto",
            "effective_mode": "fts",
            "fallback_reason": None,
        },
        budget={"requested_tokens": 6000, "estimated_tokens": 120, "result_limit": 20},
        truncation={"available": 1, "included": 1, "dropped": 0, "truncated": False},
        source_coverage={"memory_entry": 1},
        drilldown_hints=[
            {
                "source_id": source_id,
                "source_kind": "memory_entry",
                "read_surface": "read_api.get_memory_entry",
            }
        ],
    )
    trace = IterativeRetrievalTrace(
        rounds=[],
        max_rounds=2,
        stopped_reason="sufficient" if safe_to_answer else "insufficient",
        budget_remaining=500,
        retrieval_quality={},
    )
    context_plan = ContextPlan(
        project_name="demo",
        query=query,
        source_ids=[source_id],
        why_included=[{"source_id": source_id, "reason": "direct_truth"}],
        why_omitted=[],
        drilldown_hints=list(response.drilldown_hints),
        wake_packet=WakePacket(
            budget_tokens=6000,
            hard_include=[source_id],
            soft_include=[],
            evict_first=[],
            why_included=[{"source_id": source_id, "reason": "direct_truth"}],
            why_omitted=[],
            budget_trace={"requested": 6000, "used": 120, "truncated": False, "available": 1},
        ),
        context_sufficiency=report,
        retrieval_plan=retrieval_plan,
        iterative_retrieval_trace=trace,
    )
    return TaskAwareRetrievalRuntime(
        effective_query=query,
        retrieval_plan=retrieval_plan,
        response=response,
        sufficiency=report,
        iterative_trace=trace,
        context_plan=context_plan,
    )


def _assembly_plan(query: str) -> ContextAssemblyPlan:
    return ContextAssemblyPlan(
        project_name="demo",
        query=query,
        layers=[
            Layer(
                layer="L0",
                entries=[],
                budget=Budget(max_entries=3),
                truncation=TruncationAccounting(available=0, included=0, dropped=0),
            ),
            Layer(
                layer="L1",
                entries=[
                    PlanEntry(
                        layer="L1",
                        source_ids=["mem-truth"],
                        why_included="confirmed_truth",
                        summary="Confirmed truth for the rollout",
                    )
                ],
                budget=Budget(max_entries=7),
                truncation=TruncationAccounting(available=1, included=1, dropped=0),
            ),
            Layer(
                layer="L2",
                entries=[
                    PlanEntry(
                        layer="L2",
                        source_ids=["handoff-task"],
                        why_included="active_handoff",
                        summary="Current task handoff summary",
                    )
                ],
                budget=Budget(max_entries=7),
                truncation=TruncationAccounting(available=1, included=1, dropped=0),
            ),
            Layer(
                layer="L3",
                entries=[
                    PlanEntry(
                        layer="L3",
                        source_ids=["mem-topic"],
                        why_included="topic_recall:search_memory",
                        summary="Topic recall summary",
                    )
                ],
                budget=Budget(max_entries=10),
                truncation=TruncationAccounting(available=1, included=1, dropped=0),
            ),
            Layer(
                layer="L4",
                entries=[
                    PlanEntry(
                        layer="L4",
                        source_ids=["obs-support"],
                        why_included="evidence:topic_match",
                        drilldown=DrilldownPointer(
                            source_id="obs-support",
                            read_surface="read_api.get_observations",
                            locator={"session_id": "sess-1"},
                        ),
                    )
                ],
                budget=Budget(max_entries=20),
                truncation=TruncationAccounting(available=1, included=1, dropped=0),
            ),
        ],
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )


def test_orchestrator_auto_deep_recall_and_background_evidence(
    backend: LocalMemoryBackend,
    monkeypatch,
) -> None:
    calls: list[bool] = []
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-support",
                session_id="sess-1",
                client="pytest",
                raw_content="supporting evidence for the rollout history question",
                content_type="transcript",
                timestamp=datetime(2026, 6, 12, tzinfo=timezone.utc),
                metadata={"project_name": "demo"},
            )
        )
    )

    async def _fake_build(_backend, **kwargs):
        deep_recall = bool(kwargs["deep_recall"])
        calls.append(deep_recall)
        if deep_recall:
            return _runtime(
                query="previous rollout context",
                safe_to_answer=True,
                source_id="mem-archive",
            )
        return _runtime(
            query="rollout history",
            safe_to_answer=False,
            source_id="mem-hot",
        )

    async def _fake_assembly(_backend, *, project_name, query=None):
        return _assembly_plan(query or "rollout history")

    monkeypatch.setattr("harness_mem.task_context_runtime.build_task_aware_retrieval_runtime", _fake_build)
    monkeypatch.setattr("harness_mem.task_context_runtime.assemble_context_plan", _fake_assembly)

    runtime = run(
        orchestrate_task_context(
            backend,
            query="history of the rollout",
            project_name="demo",
            current_task="what changed before the rollout",
            auto_deep_recall=True,
        )
    )

    assert calls == [False, True]
    assert runtime.effective_deep_recall is True
    assert "auto_deep_recall" in runtime.orchestration_actions
    assert "background_evidence_expansion" in runtime.orchestration_actions
    assert "obs-support" in runtime.context_plan.source_ids
    assert "obs-support" in runtime.context_plan.wake_packet.soft_include
    assert runtime.answer_ready_context["truth"][0]["summary"] == "Confirmed truth for the rollout"
    assert runtime.answer_ready_context["active_task"][0]["summary"] == "Current task handoff summary"
    assert runtime.answer_ready_context["supporting_evidence"][0]["source_id"] == "obs-support"
    assert any(
        hint["source_id"] == "obs-support"
        and hint["read_surface"] == "read_api.get_observations"
        for hint in runtime.context_plan.drilldown_hints
    )


def test_orchestrator_skips_auto_deep_recall_when_disabled(
    backend: LocalMemoryBackend,
    monkeypatch,
) -> None:
    calls: list[bool] = []

    async def _fake_build(_backend, **kwargs):
        deep_recall = bool(kwargs["deep_recall"])
        calls.append(deep_recall)
        return _runtime(
            query="rollout history",
            safe_to_answer=False,
            source_id="mem-hot",
        )

    async def _fake_assembly(_backend, *, project_name, query=None):
        return _assembly_plan(query or "rollout history")

    monkeypatch.setattr("harness_mem.task_context_runtime.build_task_aware_retrieval_runtime", _fake_build)
    monkeypatch.setattr("harness_mem.task_context_runtime.assemble_context_plan", _fake_assembly)

    runtime = run(
        orchestrate_task_context(
            backend,
            query="history of the rollout",
            project_name="demo",
            current_task="what changed before the rollout",
            auto_deep_recall=False,
        )
    )

    assert calls == [False]
    assert runtime.effective_deep_recall is False
    assert "auto_deep_recall" not in runtime.orchestration_actions
    assert "background_evidence_expansion" in runtime.orchestration_actions
    assert runtime.answer_ready_context["topic_recall"][0]["summary"] == "Topic recall summary"
