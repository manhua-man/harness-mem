from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas.context_assembly_plan import (
    Budget,
    ContextAssemblyPlan,
    Layer,
    PlanEntry,
    TruncationAccounting,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.recent_context import build_recent_context, render_recent_context
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _layer(layer_id: str, entries: list[PlanEntry] | None = None) -> Layer:
    values = entries or []
    return Layer(
        layer=layer_id,  # type: ignore[arg-type]
        entries=values,
        budget=Budget(max_entries=10),
        truncation=TruncationAccounting(
            available=len(values),
            included=len(values),
            dropped=0,
        ),
    )


def _plan(project_name: str) -> ContextAssemblyPlan:
    return ContextAssemblyPlan(
        project_name=project_name,
        layers=[
            _layer("L0"),
            _layer(
                "L1",
                [
                    PlanEntry(
                        layer="L1",
                        source_ids=["rule-123456789"],
                        why_included="essential:confirmed_rule",
                        summary="Workspace path defines project identity.",
                    )
                ],
            ),
            _layer(
                "L2",
                [
                    PlanEntry(
                        layer="L2",
                        source_ids=["handoff-123456789"],
                        why_included="active:recent_handoff",
                        summary="Finish the recent-context wake migration.",
                    )
                ],
            ),
            _layer("L3"),
            _layer("L4"),
        ],
    )


async def _build_index(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        await backend.verbatim_store.save(
            Observation(
                id="new-observation-123456",
                session_id="session-new",
                client="cursor",
                raw_content=(
                    "# Cursor Session: session-new\n"
                    "## Turn 1\n"
                    "User: Add a recent context index.\n"
                    "Assistant: Implemented the renderer."
                ),
                content_type="transcript",
                timestamp=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
                metadata={
                    "project_name": "demo",
                    "files_modified": ["harness_mem/recent_context.py"],
                    "work_tokens": 800,
                },
            )
        )
        await backend.verbatim_store.save(
            Observation(
                id="old-observation-123456",
                session_id="session-old",
                client="codex",
                raw_content="User: Inspect the wake rendering contract.",
                content_type="transcript",
                timestamp=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
                metadata={"project_name": "demo"},
            )
        )
        await backend.verbatim_store.save(
            Observation(
                id="other-project-123456",
                session_id="session-other",
                client="cursor",
                raw_content="User: This belongs elsewhere.",
                content_type="transcript",
                timestamp=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
                metadata={"project_name": "other"},
            )
        )
        return await build_recent_context(backend, "demo", limit=10)
    finally:
        await backend.close()


def test_build_recent_context_filters_project_and_orders_newest_first(
    tmp_path: Path,
) -> None:
    index = asyncio.run(_build_index(tmp_path))

    assert [item.observation_id for item in index.items] == [
        "new-observation-123456",
        "old-observation-123456",
    ]
    assert index.items[0].title == "Add a recent context index."
    assert index.items[0].files == ("harness_mem/recent_context.py",)
    assert index.total_work_tokens == 800
    assert index.total_read_tokens > 0


def test_compact_recent_context_replaces_empty_layer_headers(tmp_path: Path) -> None:
    index = asyncio.run(_build_index(tmp_path))

    output = render_recent_context(index, _plan("demo"), compact=True)

    assert output.startswith("# [demo] recent context")
    assert "O-new-obse" in output
    assert "Add a recent context index." in output
    assert "Active" in output
    assert "Finish the recent-context wake migration." in output
    assert "Stable truths" in output
    assert "Workspace path defines project identity." in output
    assert "get_observations(observation_ids=[" in output
    assert "# Project Profile" not in output
    assert "# Essential Truth" not in output
    assert "# Active Task" not in output
    assert "_(none)_" not in output


def test_rich_recent_context_includes_legend_and_files(tmp_path: Path) -> None:
    index = asyncio.run(_build_index(tmp_path))

    output = render_recent_context(index, _plan("demo"), compact=False)

    assert "Legend: @ session" in output
    assert "Context Index:" in output
    assert "files: harness_mem/recent_context.py" in output
