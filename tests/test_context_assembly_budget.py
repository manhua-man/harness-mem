"""Budget-helper tests for ``_apply_budget`` (Task 3.2).

``_apply_budget`` is the single shared helper every layer builder uses to cap
its candidate list at ``budget.max_entries`` and record the per-layer
``TruncationAccounting``. It is pure (no I/O), so these tests construct
``PlanEntry`` candidates in memory and assert the truncation math directly —
no ``tmp_path`` / backend is needed.

Unit cases cover the three available-vs-budget regimes
(``available < / == / > max_entries``). Property-based tests use Hypothesis to
assert the two budget-level properties named in the design "Correctness
Properties" section:

* Property 3 — Budget Cap (Req 6.1, 6.2)
* Property 4 — Truncation Accounting Invariant (Req 6.3, 6.4, 6.5)
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness_mem.context_assembly import _apply_budget
from harness_mem.core.schemas import Budget, PlanEntry
from harness_mem.core.schemas.context_assembly_plan import LAYER_ORDER


# --- helpers --------------------------------------------------------------


def _make_candidates(layer_id: str, count: int) -> list[PlanEntry]:
    """Build ``count`` minimal, distinctly-identified candidates for a layer."""
    return [
        PlanEntry(
            layer=layer_id,
            source_ids=[f"src-{i}"],
            why_included="r",
        )
        for i in range(count)
    ]


# --- unit cases: available < / == / > max_entries -------------------------


def test_apply_budget_available_less_than_max_entries() -> None:
    """available < max_entries: keep all, drop nothing (Req 6.3, 6.5)."""
    candidates = _make_candidates("L0", 2)

    layer = _apply_budget("L0", candidates, Budget(max_entries=5))

    assert layer.layer == "L0"
    assert layer.budget.max_entries == 5
    assert len(layer.entries) == 2
    assert layer.truncation.available == 2
    assert layer.truncation.included == 2
    assert layer.truncation.dropped == 0


def test_apply_budget_available_equal_to_max_entries() -> None:
    """available == max_entries: keep all, drop nothing (boundary, Req 6.5)."""
    candidates = _make_candidates("L1", 5)

    layer = _apply_budget("L1", candidates, Budget(max_entries=5))

    assert len(layer.entries) == 5
    assert layer.truncation.available == 5
    assert layer.truncation.included == 5
    assert layer.truncation.dropped == 0


def test_apply_budget_available_greater_than_max_entries() -> None:
    """available > max_entries: cap at the budget and report the drop (Req 6.2-6.4)."""
    candidates = _make_candidates("L4", 8)

    layer = _apply_budget("L4", candidates, Budget(max_entries=3))

    assert len(layer.entries) == 3
    assert layer.truncation.available == 8
    assert layer.truncation.included == 3
    assert layer.truncation.dropped == 5
    # The kept entries are the first ``max_entries`` candidates, in order.
    assert [entry.source_ids[0] for entry in layer.entries] == [
        "src-0",
        "src-1",
        "src-2",
    ]


def test_apply_budget_empty_candidates_yields_empty_layer() -> None:
    """No candidates: well-formed empty layer, zero accounting (Req 6.3)."""
    layer = _apply_budget("L2", [], Budget(max_entries=7))

    assert layer.entries == []
    assert layer.truncation.available == 0
    assert layer.truncation.included == 0
    assert layer.truncation.dropped == 0


# --- Hypothesis settings --------------------------------------------------

# The autouse ``data_dir`` fixture (tests/conftest.py) is function-scoped and
# inert for these pure tests; suppress the health check rather than reset state
# per generated example.
_PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# --- Property 3: Budget Cap -----------------------------------------------


@_PBT_SETTINGS
@given(
    layer_id=st.sampled_from(LAYER_ORDER),
    max_entries=st.integers(min_value=1, max_value=50),
    n_candidates=st.integers(min_value=0, max_value=80),
)
def test_property3_budget_cap(
    layer_id: str, max_entries: int, n_candidates: int
) -> None:
    """Validates: Requirements 6.1, 6.2 (entries never exceed the budget)."""
    budget = Budget(max_entries=max_entries)
    candidates = _make_candidates(layer_id, n_candidates)

    layer = _apply_budget(layer_id, candidates, budget)

    assert layer.budget.max_entries > 0
    assert len(layer.entries) <= layer.budget.max_entries


# --- Property 4: Truncation Accounting Invariant --------------------------


@_PBT_SETTINGS
@given(
    layer_id=st.sampled_from(LAYER_ORDER),
    max_entries=st.integers(min_value=1, max_value=50),
    n_candidates=st.integers(min_value=0, max_value=80),
)
def test_property4_truncation_accounting_invariant(
    layer_id: str, max_entries: int, n_candidates: int
) -> None:
    """Validates: Requirements 6.3, 6.4, 6.5 (accounting identities hold)."""
    budget = Budget(max_entries=max_entries)
    candidates = _make_candidates(layer_id, n_candidates)

    layer = _apply_budget(layer_id, candidates, budget)

    available = layer.truncation.available
    included = layer.truncation.included
    dropped = layer.truncation.dropped

    assert available == n_candidates
    assert included == min(available, max_entries)
    assert dropped == available - included
    assert included == len(layer.entries)
    # Req 6.5: nothing is dropped while candidates fit within the budget.
    if available <= max_entries:
        assert dropped == 0
