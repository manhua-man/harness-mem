from __future__ import annotations

import asyncio
from types import SimpleNamespace

import harness_mem.commands.wake as wake_module
import harness_mem.mcp.read_query_support as query_support


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
