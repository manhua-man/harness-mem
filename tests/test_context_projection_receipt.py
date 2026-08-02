from __future__ import annotations

import pytest

from harness_mem import context_assembly
from harness_mem.context_assembly import _BudgetTrace, _apply_budget, _projection_receipt
from harness_mem.core.schemas.context_assembly_plan import (
    Budget,
    ContextAssemblyPlan,
    ContextProjectionReceipt,
    DrilldownPointer,
    LAYER_ORDER,
    Layer,
    LayerId,
    PlanEntry,
    TruncationAccounting,
)


def _entry(source_id: str, summary: str) -> PlanEntry:
    return PlanEntry(
        layer="L1",
        source_ids=[source_id],
        why_included="test",
        summary=summary,
    )


def _empty_layer(layer_id: LayerId) -> Layer:
    return Layer(
        layer=layer_id,
        budget=Budget(max_entries=1),
        truncation=TruncationAccounting(available=0, included=0, dropped=0),
    )


def test_max_chars_is_a_hard_budget_and_does_not_claim_compaction() -> None:
    traces: list[_BudgetTrace] = []
    layer = _apply_budget(
        "L1",
        [_entry("one", "abcdefgh"), _entry("two", "later")],
        Budget(max_entries=2, max_chars=5),
        budget_trace=traces,
    )

    assert [entry.summary for entry in layer.entries] == ["abcd\u2026"]
    assert layer.truncation.model_dump() == {
        "available": 2,
        "included": 1,
        "dropped": 1,
    }
    receipt = _projection_receipt(
        [layer],
        traces,
        observed_usage=None,
        source_revision="sha256:revision",
    )
    assert receipt.outcome == "truncated"
    assert receipt.summary_generated is False
    assert receipt.kept_source_ids == ["one"]
    assert receipt.evicted_source_ids == ["two"]
    assert receipt.source_revision == "sha256:revision"
    assert receipt.before_tokens >= receipt.after_tokens


def test_entry_cap_is_reported_as_eviction() -> None:
    traces: list[_BudgetTrace] = []
    layer = _apply_budget(
        "L1",
        [_entry("one", "first"), _entry("two", "second")],
        Budget(max_entries=1),
        budget_trace=traces,
    )
    receipt = _projection_receipt(
        [layer], traces, observed_usage=None, source_revision=None
    )

    assert receipt.outcome == "evicted"
    assert receipt.kept_source_ids == ["one"]
    assert receipt.evicted_source_ids == ["two"]


def test_max_chars_counts_rendered_separator_and_partial_budget_dict() -> None:
    budget = context_assembly._coerce_budget(
        {"max_chars": 6}, default_max_entries=2
    )
    traces: list[_BudgetTrace] = []
    layer = _apply_budget(
        "L1",
        [_entry("one", "abc"), _entry("two", "def")],
        budget,
        budget_trace=traces,
    )

    assert "\n".join(entry.summary for entry in layer.entries) == "abc\nd\u2026"
    assert len(traces[0].after_text) == 6


def test_observed_usage_wins_over_tokenizer_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_assembly.token_estimator, "count_tokens", lambda value: 999)
    monkeypatch.setattr(context_assembly.token_estimator, "tokenizer_kind", "tiktoken")
    traces: list[_BudgetTrace] = []
    layer = _apply_budget(
        "L1",
        [_entry("one", "first")],
        Budget(max_entries=1),
        budget_trace=traces,
    )

    receipt = _projection_receipt(
        [layer],
        traces,
        observed_usage={"inputTokens": 7, "outputTokens": 5},
        source_revision=None,
    )

    assert receipt.before_tokens == 12
    assert receipt.after_tokens == 12
    assert receipt.token_basis == "observed_usage"


def test_character_fallback_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def _count(value: str) -> int:
        context_assembly.token_estimator.tokenizer_kind = "char-heuristic"
        return len(value) // 4

    monkeypatch.setattr(context_assembly.token_estimator, "count_tokens", _count)
    traces: list[_BudgetTrace] = []
    layer = _apply_budget(
        "L1",
        [_entry("one", "abcdefgh")],
        Budget(max_entries=1),
        budget_trace=traces,
    )

    receipt = _projection_receipt(
        [layer], traces, observed_usage=None, source_revision=None
    )

    assert receipt.token_basis == "character_estimate"
    assert receipt.after_tokens == 2


def test_receipt_round_trip_keeps_content_free_drilldown() -> None:
    pointer = DrilldownPointer(
        source_id="observation-1",
        read_surface="read_api.get_observations",
        locator={"source_revision": "sha256:one", "session_id": "session-1"},
    )
    layer = _empty_layer("L4")
    layer.entries = [
        PlanEntry(
            layer="L4",
            source_ids=["observation-1"],
            why_included="evidence",
            drilldown=pointer,
        )
    ]
    receipt = ContextProjectionReceipt(
        source_revision="sha256:one",
        before_tokens=10,
        after_tokens=10,
        kept_source_ids=["observation-1"],
        token_basis="tokenizer_estimate",
        drilldown=[pointer],
    )
    plan = ContextAssemblyPlan(
        project_name="demo",
        layers=[
            _empty_layer("L0"),
            _empty_layer("L1"),
            _empty_layer("L2"),
            _empty_layer("L3"),
            layer,
        ],
        projection_receipt=receipt,
    )

    restored = ContextAssemblyPlan.from_dict(plan.to_dict())

    assert restored.projection_receipt == receipt
    assert context_assembly._receipt_source_revision([layer], None) == "sha256:one"
    assert restored.projection_receipt is not None
    assert restored.projection_receipt.drilldown[0].locator == {
        "source_revision": "sha256:one",
        "session_id": "session-1",
    }


def test_legacy_plan_without_receipt_still_deserializes() -> None:
    payload = ContextAssemblyPlan(
        project_name="demo",
        layers=[_empty_layer(layer_id) for layer_id in LAYER_ORDER],
    ).to_dict()
    payload.pop("projection_receipt")

    restored = ContextAssemblyPlan.from_dict(payload)

    assert restored.projection_receipt is None


def test_compacted_requires_an_actual_summary() -> None:
    with pytest.raises(ValueError, match="requires summary_generated=true"):
        ContextProjectionReceipt(
            before_tokens=10,
            after_tokens=5,
            token_basis="tokenizer_estimate",
            outcome="compacted",
        )
