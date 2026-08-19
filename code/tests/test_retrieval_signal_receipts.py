from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import harness_mem.commands.wake as wake_module
import harness_mem.mcp.read_feedback_handlers as feedback_handlers
import harness_mem.mcp.read_query_support as query_support
from harness_mem.core.schemas import KnowledgeEntry


@pytest.mark.parametrize(
    "arguments",
    [
        {"project_name": "", "surface": "search_memory", "outcome": "used", "source_ids": ["one"]},
        {"project_name": "demo", "surface": "", "outcome": "used", "source_ids": ["one"]},
        {"project_name": "demo", "surface": "search_memory", "outcome": "unknown", "source_ids": ["one"]},
        {"project_name": "demo", "surface": "search_memory", "outcome": "used", "source_ids": []},
    ],
)
def test_context_outcome_rejects_invalid_arguments_without_mutating_truth(arguments) -> None:
    receipt = feedback_handlers.tool_record_context_outcome(**arguments)

    assert receipt["success"] is False
    assert receipt["truth_mutated"] is False


def test_context_outcome_reports_partial_signal_write_as_degraded(monkeypatch) -> None:
    async def record_signal(_backend, *, target_id, **_kwargs):
        return None if target_id == "source-2" else SimpleNamespace(id="signal-1")

    monkeypatch.setattr(feedback_handlers, "record_retrieval_signal", record_signal)

    receipt = feedback_handlers.tool_record_context_outcome(
        project_name="demo",
        surface="search_memory",
        outcome="ignored",
        source_ids=["source-1", "source-2"],
        _backend=object(),
    )

    assert receipt["success"] is False
    assert receipt["recorded_count"] == 1
    assert receipt["failed_count"] == 1
    assert receipt["signal_ids"] == ["signal-1"]
    assert receipt["failed_source_ids"] == ["source-2"]
    assert receipt["degraded_reason"] == "signal_write_failed"
    assert receipt["truth_mutated"] is False


def test_search_signal_failure_returns_content_free_degraded_receipt(
    monkeypatch,
) -> None:
    async def fail_signal(*_args, **_kwargs):
        return None

    monkeypatch.setattr(query_support, "record_retrieval_signal", fail_signal)
    receipt = asyncio.run(
        query_support._record_search_quality_signals(
            object(),
            project_name="demo",
            query="not persisted",
            entries=[SimpleNamespace(id="entry-1")],
            response=SimpleNamespace(results=[object()]),
            context_plan=SimpleNamespace(
                context_sufficiency=SimpleNamespace(safe_to_answer=True)
            ),
            retrieval_id="retrieval-test",
        )
    )

    assert receipt == {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": "retrieval-test",
        "surface": "search_memory",
        "attempted": 1,
        "recorded": 0,
        "failed": 1,
        "state": "degraded",
        "source_ids": [],
        "content_recorded": False,
    }


def test_current_knowledge_search_hit_keeps_knowledge_target_kind(
    monkeypatch,
) -> None:
    recorded = []

    async def capture_signal(*_args, **kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(id="signal-1")

    monkeypatch.setattr(query_support, "record_retrieval_signal", capture_signal)
    entry = KnowledgeEntry(
        id="knowledge-1",
        project_name="demo",
        module_path=["retrieval"],
        title="Current knowledge",
        statement="Current knowledge keeps its target kind through feedback.",
    )
    receipt = asyncio.run(
        query_support._record_search_quality_signals(
            object(),
            project_name="demo",
            query="current",
            entries=[entry],
            response=SimpleNamespace(results=[entry]),
            context_plan=None,
            retrieval_id="retrieval-current",
        )
    )

    assert receipt["source_ids"] == ["knowledge-1"]
    assert recorded[0]["target_kind"] == "knowledge_entry"


def test_wake_signal_failure_does_not_fail_context_and_is_reported(
    monkeypatch,
) -> None:
    class Store:
        async def touch_memory_entry(self, _record_id: str) -> None:
            return None

        async def touch_confirmed_rule(self, _record_id: str) -> None:
            return None

    class Plan:
        project_name = "demo"

        def layer(self, _layer_id: str):
            return object()

    entry = SimpleNamespace(
        why_included="essential:high_confidence_truth",
        source_ids=["entry-1"],
    )

    async def fail_signal(*_args, **_kwargs):
        return None

    monkeypatch.setattr(wake_module, "select_rendered_entries", lambda _layer: [entry])
    monkeypatch.setattr(wake_module, "record_retrieval_signal", fail_signal)
    backend = SimpleNamespace(structured_store=Store())

    receipt = asyncio.run(
        wake_module._apply_surface_side_effects(
            backend,
            Plan(),
            retrieval_id="retrieval-wake-test",
        )
    )

    assert receipt["state"] == "degraded"
    assert receipt["attempted"] == 1
    assert receipt["recorded"] == 0
    assert receipt["failed"] == 1
    assert receipt["source_ids"] == []
    assert receipt["content_recorded"] is False
