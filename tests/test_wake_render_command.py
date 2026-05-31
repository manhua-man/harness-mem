"""Unit / example / edge tests for the pure Wake_Renderer (``wake_render.py``).

These focused tests complement the property-based suite in
``tests/test_wake_render_properties.py`` by pinning down specific edge cases
with hand-built :class:`ContextAssemblyPlan` shapes. They need no backend,
store, or ``tmp_path`` — the renderer is a pure function of in-memory plan data.
"""

from __future__ import annotations

import pytest

from harness_mem.commands import wake as wake_cmd
from harness_mem.commands.wake_render import (
    EMPTY_STATE,
    LAYER_HEADERS,
    NO_SOURCE_ID,
    render_entry_line,
    render_source_id_display,
    select_rendered_entries,
)
from harness_mem.core.schemas.context_assembly_plan import (
    Budget,
    Layer,
    PlanEntry,
    TruncationAccounting,
)


def _zero_budget() -> Budget:
    """Build a ``Budget`` with ``max_entries == 0``.

    The v2.5.0 ``Budget`` schema enforces ``max_entries > 0`` (``Field(gt=0)``),
    so the zero cap is constructed via ``model_construct`` to bypass validation
    — matching the approach used in ``tests/test_wake_render_properties.py``.
    """
    return Budget.model_construct(max_entries=0, max_chars=None)


def test_select_rendered_entries_returns_empty_when_max_entries_zero() -> None:
    """A layer whose Budget ``max_entries`` is 0 renders zero entries (Req 2.4).

    Defensive edge: ``assemble_context_plan`` can never produce this (the
    ``Budget`` schema enforces ``max_entries > 0``), but the renderer must still
    cap a hand-built ``Layer`` at zero. An L0 layer is used so no truth filter
    is involved — the only thing producing an empty result is the budget cap.
    """
    layer = Layer(
        layer="L0",
        entries=[
            PlanEntry(
                layer="L0",
                source_ids=[f"L0-src-{i}"],
                why_included="identity:active_project",
                summary=f"summary-{i}",
                truth_status="confirmed_current",
            )
            for i in range(3)
        ],
        budget=_zero_budget(),
        truncation=TruncationAccounting(available=3, included=0, dropped=3),
    )

    assert layer.budget.max_entries == 0
    assert select_rendered_entries(layer) == []


def test_render_entry_line_with_all_empty_source_ids_shows_no_source_id() -> None:
    """An entry whose ``source_ids`` are all empty strings still renders (Req 3.6).

    ``PlanEntry.source_ids`` requires ``min_length=1``, but the individual
    strings may be empty, so ``["", ""]`` is a valid entry that carries no
    usable Source_Id. The renderer must still render the entry, surface the
    explicit ``(no source id)`` indication in its Source_Id_Display, and keep
    the ``📍`` provenance marker.
    """
    entry = PlanEntry(
        layer="L1",
        source_ids=["", ""],
        why_included="essential:confirmed_rule",
        summary="rule with no usable source id",
        truth_status="confirmed_current",
    )

    line = render_entry_line(entry)

    # The entry still renders with its summary.
    assert "rule with no usable source id" in line
    # The explicit no-source-id indication is present in the Source_Id_Display.
    assert NO_SOURCE_ID in line
    assert render_source_id_display(entry.source_ids) == f"⟨src: {NO_SOURCE_ID}⟩"
    # The provenance marker is still rendered for the entry (Req 3.5).
    assert "📍" in line


@pytest.mark.anyio
async def test_cmd_wake_up_no_plan_returns_error_and_emits_no_plan_section(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No producible plan -> error line, non-zero exit, no plan-backed section (Req 1.7).

    When ``assemble_context_plan`` raises, ``cmd_wake_up`` must stop before
    emitting any plan-backed section and return a non-zero code naming the
    plan-production failure (Req 1.7). The data directory is isolated by the
    autouse ``data_dir`` fixture in ``tests/conftest.py``, which monkeypatches
    ``wake.DEFAULT_DATA_DIR`` to a ``tmp_path`` subdir — the backend
    ``cmd_wake_up`` constructs never touches the real ``~/.harness-mem/``.
    ``no_auto_ingest=True`` keeps the run deterministic (auto-ingest runs
    before plan assembly).
    """

    async def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    # Patch the name in the module under test so the call inside cmd_wake_up
    # raises before any plan-backed section is rendered.
    monkeypatch.setattr(wake_cmd, "assemble_context_plan", _boom)

    result = await wake_cmd.cmd_wake_up("someproject", no_auto_ingest=True)

    assert result == 1

    out = capsys.readouterr().out
    # The error line names the plan-production failure for the resolved project.
    assert "Error: could not assemble context plan" in out
    assert "someproject" in out
    assert "boom" in out
    # No plan-backed section header is emitted (rendering stopped before render_wake_plan).
    for header in LAYER_HEADERS.values():
        assert header not in out
    assert "# Essential Truth" not in out
    assert "# Active Task" not in out


@pytest.mark.anyio
async def test_cmd_wake_up_empty_project_renders_headers_and_empty_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty project renders every surfaced header plus ``_(none)_`` (Req 1.4).

    Even with no seeded data, ``assemble_context_plan`` returns a well-formed
    plan whose L0/L1/L2 layers carry zero entries, so ``cmd_wake_up`` must
    render each surfaced layer header followed by the ``EMPTY_STATE`` indicator
    and complete without raising (Req 1.4).

    No profile is seeded: ``cmd_wake_up`` resolves the project from the explicit
    ``project_name`` argument (``resolve_project_name`` returns it directly), and
    the assembler's own ``required=False`` resolution accepts the same explicit
    name — an unseeded project still produces a plan. The data directory is
    isolated by the autouse ``data_dir`` fixture in ``tests/conftest.py``
    (``wake.DEFAULT_DATA_DIR`` -> a ``tmp_path`` subdir), and ``cmd_wake_up``
    owns the backend it constructs, closing it in its own ``finally`` block.
    ``no_auto_ingest=True`` keeps the run deterministic.
    """
    result = await wake_cmd.cmd_wake_up("emptyproject", no_auto_ingest=True)

    # Empty project still succeeds — no exception, success exit code.
    assert result == 0

    out = capsys.readouterr().out
    # Every surfaced layer header is rendered (L0, L1, L2) in fixed order.
    for header in LAYER_HEADERS.values():
        assert header in out
    assert out.index(LAYER_HEADERS["L0"]) < out.index(LAYER_HEADERS["L1"])
    assert out.index(LAYER_HEADERS["L1"]) < out.index(LAYER_HEADERS["L2"])
    # Each empty layer surfaces the explicit empty-state indicator.
    assert EMPTY_STATE in out
    # One empty-state line per surfaced empty layer.
    assert out.count(EMPTY_STATE) == len(LAYER_HEADERS)
    # The Disclosure_Level token-budget summary line is still preserved (Req 1.6).
    assert "Approx wake-up tokens:" in out
