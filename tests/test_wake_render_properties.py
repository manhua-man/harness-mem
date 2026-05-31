"""Property-based tests for the pure Wake_Renderer (``wake_render.py``).

The Wake_Renderer is a pure function of a :class:`ContextAssemblyPlan`, so its
universal invariants are tested directly against in-memory plans built by
Hypothesis strategies — no backend, store, or ``tmp_path`` is required, which
keeps the >=100-iteration minimum fast.

Each property test is a SINGLE property-based test referencing its design
property by number.
"""

from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness_mem.commands.wake import _disclosure_level_for_plan
from harness_mem.commands.wake_render import (
    EMPTY_STATE,
    LAYER_HEADERS,
    NO_SOURCE_ID,
    SURFACED_LAYERS,
    TRUTH_LAYERS,
    render_entry_line,
    render_source_id_display,
    render_truncation_indicator,
    render_truth_status_label,
    render_wake_plan,
    select_rendered_entries,
)
from harness_mem.core.schemas.context_assembly_plan import (
    Budget,
    ContextAssemblyPlan,
    Layer,
    LayerId,
    PlanEntry,
    TruncationAccounting,
    TruthStatus,
)

# The cold-start tiers wake surfaces; this is what Property 4 ranges over.
_SURFACED_LAYERS: tuple[LayerId, ...] = ("L0", "L1", "L2")

# The autouse ``data_dir`` fixture (tests/conftest.py) is function-scoped and
# inert for these pure tests; suppress the health check rather than reset state
# per generated example.
_PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _make_budget(max_entries: int) -> Budget:
    """Build a ``Budget`` for a given cap, allowing ``max_entries == 0``.

    The v2.5.0 ``Budget`` schema enforces ``max_entries > 0`` (``Field(gt=0)``),
    so a zero cap — which the renderer must still handle defensively (Req 2.4) —
    is constructed via ``model_construct`` to bypass validation, exactly the
    "build ``Layer`` directly" path the task calls for.
    """
    if max_entries == 0:
        return Budget.model_construct(max_entries=0, max_chars=None)
    return Budget(max_entries=max_entries)


@st.composite
def _surfaced_layer(draw: st.DrawFn, layer_id: LayerId) -> tuple[Layer, list[PlanEntry], int]:
    """Build one surfaced ``Layer`` plus its expected eligible list and cap.

    The generator builds entries with mixed ``truth_status`` so the *eligible*
    list — truth-filtered for L1/L2, unfiltered for L0 — mirrors exactly what
    ``select_rendered_entries`` filters on. ``max_entries`` is drawn to span
    ``< / == / >`` the eligible count and ``== 0``.

    Returns the layer, the eligible entries (in plan order), and the cap.
    """
    is_truth_layer = layer_id in TRUTH_LAYERS

    n_entries = draw(st.integers(min_value=0, max_value=8))
    entries: list[PlanEntry] = []
    for i in range(n_entries):
        status = draw(
            st.sampled_from(["confirmed_current", "historical", "pending"])
        )
        entries.append(
            PlanEntry(
                layer=layer_id,
                source_ids=[f"{layer_id}-src-{i}"],
                why_included="reason",
                summary=f"summary-{layer_id}-{i}",
                truth_status=status,
            )
        )

    # Eligible mirrors the renderer's filter: L1/L2 keep only confirmed_current,
    # L0 keeps everything in plan order.
    if is_truth_layer:
        eligible = [e for e in entries if e.truth_status == "confirmed_current"]
    else:
        eligible = list(entries)

    # Span max_entries across < / == / > the eligible count, plus 0.
    max_entries = draw(st.integers(min_value=0, max_value=len(eligible) + 3))

    layer = Layer(
        layer=layer_id,
        entries=entries,
        budget=_make_budget(max_entries),
        # Truncation is unused by select_rendered_entries; keep it well-formed.
        truncation=TruncationAccounting(available=0, included=0, dropped=0),
    )
    return layer, eligible, max_entries


# Feature: v251-wake-renderer-hardening, Property 4: Per-Layer Budget Cap Is a Plan-Order Prefix
@_PBT_SETTINGS
@given(data=st.data())
def test_property4_per_layer_budget_cap(data: st.DataObject) -> None:
    """Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.

    For any surfaced layer the selected entries equal the first
    ``min(eligible_count, max_entries)`` eligible entries in plan order, so the
    selected count never exceeds ``max_entries``, equals ``max_entries`` when
    eligible entries exceed it, equals the eligible count otherwise, and is zero
    when ``max_entries == 0`` — and each layer's cap is applied independently.
    """
    built = {
        layer_id: data.draw(_surfaced_layer(layer_id), label=layer_id)
        for layer_id in _SURFACED_LAYERS
    }

    # Independence: place all surfaced layers in one plan and select each from
    # the plan, so one layer's cap can neither consume nor contribute to
    # another's (Req 2.5). Standalone selection must match plan-based selection.
    plan = ContextAssemblyPlan(
        project_name="proj",
        query=None,
        layers=[built[layer_id][0] for layer_id in _SURFACED_LAYERS],
    )

    for layer_id in _SURFACED_LAYERS:
        layer, eligible, max_entries = built[layer_id]
        expected = eligible[:max_entries]

        selected = select_rendered_entries(layer)
        # Selecting via the shared plan yields the same result — caps are
        # independent across layers (Req 2.5, 2.6).
        selected_from_plan = select_rendered_entries(plan.layer(layer_id))

        # Req 2.2/2.3/2.6: selection is the plan-order prefix of eligible.
        assert selected == expected
        assert selected_from_plan == expected

        # Req 2.1: never more than the cap.
        assert len(selected) <= max_entries

        # Req 2.2 vs 2.3: equals the cap when eligible exceeds it, else the
        # eligible count.
        if len(eligible) > max_entries:
            assert len(selected) == max_entries
        else:
            assert len(selected) == len(eligible)

        # Req 2.4: a zero cap renders nothing.
        if max_entries == 0:
            assert selected == []


# All truth_status values a PlanEntry can legally carry. The schema default is
# "confirmed_current", so the "absent" case is exercised by entries that simply
# default to confirmed_current; non-current truth is exercised by "historical"
# and "pending". The Literal-typed field admits no other values, so there is no
# further "non-confirmed_current" value to construct.
_MIXED_TRUTH_STATUSES = ("confirmed_current", "historical", "pending")


@st.composite
def _truth_layer_mixed_status(draw: st.DrawFn, layer_id: LayerId) -> Layer:
    """Build an L1/L2 layer with mixed ``truth_status`` and a non-hiding budget.

    Each entry draws a status from confirmed_current / historical / pending so
    the layer mixes current and non-current truth. ``max_entries`` is drawn at
    or above the entry count so the budget cap can never hide the truth filter:
    any non-current entry surviving selection is a filter failure, not a cap.
    """
    n_entries = draw(st.integers(min_value=0, max_value=8))
    entries: list[PlanEntry] = []
    for i in range(n_entries):
        status = draw(st.sampled_from(_MIXED_TRUTH_STATUSES))
        entries.append(
            PlanEntry(
                layer=layer_id,
                source_ids=[f"{layer_id}-src-{i}"],
                why_included="reason",
                summary=f"summary-{layer_id}-{i}",
                truth_status=status,
            )
        )

    # Budget at or above the entry count: the cap cannot hide the truth filter.
    max_entries = draw(st.integers(min_value=n_entries, max_value=n_entries + 3))

    return Layer(
        layer=layer_id,
        entries=entries,
        budget=_make_budget(max_entries),
        truncation=TruncationAccounting(available=0, included=0, dropped=0),
    )


# Feature: v251-wake-renderer-hardening, Property 6: Confirmed-Current-Only in L1 and L2
@_PBT_SETTINGS
@given(data=st.data())
def test_property6_confirmed_current_only_in_l1_l2(data: st.DataObject) -> None:
    """Validates: Requirements 4.1, 4.2, 4.5, 5.1, 5.2.

    For any L1/L2 layer carrying mixed ``truth_status`` values, every entry the
    renderer selects has ``truth_status == "confirmed_current"`` and no
    ``historical`` / ``pending`` / otherwise-non-current entry is selected
    there. The budget is drawn at or above the entry count so the cap cannot
    hide the filter, so the selection equals exactly the layer's
    confirmed-current entries in plan order.
    """
    for layer_id in sorted(TRUTH_LAYERS):
        layer = data.draw(_truth_layer_mixed_status(layer_id), label=layer_id)

        selected = select_rendered_entries(layer)

        # Req 4.1 / 5.1: every selected entry is confirmed-current truth.
        assert all(entry.truth_status == "confirmed_current" for entry in selected)

        # Req 4.2 / 4.5 / 5.2: no non-confirmed_current entry is selected here.
        assert not any(entry.truth_status != "confirmed_current" for entry in selected)

        # The budget does not hide the filter: the selection equals exactly the
        # layer's confirmed-current entries, in plan order.
        expected = [
            entry for entry in layer.entries if entry.truth_status == "confirmed_current"
        ]
        assert selected == expected


@st.composite
def _entry_with_status(draw: st.DrawFn, truth_status: TruthStatus) -> PlanEntry:
    """Build a ``PlanEntry`` carrying ``truth_status`` with all other fields varied.

    ``render_truth_status_label`` takes only ``truth_status``, so "holding other
    fields fixed" is demonstrated by varying every *other* ``PlanEntry`` field
    (layer, source_ids, why_included, summary) while pinning the status: the
    label must depend on the status argument alone.
    """
    layer_id = draw(st.sampled_from(["L0", "L1", "L2", "L3", "L4"]))
    source_ids = draw(
        st.lists(st.text(max_size=12), min_size=1, max_size=3)
    )
    summary = draw(st.text(max_size=20))
    why = draw(st.text(min_size=1, max_size=20))
    return PlanEntry(
        layer=layer_id,
        source_ids=source_ids,
        why_included=why,
        summary=summary,
        truth_status=truth_status,
    )


# Feature: v251-wake-renderer-hardening, Property 7: Truth-Status Label Determined Solely by truth_status and Distinguishes Historical
@_PBT_SETTINGS
@given(data=st.data())
def test_property7_truth_status_label(data: st.DataObject) -> None:
    """Validates: Requirements 4.3, 4.4.

    The rendered truth-status label is a pure function of ``truth_status``
    alone: holding the status fixed while varying every other ``PlanEntry``
    field leaves the label unchanged, the same status always yields the same
    label (determinism), and the three distinct statuses map to three distinct
    labels so the label changes deterministically with the status. The
    ``historical`` label is a non-empty, visible marker distinct from the
    ``confirmed_current`` label.
    """
    status_a = data.draw(st.sampled_from(_MIXED_TRUTH_STATUSES), label="status_a")
    status_b = data.draw(st.sampled_from(_MIXED_TRUTH_STATUSES), label="status_b")

    # Two entries sharing ``status_a`` but with independently varied other
    # fields: the label must ignore those other fields entirely (Req 4.4).
    entry_a1 = data.draw(_entry_with_status(status_a), label="entry_a1")
    entry_a2 = data.draw(_entry_with_status(status_a), label="entry_a2")

    label_a1 = render_truth_status_label(entry_a1.truth_status)
    label_a2 = render_truth_status_label(entry_a2.truth_status)

    # Unchanged by other fields + deterministic: same status -> same label,
    # regardless of how the rest of the entry varies, on every call.
    assert label_a1 == label_a2
    assert render_truth_status_label(status_a) == label_a1

    # Pure function of ``truth_status``: equal statuses yield equal labels and
    # differing statuses yield differing labels, so the label changes
    # deterministically with the status across its three-value domain (Req 4.4).
    label_b = render_truth_status_label(status_b)
    if status_a == status_b:
        assert label_a1 == label_b
    else:
        assert label_a1 != label_b

    # The ``historical`` label is non-empty, visible, and distinct from the
    # ``confirmed_current`` label (Req 4.3).
    historical_label = render_truth_status_label("historical")
    confirmed_label = render_truth_status_label("confirmed_current")
    assert historical_label != ""
    assert historical_label.strip() != ""
    assert historical_label != confirmed_label


# Source-id characters span unicode, CJK, emoji, punctuation, and other special
# characters, plus long strings — but exclude the renderer's own framing glyphs
# (``⟨`` / ``⟩`` / ``📍``) and line breaks so the "exactly one Source_Id_Display"
# count can never be spoofed by generated content. Property 5 is about *verbatim
# inclusion*, not the alphabet, so this exclusion does not weaken it: any id the
# generator emits is reproduced character-for-character by the renderer.
_SOURCE_ID_CHARS = st.characters(
    exclude_characters="⟨⟩📍\n\r",
    exclude_categories=("Cs",),
)


def _source_id_text() -> st.SearchStrategy[str]:
    """One non-empty source id — short, long, unicode, or special-character."""
    return st.text(_SOURCE_ID_CHARS, min_size=1, max_size=200)


@st.composite
def _source_ids(draw: st.DrawFn) -> list[str]:
    """Build a ``PlanEntry.source_ids`` list spanning the Property 5 input space.

    Covers a single id, many ids, all-empty-string ids, and a mixed list where
    some elements are empty. ``PlanEntry.source_ids`` has ``min_length=1``, so
    every branch yields at least one element; the all-empty branch is a list of
    one-or-more empty strings (the explicit no-source-id case, Req 3.6).
    """
    n = draw(st.integers(min_value=1, max_value=5))
    kind = draw(st.sampled_from(["single", "many", "all_empty", "mixed"]))
    if kind == "all_empty":
        return [""] * n
    if kind == "single":
        return [draw(_source_id_text())]
    if kind == "many":
        return [draw(_source_id_text()) for _ in range(max(n, 2))]
    # mixed: each element is independently empty or a generated id.
    return [draw(st.one_of(st.just(""), _source_id_text())) for _ in range(n)]


# Feature: v251-wake-renderer-hardening, Property 5: Source-Id Display Fidelity
@_PBT_SETTINGS
@given(
    source_ids=_source_ids(),
    summary=st.text(_SOURCE_ID_CHARS, max_size=40),
    truth_status=st.sampled_from(_MIXED_TRUTH_STATUSES),
    layer_id=st.sampled_from(["L0", "L1", "L2"]),
)
def test_property5_source_id_display_fidelity(
    source_ids: list[str],
    summary: str,
    truth_status: TruthStatus,
    layer_id: LayerId,
) -> None:
    """Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6.

    For any rendered Wake_Rendered_Entry, the output carries exactly one
    Source_Id_Display for that entry; the display lists every value of the
    originating ``source_ids`` field character-for-character and in
    ``source_ids`` order (showing the explicit no-source-id indication when
    every value is empty); and the entry additionally carries the ``📍``
    provenance marker.
    """
    entry = PlanEntry(
        layer=layer_id,
        source_ids=source_ids,
        why_included="reason",
        summary=summary,
        truth_status=truth_status,
    )

    non_empty = [source_id for source_id in source_ids if source_id]
    expected_inner = ", ".join(non_empty) if non_empty else NO_SOURCE_ID
    expected_display = f"⟨src: {expected_inner}⟩"

    display = render_source_id_display(source_ids)

    # Req 3.1-3.4 / 3.6: the display is exactly the verbatim, in-order list of
    # non-empty ids (or the explicit no-source-id indication when all empty).
    assert display == expected_display

    if non_empty:
        # Req 3.2/3.3/3.4: every non-empty id appears verbatim, joined in order.
        assert ", ".join(non_empty) in display
        for source_id in non_empty:
            assert source_id in display
    else:
        # Req 3.6: explicit no-source-id indication when every value is empty.
        assert NO_SOURCE_ID in display

    entry_line = render_entry_line(entry)

    # Req 3.1: exactly one Source_Id_Display per rendered entry. Generated
    # content never contains ``⟨`` / ``⟩``, so the renderer's own framing is the
    # only ``⟨src:`` marker — counting it (and the full display) yields one.
    assert entry_line.count("⟨src:") == 1
    assert entry_line.count(expected_display) == 1

    # Req 3.5: the 📍 provenance marker is rendered for the entry.
    assert "📍" in entry_line


@st.composite
def _layer_with_decoupled_truncation(draw: st.DrawFn) -> Layer:
    """Build a surfaced ``Layer`` whose accounting is decoupled from its entries.

    ``render_truncation_indicator`` must source its counts from
    ``layer.truncation`` (Req 6.3), never recompute them from the rendered entry
    count. To prove that, the entry count is drawn *independently* of the
    accounting's ``dropped`` value, and ``dropped`` is drawn to span both the
    no-truncation case (``dropped == 0``) and the truncation case
    (``dropped > 0``). ``TruncationAccounting`` constrains every field to
    ``>= 0`` (schema ``Field(ge=0)``), so all drawn values stay in range.
    """
    layer_id = draw(st.sampled_from(_SURFACED_LAYERS))

    # Entry count is independent of the accounting counts below.
    n_entries = draw(st.integers(min_value=0, max_value=6))
    entries = [
        PlanEntry(
            layer=layer_id,
            source_ids=[f"{layer_id}-src-{i}"],
            why_included="reason",
            summary=f"summary-{layer_id}-{i}",
            truth_status="confirmed_current",
        )
        for i in range(n_entries)
    ]

    # Accounting decoupled from len(entries): all fields >= 0 (schema), and
    # ``dropped`` spans 0 (no truncation) and > 0 (truncation). ``available`` /
    # ``included`` are free non-negative counts, deliberately unrelated to the
    # entry count so the indicator cannot be a recomputation of it.
    available = draw(st.integers(min_value=0, max_value=50))
    included = draw(st.integers(min_value=0, max_value=50))
    dropped = draw(st.integers(min_value=0, max_value=50))

    return Layer(
        layer=layer_id,
        entries=entries,
        budget=_make_budget(draw(st.integers(min_value=1, max_value=10))),
        truncation=TruncationAccounting(
            available=available, included=included, dropped=dropped
        ),
    )


# Feature: v251-wake-renderer-hardening, Property 8: Truncation Visibility Sourced from Accounting
@_PBT_SETTINGS
@given(layer=_layer_with_decoupled_truncation())
def test_property8_truncation_visibility_sourced_from_accounting(layer: Layer) -> None:
    """Validates: Requirements 6.1, 6.2, 6.3.

    For any surfaced layer the output carries a truncation indicator if and only
    if ``layer.truncation.dropped > 0``, and when present that indicator states
    the ``dropped`` count taken directly from ``layer.truncation`` — not
    recomputed from the rendered entry count. The generator decouples the
    accounting from ``len(entries)`` so a ``dropped`` value that differs from the
    entry count proves the indicator is sourced from the accounting.
    """
    indicator = render_truncation_indicator(layer)
    dropped = layer.truncation.dropped

    if dropped > 0:
        # Req 6.1: present exactly when dropped > 0, and it states the dropped
        # count taken from the layer's accounting (Req 6.3). The count is
        # matched with its trailing ``)`` delimiter so a smaller count can never
        # be a substring false-positive of a larger one (e.g. ``1`` in ``10``).
        assert indicator is not None
        assert f"dropped={dropped})" in indicator
        # Req 6.3: the dropped count is sourced from the accounting, not
        # recomputed from the rendered entry count. When the two differ, the
        # accounting value — never the entry count — appears as the dropped
        # count, proving the indicator reads ``layer.truncation``.
        if dropped != len(layer.entries):
            assert f"dropped={len(layer.entries)})" not in indicator
        # Req 6.3: the available / included counts also come from accounting
        # (delimiter-anchored with the trailing ``,`` for the same reason).
        assert f"available={layer.truncation.available}," in indicator
        assert f"included={layer.truncation.included}," in indicator
    else:
        # Req 6.2: no indicator when dropped == 0.
        assert indicator is None


@st.composite
def _non_surfaced_layer(draw: st.DrawFn, layer_id: LayerId) -> Layer:
    """Build an arbitrary L3/L4 layer to prove its presence is harmless to P1.

    ``render_wake_plan`` only iterates ``SURFACED_LAYERS`` (L0/L1/L2), so a plan
    may legitimately carry populated L3/L4 layers. Including them here keeps the
    generated plan realistic (and well-formed for ``plan.layer(...)``) without
    affecting the surfaced sections Property 1 reasons about.
    """
    n_entries = draw(st.integers(min_value=0, max_value=4))
    entries = [
        PlanEntry(
            layer=layer_id,
            source_ids=[f"{layer_id}-src-{i}"],
            why_included="reason",
            summary=f"summary-{layer_id}-{i}",
            truth_status=draw(st.sampled_from(_MIXED_TRUTH_STATUSES)),
        )
        for i in range(n_entries)
    ]
    return Layer(
        layer=layer_id,
        entries=entries,
        budget=_make_budget(draw(st.integers(min_value=1, max_value=6))),
        truncation=TruncationAccounting(available=0, included=0, dropped=0),
    )


def _surfaced_section_entry_lines(output: str, layer_id: LayerId) -> list[str]:
    """Return the rendered entry lines within one surfaced layer's section.

    Splits ``output`` into sections delimited by the surfaced layer headers (in
    their fixed L0/L1/L2 order) and returns, in order, the entry lines of the
    requested layer's section. Entry lines are exactly the rendered
    Wake_Rendered_Entry lines (each begins with ``"- "``); the section's header,
    its ``EMPTY_STATE`` indicator, and any truncation indicator are excluded.
    """
    lines = output.split("\n")
    start = lines.index(LAYER_HEADERS[layer_id])
    # The next surfaced layer's header bounds this section; the last surfaced
    # layer runs to the end of the output.
    position = SURFACED_LAYERS.index(layer_id)
    if position + 1 < len(SURFACED_LAYERS):
        end = lines.index(LAYER_HEADERS[SURFACED_LAYERS[position + 1]])
    else:
        end = len(lines)
    return [line for line in lines[start + 1 : end] if line.startswith("- ")]


# Feature: v251-wake-renderer-hardening, Property 1: Plan Fidelity and Order
@_PBT_SETTINGS
@given(data=st.data())
def test_property1_plan_fidelity_and_order(data: st.DataObject) -> None:
    """Validates: Requirements 1.1, 1.2, 1.3.

    For any ContextAssemblyPlan the Rendered_Wake_Output carries the surfaced
    headers in the fixed order L0 < L1 < L2; within each surfaced layer the
    rendered entry lines correspond one-to-one and in order to that layer's
    ``select_rendered_entries`` result; and no rendered entry presents content
    absent from its source PlanEntry (each entry line is exactly
    ``render_entry_line`` of its source entry, and carries that entry's
    ``summary`` and ``source_ids``).
    """
    built = {
        layer_id: data.draw(_surfaced_layer(layer_id), label=layer_id)
        for layer_id in SURFACED_LAYERS
    }
    # Populated L3/L4 layers are present but must not affect the surfaced output.
    plan = ContextAssemblyPlan(
        project_name="proj",
        query=None,
        layers=[built[layer_id][0] for layer_id in SURFACED_LAYERS]
        + [
            data.draw(_non_surfaced_layer("L3"), label="L3"),
            data.draw(_non_surfaced_layer("L4"), label="L4"),
        ],
    )

    output = render_wake_plan(plan)

    # Req 1.2: all three surfaced headers appear, each exactly once, and their
    # positions satisfy the fixed order L0 < L1 < L2.
    for layer_id in SURFACED_LAYERS:
        assert output.count(LAYER_HEADERS[layer_id]) == 1
    assert (
        output.index(LAYER_HEADERS["L0"])
        < output.index(LAYER_HEADERS["L1"])
        < output.index(LAYER_HEADERS["L2"])
    )

    for layer_id in SURFACED_LAYERS:
        layer = built[layer_id][0]
        selected = select_rendered_entries(layer)
        expected_lines = [render_entry_line(entry) for entry in selected]

        actual_lines = _surfaced_section_entry_lines(output, layer_id)

        # Req 1.3: the rendered entry lines correspond one-to-one and in order
        # to the layer's selected Plan_Entry records. Equality with the
        # per-entry ``render_entry_line`` output is the single source of each
        # line, which establishes fidelity (no rendered content originates
        # outside the source PlanEntry).
        assert actual_lines == expected_lines

        # An empty selection renders the explicit empty-state indicator instead
        # of any entry line (Req 1.1 — no content beyond the plan entries).
        if not selected:
            section_start = output.index(LAYER_HEADERS[layer_id])
            assert EMPTY_STATE in output[section_start:]

        # Per-entry fidelity: each selected entry's own summary and every one of
        # its source ids appear in that entry's rendered line (Req 1.1, 1.3).
        for entry, line in zip(selected, actual_lines):
            assert entry.summary in line
            for source_id in entry.source_ids:
                assert source_id in line


# Feature: v251-wake-renderer-hardening, Property 2: No L3/L4 Leakage
@_PBT_SETTINGS
@given(data=st.data())
def test_property2_no_l3_l4_leakage(data: st.DataObject) -> None:
    """Validates: Requirements 1.5.

    For any ContextAssemblyPlan — including plans whose L3 and L4 layers carry
    entries — the Rendered_Wake_Output contains no entry content (no ``summary``
    and no ``source_ids``) originating from the L3 or L4 layers, while the L0,
    L1, and L2 sections are still rendered. ``render_wake_plan`` only iterates
    ``SURFACED_LAYERS`` (L0/L1/L2), so populated L3/L4 layers must never leak
    into the rendered output.

    The surfaced generator emits only L0/L1/L2-prefixed markers
    (``summary-L0-0`` / ``L0-src-0`` …) and ``_non_surfaced_layer`` emits only
    L3/L4-prefixed markers (``summary-L3-0`` / ``L3-src-0`` …), so the two
    alphabets are disjoint: any appearance of an L3/L4 marker in the output is
    genuine leakage, never an accidental collision with surfaced content.
    """
    surfaced = {
        layer_id: data.draw(_surfaced_layer(layer_id), label=layer_id)[0]
        for layer_id in SURFACED_LAYERS
    }
    # Populated L3/L4 layers carry the distinctive, layer-id-prefixed markers
    # described above; their presence in the plan must not affect the surfaced
    # sections render_wake_plan emits.
    l3 = data.draw(_non_surfaced_layer("L3"), label="L3")
    l4 = data.draw(_non_surfaced_layer("L4"), label="L4")

    plan = ContextAssemblyPlan(
        project_name="proj",
        query=None,
        layers=[surfaced[layer_id] for layer_id in SURFACED_LAYERS] + [l3, l4],
    )

    output = render_wake_plan(plan)

    # The surfaced sections are still rendered: all three headers appear (Req 1.5).
    for layer_id in SURFACED_LAYERS:
        assert LAYER_HEADERS[layer_id] in output

    # No L3/L4 entry content leaks: neither any entry's summary nor any of its
    # source ids appears anywhere in the rendered output (Req 1.5).
    for layer in (l3, l4):
        for entry in layer.entries:
            assert entry.summary not in output
            for source_id in entry.source_ids:
                assert source_id not in output


# The Disclosure_Level label set is fixed by ``disclosure_level`` (glossary):
# the token-budget summary line must always close with one of these labels.
_DISCLOSURE_LEVELS = ("L0", "L1", "L2", "L3", "L4+")

# Matches the one Disclosure_Level summary line the Wake_Command emits, capturing
# its level label. ``≈`` and the ``[...]`` framing are the renderer's own glyphs;
# generated summaries never contain them, so the count can't be spoofed. The
# token count is ``{N:,}`` formatted, hence the ``[\d,]+`` digit-and-comma class.
_DISCLOSURE_LINE_RE = re.compile(
    r"Approx wake-up tokens: ≈ [\d,]+ \[(L0|L1|L2|L3|L4\+)\]"
)


# Feature: v251-wake-renderer-hardening, Property 3: Disclosure_Level Summary Preserved
@_PBT_SETTINGS
@given(data=st.data())
def test_property3_disclosure_level_summary_preserved(data: st.DataObject) -> None:
    """Validates: Requirements 1.6.

    For any ContextAssemblyPlan the Rendered_Wake_Output — the pure
    ``render_wake_plan(plan)`` text plus the Disclosure_Level summary line the
    Wake_Command appends from ``_disclosure_level_for_plan(plan)`` — contains
    exactly one ``Approx wake-up tokens: ≈ {N} [{level}]`` summary line, whose
    ``level`` is one of the fixed Disclosure_Level labels
    ``{L0, L1, L2, L3, L4+}``. The Disclosure_Level helper is pure (it reads the
    surfaced plan summaries only), so the composed output is built without a
    backend.
    """
    built = {
        layer_id: data.draw(_surfaced_layer(layer_id), label=layer_id)
        for layer_id in SURFACED_LAYERS
    }
    # Populated L3/L4 layers may be present in a real plan; include them so the
    # summary line is exercised against a full plan, not just surfaced layers.
    plan = ContextAssemblyPlan(
        project_name="proj",
        query=None,
        layers=[built[layer_id][0] for layer_id in SURFACED_LAYERS]
        + [
            data.draw(_non_surfaced_layer("L3"), label="L3"),
            data.draw(_non_surfaced_layer("L4"), label="L4"),
        ],
    )

    # Compose the full Rendered_Wake_Output exactly as the Wake_Command does:
    # the pure rendered plan plus the Disclosure_Level summary line.
    total_tokens, level = _disclosure_level_for_plan(plan)
    output = render_wake_plan(plan) + "\n" + f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]"

    matches = _DISCLOSURE_LINE_RE.findall(output)

    # Req 1.6: exactly one Disclosure_Level summary line is preserved.
    assert len(matches) == 1

    # Req 1.6: the captured level is one of the fixed Disclosure_Level labels.
    captured_level = matches[0]
    assert captured_level in _DISCLOSURE_LEVELS
    # The summary line's level agrees with the helper's computed level.
    assert captured_level == level
