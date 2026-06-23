"""Pure Wake_Renderer — turns a ContextAssemblyPlan into rendered wake text.

v2.5.1 makes the rendered ``wake`` output reflect the v2.5.0
:class:`ContextAssemblyPlan`. All plan->text formatting lives here as pure
functions: this module performs **no I/O**, accesses **no store or backend**,
and never calls ``print``. ``cmd_wake_up`` prints the text this module returns
and applies the existing side effects separately, which keeps the rendering
logic directly property-testable and keeps the MCP stdout stream clean (Req 8).

This is the task 1.1 scaffold: the module constants and the
``render_wake_plan`` integration point are wired in fixed layer order, while
the per-helper bodies are stubs that subsequent tasks replace each behind its
own test.
"""

from __future__ import annotations

from harness_mem.core.schemas.context_assembly_plan import (
    ContextAssemblyPlan,
    Layer,
    LayerId,
    PlanEntry,
    TruthStatus,
)

# The cold-start, query-independent tiers wake surfaces, in fixed render order
# (Req 1.2, 1.5). L3 (topic recall) and L4 (raw evidence) are never rendered by
# wake because wake runs without a query.
SURFACED_LAYERS: tuple[LayerId, ...] = ("L0", "L1", "L2")

# Layers whose entries must be confirmed-current truth (Req 4.1, 5.1).
TRUTH_LAYERS: frozenset[LayerId] = frozenset({"L1", "L2"})

# Section header strings for each surfaced layer (Req 1.4 labeled headers).
LAYER_HEADERS: dict[LayerId, str] = {
    "L0": "# Project Profile  (L0 · identity)",
    "L1": "# Essential Truth  (L1 · confirmed current)",
    "L2": "# Active Task  (L2)",
}

EMPTY_STATE = "_(none)_"  # explicit empty-layer indicator (Req 1.4)
NO_SOURCE_ID = "(no source id)"  # explicit source-id-absent indicator (Req 3.6)


def select_rendered_entries(layer: Layer) -> list[PlanEntry]:
    """Entries that will be rendered for a surfaced layer, in plan order.

    1. For TRUTH_LAYERS (L1/L2), drop any entry whose ``truth_status`` is not
       ``confirmed_current`` (Req 4.1, 4.5, 5.1, 5.2). L0 (identity) is not
       filtered.
    2. Cap the result at ``layer.budget.max_entries`` by taking the first N in
       plan order (Req 2.1-2.6). ``eligible[:max_entries]`` also yields an
       empty list when ``max_entries`` is 0 (Req 2.4 — unreachable while the
       v2.5.0 Budget schema enforces ``max_entries > 0``, but handled
       defensively).
    """
    eligible = layer.entries
    if layer.layer in TRUTH_LAYERS:
        eligible = [
            entry for entry in eligible if entry.truth_status == "confirmed_current"
        ]
    return eligible[: layer.budget.max_entries]


def render_source_id_display(source_ids: list[str]) -> str:
    """Render every non-empty Source_Id verbatim, in order (Req 3.1-3.4).

    Returns a single Source_Id_Display string such as ``⟨src: id-a, id-b⟩``.
    When no non-empty id is present, returns ``⟨src: (no source id)⟩``
    (Req 3.6). Source ids are emitted character-for-character (no
    truncation/abbreviation).
    """
    non_empty = [source_id for source_id in source_ids if source_id]
    ids = ", ".join(non_empty) if non_empty else NO_SOURCE_ID
    return f"⟨src: {ids}⟩"


def render_truth_status_label(truth_status: TruthStatus) -> str:
    """Visible status label keyed off ``truth_status`` (Req 4.3, 4.4).

    ``confirmed_current`` -> "" (no stale marker); ``historical`` ->
    a distinct "⚠️ historical (superseded)" marker; ``pending`` ->
    a distinct "⏳ pending" marker. Status is read from the field, never
    re-derived from ``valid_to``.
    """
    if truth_status == "historical":
        return "⚠️ historical (superseded)"
    if truth_status == "pending":
        return "⏳ pending"
    return ""


def render_entry_line(entry: PlanEntry) -> str:
    """Render one Wake_Rendered_Entry from exactly one Plan_Entry (Req 1.3, 3.x).

    Includes the entry summary, the truth-status label, exactly one
    Source_Id_Display (all of ``entry.source_ids``), and the ``📍`` provenance
    marker derived from the primary Source_Id (Req 3.5).
    """
    truth_label = render_truth_status_label(entry.truth_status)
    source_id_display = render_source_id_display(entry.source_ids)
    primary_source_id = next(
        (source_id for source_id in entry.source_ids if source_id),
        NO_SOURCE_ID,
    )
    return (
        f"- {entry.summary}{truth_label}  "
        f"{source_id_display}  📍 {primary_source_id}"
    )


def render_truncation_indicator(layer: Layer) -> str | None:
    """Truncation line for a layer, sourced from TruncationAccounting (Req 6).

    Returns a string stating ``layer.truncation.dropped`` when ``dropped > 0``,
    else ``None`` (no indicator). Counts are read from the layer's accounting,
    never recomputed.
    """
    truncation = layer.truncation
    if truncation.dropped <= 0:
        return None
    return (
        f"_… {truncation.dropped} more dropped to fit budget "
        f"(available={truncation.available}, "
        f"included={truncation.included}, "
        f"dropped={truncation.dropped})_"
    )


def render_wake_plan(plan: ContextAssemblyPlan) -> str:
    """Render the full surfaced output (L0, L1, L2) as one text block (Req 1).

    Renders SURFACED_LAYERS in fixed order; each layer renders its header,
    then its selected entries (or EMPTY_STATE), then its truncation indicator.
    Never renders L3/L4 content (Req 1.5). Pure: no I/O, no store access.
    """
    lines: list[str] = []
    for layer_id in SURFACED_LAYERS:
        layer = plan.layer(layer_id)
        lines.append(LAYER_HEADERS[layer_id])

        entries = select_rendered_entries(layer)
        if entries:
            lines.extend(render_entry_line(entry) for entry in entries)
        else:
            lines.append(EMPTY_STATE)

        truncation = render_truncation_indicator(layer)
        if truncation is not None:
            lines.append(truncation)

    return "\n".join(lines)
