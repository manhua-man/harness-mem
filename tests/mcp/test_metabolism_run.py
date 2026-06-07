"""MCP ``tool_metabolism_run`` handler-level tests (v2.3.1 tasks 5.2–5.5).

Covers the full 5.2/5.3/5.5 contract:

* Success path persists exactly one ``MetabolismRun(kind="metabolism",
  status="completed")`` row, attaches each suggestion candidate to that
  run id, and returns ``output_counts`` with three explicit per-type
  keys.
* Error path persists a ``MetabolismRun(kind="metabolism", status="error")``
  row and returns ``{success: False, error, doctor_pointer}`` without
  raising. Mirrors ``test_metabolism_preview.py``'s monkeypatch shape.
* Two-call sequence (run + preview) verifies no cross-contamination:
  the sibling ``metabolism_preview`` tool still works alongside (its
  run record stays ``kind="preview"`` and is unaffected by the new
  handler).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import MemoryEntry, RetrievalSignal
from harness_mem.mcp import server as mcp_server
from harness_mem.mcp.server import (
    set_backend_override,
    tool_metabolism_preview,
    tool_metabolism_run,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import patch_fake_embedding_loader, run, seed_persisted_embedding

pytestmark = pytest.mark.mcp


def _seed_merge_pair(backend: LocalMemoryBackend, project_name: str) -> tuple[str, str]:
    """Two near-duplicate current entries plus search_hit signals."""
    now = datetime.now(timezone.utc)

    duplicate_a = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="Always parameterize SQL queries to prevent SQL injection.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )
    duplicate_b = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="Always use parameterized SQL queries to prevent SQL injection.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    run(structured_store.save_memory_entry(duplicate_a))
    run(structured_store.save_memory_entry(duplicate_b))
    seed_persisted_embedding(backend, duplicate_a.id, (1.0, 0.0))
    seed_persisted_embedding(backend, duplicate_b.id, (1.0, 0.0))

    for entry_id in (duplicate_a.id, duplicate_b.id):
        for offset in range(2):
            signal = RetrievalSignal(
                project_name=project_name,
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id=entry_id,
                recorded_at=now - timedelta(hours=offset + 1),
            )
            run(structured_store.save_retrieval_signal(signal))

    return duplicate_a.id, duplicate_b.id


def _seed_supersede_pair(backend: LocalMemoryBackend, project_name: str) -> tuple[str, str]:
    """One historical/current near-identical pair so the supersede proposer fires."""
    now = datetime.now(timezone.utc)
    historical = MemoryEntry(
        project_name=project_name,
        category="decision",
        content="Use invoke for IPC payloads on Windows to avoid large emit deadlocks.",
        source="manual",
        created_at=now - timedelta(days=10),
        valid_to=now - timedelta(days=1),
    )
    current = MemoryEntry(
        project_name=project_name,
        category="decision",
        content="Use invoke for IPC payloads on Windows to avoid large emit deadlocks and keep payload delivery stable.",
        source="manual",
        created_at=now - timedelta(hours=3),
    )
    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    run(structured_store.save_memory_entry(historical))
    run(structured_store.save_memory_entry(current))
    return historical.id, current.id


def test_metabolism_run_success_persists_run_and_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success path: run record is metabolism/completed, candidates carry
    the new run id, ``output_counts`` has three explicit per-type keys.

    Also sanity-checks that ``metabolism_preview`` still runs alongside
    and produces its own ``kind="preview"`` row (no cross-contamination).
    """
    project_name = "v231-5-2-success"
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    patch_fake_embedding_loader(monkeypatch)
    set_backend_override(backend)
    try:
        entry_a_id, entry_b_id = _seed_merge_pair(backend, project_name)
        superseded_id, replacement_id = _seed_supersede_pair(backend, project_name)

        result = tool_metabolism_run(project_name=project_name)

        assert result["success"] is True
        run_id = result["run_id"]
        assert isinstance(run_id, str) and run_id

        output_counts = result["output_counts"]
        assert set(output_counts.keys()) == {
            "merge_suggestions",
            "stale_suggestions",
            "supersede_suggestions",
        }
        assert output_counts["merge_suggestions"] == 1
        # Fresh entries don't trip the 60d silence threshold.
        assert output_counts["stale_suggestions"] == 0
        assert output_counts["supersede_suggestions"] == 1

        structured_store = backend.structured_store
        assert isinstance(structured_store, LocalStructuredStore)

        runs = run(structured_store.list_metabolism_runs(project_name))
        assert len(runs) == 1
        record = runs[0]
        assert record.id == run_id
        assert record.kind == "metabolism"
        assert record.status == "completed"
        assert record.output_counts == {
            "merge_suggestions": 1,
            "stale_suggestions": 0,
            "supersede_suggestions": 1,
        }

        merge_candidates = run(
            structured_store.list_merge_suggestion_candidates(project_name)
        )
        assert len(merge_candidates) == 1
        candidate = merge_candidates[0]
        assert candidate.metabolism_run_id == run_id
        assert {candidate.target_a_id, candidate.target_b_id} == {
            entry_a_id,
            entry_b_id,
        }

        stale_candidates = run(
            structured_store.list_stale_truth_suggestion_candidates(project_name)
        )
        assert stale_candidates == []
        supersede_candidates = run(
            structured_store.list_supersede_candidates(project_name)
        )
        assert len(supersede_candidates) == 1
        supersede = supersede_candidates[0]
        assert supersede.target_id == superseded_id
        assert supersede.replacement_id == replacement_id
        assert supersede.status == "pending"

        # Sibling check: metabolism_preview still works and writes a
        # separate kind="preview" record without disturbing the run row.
        preview_result = tool_metabolism_preview(project_name=project_name)
        assert preview_result["success"] is True

        all_runs = run(structured_store.list_metabolism_runs(project_name))
        kinds = sorted(r.kind for r in all_runs)
        assert kinds == ["metabolism", "preview"]
    finally:
        set_backend_override(None)
        run(backend.close())


def test_metabolism_run_error_path_persists_error_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selector failures persist a metabolism/error run and never raise.

    Monkeypatches ``select_metabolism_pass`` rather than the deeper
    ``select_replay_window``; the 5.3 contract is "any exception in the
    pass funnels through one except block" — patching the entry point
    is the cleanest way to assert that without coupling to internals.
    """
    project_name = "v231-5-3-error"
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    set_backend_override(backend)
    try:

        async def _boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("pass exploded")

        monkeypatch.setattr(mcp_server, "select_metabolism_pass", _boom)

        result = tool_metabolism_run(project_name=project_name)

        assert result["success"] is False
        assert result["error"] == "pass exploded"
        assert "doctor_pointer" in result

        structured_store = backend.structured_store
        assert isinstance(structured_store, LocalStructuredStore)

        runs = run(structured_store.list_metabolism_runs(project_name))
        assert len(runs) == 1
        record = runs[0]
        assert record.kind == "metabolism"
        assert record.status == "error"
        assert record.output_counts == {
            "merge_suggestions": 0,
            "stale_suggestions": 0,
            "supersede_suggestions": 0,
        }
        assert record.notes is not None
        assert any("metabolism_run failed: pass exploded" in note for note in record.notes)

        merge_candidates = run(
            structured_store.list_merge_suggestion_candidates(project_name)
        )
        assert merge_candidates == []
        stale_candidates = run(
            structured_store.list_stale_truth_suggestion_candidates(project_name)
        )
        assert stale_candidates == []
    finally:
        set_backend_override(None)
        run(backend.close())
