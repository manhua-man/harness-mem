"""Schema tests for ``ContextAssemblyPlan`` and its nested records (Task 1.2).

These tests are pure in-memory: they exercise ``to_dict`` / ``from_dict``,
the empty-``entries`` default (Req 1.7), the explicit invalid-``layer`` guard
(Req 1.8), ``source_ids`` min-length rejection (Req 8.1), and nested-record
serialization. The schema performs no I/O (Req 1.9), so no ``tmp_path`` is
needed here — the autouse ``data_dir`` fixture from ``tests/conftest.py`` still
reroutes any incidental writes away from ``~/.harness-mem/``.

Property-based tests use Hypothesis to assert the four schema-level properties
named in the design "Correctness Properties" section:

* Property 1 — Round-Trip Serialization (Req 1.5, 1.6, 8.4)
* Property 2 — Layer Order and Completeness (Req 1.2, 1.3)
* Property 5 — Source-Id Presence (Req 8.1)
* Property 9 — Layer Literal Validation (Req 1.8)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from harness_mem.core.schemas import (
    LAYER_ORDER,
    Budget,
    ContextAssemblyPlan,
    DrilldownPointer,
    Layer,
    PlanEntry,
    TruncationAccounting,
)


# --- shared assertions ----------------------------------------------------


def _assert_plan_equal(
    restored: ContextAssemblyPlan, original: ContextAssemblyPlan
) -> None:
    """Field-by-field equality, including nested layers/entries/budgets."""
    assert restored.project_name == original.project_name
    assert restored.query == original.query
    assert restored.created_at == original.created_at
    assert [layer.layer for layer in restored.layers] == [
        layer.layer for layer in original.layers
    ]
    for r_layer, o_layer in zip(restored.layers, original.layers):
        assert r_layer.layer == o_layer.layer
        assert r_layer.budget == o_layer.budget
        assert r_layer.truncation == o_layer.truncation
        assert len(r_layer.entries) == len(o_layer.entries)
        for r_entry, o_entry in zip(r_layer.entries, o_layer.entries):
            assert r_entry.layer == o_entry.layer
            assert r_entry.source_ids == o_entry.source_ids
            assert r_entry.why_included == o_entry.why_included
            assert r_entry.summary == o_entry.summary
            assert r_entry.truth_status == o_entry.truth_status
            assert r_entry.drilldown == o_entry.drilldown


def _fully_populated_plan() -> ContextAssemblyPlan:
    """A plan touching every nested record type and non-default field."""
    base = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    l0 = Layer(
        layer="L0",
        entries=[
            PlanEntry(
                layer="L0",
                source_ids=["profile-1"],
                why_included="identity:active_project",
                summary="harness-mem",
            )
        ],
        budget=Budget(max_entries=3),
        truncation=TruncationAccounting(available=1, included=1, dropped=0),
    )
    l1 = Layer(
        layer="L1",
        entries=[
            PlanEntry(
                layer="L1",
                source_ids=["rule-1"],
                why_included="essential:confirmed_rule",
                summary="always write a failing test first",
                truth_status="confirmed_current",
            ),
            PlanEntry(
                layer="L1",
                source_ids=["entry-9"],
                why_included="essential:high_confidence_truth",
                summary="storage is sqlite",
            ),
        ],
        # max_chars exercised here so the optional Budget field round-trips.
        budget=Budget(max_entries=7, max_chars=4096),
        # dropped > 0 exercises the non-trivial truncation accounting path.
        truncation=TruncationAccounting(available=5, included=2, dropped=3),
    )
    l2 = Layer(
        layer="L2",
        entries=[
            PlanEntry(
                layer="L2",
                source_ids=["handoff-3"],
                why_included="active:recent_handoff",
                summary="resume task X",
            )
        ],
        budget=Budget(max_entries=7),
        truncation=TruncationAccounting(available=1, included=1, dropped=0),
    )
    l3 = Layer(
        layer="L3",
        entries=[
            PlanEntry(
                layer="L3",
                source_ids=["entry-42"],
                why_included="topic_recall:search_memory",
                summary="matched the query",
            )
        ],
        budget=Budget(max_entries=10),
        truncation=TruncationAccounting(available=1, included=1, dropped=0),
    )
    l4 = Layer(
        layer="L4",
        entries=[
            PlanEntry(
                layer="L4",
                source_ids=["obs-1"],
                why_included="evidence:supports_L1",
                drilldown=DrilldownPointer(
                    source_id="obs-1",
                    read_surface="read_api.get_observations",
                    locator={"session_id": "sess-1", "project_name": "harness-mem"},
                ),
                truth_status="historical",
            )
        ],
        budget=Budget(max_entries=20),
        truncation=TruncationAccounting(available=1, included=1, dropped=0),
    )
    return ContextAssemblyPlan(
        project_name="harness-mem",
        query="how does wake work",
        layers=[l0, l1, l2, l3, l4],
        created_at=base,
    )


# --- Req 1.7: absent ``entries`` defaults to an empty list ----------------


def test_layer_from_dict_defaults_absent_entries_to_empty_list() -> None:
    """Validates: Requirements 1.7 (empty-``entries`` default)."""
    layer = Layer.from_dict(
        {
            "layer": "L1",
            "budget": {"max_entries": 7, "max_chars": None},
            "truncation": {"available": 0, "included": 0, "dropped": 0},
        }
    )

    assert layer.entries == []


def test_layer_from_dict_treats_null_entries_as_empty_list() -> None:
    """Validates: Requirements 1.7 (a null ``entries`` value also defaults)."""
    layer = Layer.from_dict(
        {
            "layer": "L0",
            "entries": None,
            "budget": {"max_entries": 3},
            "truncation": {"available": 0, "included": 0, "dropped": 0},
        }
    )

    assert layer.entries == []


# --- Req 1.8: invalid ``layer`` literal raises a naming ValueError --------


def test_layer_from_dict_rejects_invalid_layer_literal() -> None:
    """Validates: Requirements 1.8 (Layer field + value surfaced in error)."""
    with pytest.raises(ValueError) as exc_info:
        Layer.from_dict(
            {
                "layer": "L9",
                "budget": {"max_entries": 7},
                "truncation": {"available": 0, "included": 0, "dropped": 0},
            }
        )

    message = str(exc_info.value)
    assert "layer" in message
    assert "L9" in message


def test_plan_entry_from_dict_rejects_invalid_layer_literal() -> None:
    """Validates: Requirements 1.8 (PlanEntry field + value surfaced)."""
    with pytest.raises(ValueError) as exc_info:
        PlanEntry.from_dict(
            {
                "layer": "BAD",
                "source_ids": ["s1"],
                "why_included": "topic_recall:search_memory",
            }
        )

    message = str(exc_info.value)
    assert "layer" in message
    assert "BAD" in message


# --- Req 8.1: ``source_ids`` requires at least one element ----------------


def test_plan_entry_rejects_empty_source_ids() -> None:
    """Validates: Requirements 8.1 (min_length=1 on ``source_ids``)."""
    with pytest.raises(ValidationError):
        PlanEntry(
            layer="L0",
            source_ids=[],
            why_included="identity:active_project",
        )


def test_plan_entry_from_dict_rejects_empty_source_ids() -> None:
    """Validates: Requirements 8.1 (rejection also holds via ``from_dict``)."""
    with pytest.raises(ValidationError):
        PlanEntry.from_dict(
            {
                "layer": "L0",
                "source_ids": [],
                "why_included": "identity:active_project",
            }
        )


# --- Req 1.5 / 1.6: nested-record serialization round-trip ----------------


def test_nested_record_serialization_round_trip() -> None:
    """Validates: Requirements 1.5, 1.6, 8.4 (nested records survive)."""
    original = _fully_populated_plan()

    restored = ContextAssemblyPlan.from_dict(original.to_dict())

    _assert_plan_equal(restored, original)

    # Spot-check that the nested L4 drilldown survived intact.
    drilldown = restored.layer("L4").entries[0].drilldown
    assert drilldown is not None
    assert drilldown.source_id == "obs-1"
    assert drilldown.read_surface == "read_api.get_observations"
    assert drilldown.locator == {
        "session_id": "sess-1",
        "project_name": "harness-mem",
    }
    # And that ISO 8601 datetime serialization is the on-the-wire form (Req 1.5).
    assert isinstance(original.to_dict()["created_at"], str)
    datetime.fromisoformat(original.to_dict()["created_at"])


# --- Hypothesis strategies for arbitrary valid plans ----------------------

# Non-empty, whitespace-free tokens for ids / reasons (satisfy min_length=1).
_ids = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=24,
)


@st.composite
def _drilldowns(draw: st.DrawFn) -> DrilldownPointer:
    return DrilldownPointer(
        source_id=draw(_ids),
        read_surface=draw(
            st.sampled_from(
                ["read_api.get_observations", "read_api.timeline_observations"]
            )
        ),
        locator=draw(st.dictionaries(_ids, st.text(max_size=16), max_size=3)),
    )


@st.composite
def _plan_entries(draw: st.DrawFn, layer_id: str) -> PlanEntry:
    # Drilldowns are an L4-only concern per the design; other layers omit them.
    drilldown = None
    if layer_id == "L4":
        drilldown = draw(st.one_of(st.none(), _drilldowns()))
    return PlanEntry(
        layer=layer_id,
        source_ids=draw(st.lists(_ids, min_size=1, max_size=4)),
        why_included=draw(_ids),
        summary=draw(st.text(max_size=40)),
        drilldown=drilldown,
        truth_status=draw(
            st.sampled_from(["confirmed_current", "pending", "historical"])
        ),
    )


@st.composite
def _layers(draw: st.DrawFn, layer_id: str) -> Layer:
    max_entries = draw(st.integers(min_value=1, max_value=8))
    # "random within-budget entry counts": never exceed the layer budget.
    n_entries = draw(st.integers(min_value=0, max_value=max_entries))
    entries = draw(
        st.lists(_plan_entries(layer_id), min_size=n_entries, max_size=n_entries)
    )
    dropped = draw(st.integers(min_value=0, max_value=5))
    return Layer(
        layer=layer_id,
        entries=entries,
        budget=Budget(
            max_entries=max_entries,
            max_chars=draw(
                st.one_of(st.none(), st.integers(min_value=1, max_value=10_000))
            ),
        ),
        truncation=TruncationAccounting(
            available=n_entries + dropped,
            included=n_entries,
            dropped=dropped,
        ),
    )


@st.composite
def _plans(draw: st.DrawFn) -> ContextAssemblyPlan:
    return ContextAssemblyPlan(
        project_name=draw(st.text(max_size=24)),
        query=draw(st.one_of(st.none(), st.text(max_size=24))),
        layers=[draw(_layers(layer_id)) for layer_id in LAYER_ORDER],
        created_at=draw(st.datetimes(timezones=st.just(timezone.utc))),
    )


# Function-scoped autouse fixtures (data_dir/monkeypatch) are inert for these
# pure tests; suppress the health check rather than reset state per example.
_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# --- Property 1: Round-Trip Serialization ---------------------------------


@_PBT_SETTINGS
@given(plan=_plans())
def test_property1_round_trip_serialization(plan: ContextAssemblyPlan) -> None:
    """Validates: Requirements 1.5, 1.6, 8.4 (round-trip is field-stable)."""
    restored = ContextAssemblyPlan.from_dict(plan.to_dict())

    _assert_plan_equal(restored, plan)


# --- Property 2: Layer Order and Completeness -----------------------------


@_PBT_SETTINGS
@given(plan=_plans())
def test_property2_layer_order_and_completeness(plan: ContextAssemblyPlan) -> None:
    """Validates: Requirements 1.2, 1.3 (exactly five layers, fixed order)."""
    expected = list(LAYER_ORDER)

    assert [layer.layer for layer in plan.layers] == expected

    restored = ContextAssemblyPlan.from_dict(plan.to_dict())
    assert [layer.layer for layer in restored.layers] == expected


# --- Property 5: Source-Id Presence ---------------------------------------


@_PBT_SETTINGS
@given(plan=_plans())
def test_property5_source_id_presence(plan: ContextAssemblyPlan) -> None:
    """Validates: Requirements 8.1 (every entry has >=1 non-empty source id)."""
    for layer in plan.layers:
        for entry in layer.entries:
            assert len(entry.source_ids) >= 1
            for source_id in entry.source_ids:
                assert isinstance(source_id, str)
                assert source_id != ""


# --- Property 9: Layer Literal Validation ---------------------------------


@_PBT_SETTINGS
@given(layer_id=st.sampled_from(LAYER_ORDER))
def test_property9_accepts_in_set_layer_literal(layer_id: str) -> None:
    """Validates: Requirements 1.8 (in-set literals are accepted)."""
    entry = PlanEntry.from_dict(
        {
            "layer": layer_id,
            "source_ids": ["s1"],
            "why_included": "topic_recall:search_memory",
        }
    )

    assert entry.layer == layer_id


@_PBT_SETTINGS
@given(bad_layer=st.text(max_size=8).filter(lambda s: s not in LAYER_ORDER))
def test_property9_rejects_out_of_set_layer_literal(bad_layer: str) -> None:
    """Validates: Requirements 1.8 (out-of-set literals raise field+value)."""
    with pytest.raises(ValueError) as exc_info:
        PlanEntry.from_dict(
            {
                "layer": bad_layer,
                "source_ids": ["s1"],
                "why_included": "topic_recall:search_memory",
            }
        )

    message = str(exc_info.value)
    assert "layer" in message
    assert repr(bad_layer) in message
