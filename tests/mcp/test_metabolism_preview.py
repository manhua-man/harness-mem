"""MCP ``tool_metabolism_preview`` end-to-end tests for v2.3.0 task 4.4.

These tests exercise the full preview tool surface: project resolution,
selector → store wiring, run-record persistence ordering, and the
selector-failure error path. They are tests-only; no production source
is modified.

The two-call sequence locks in the selector ↔ ``MetabolismRun`` storage
contract:

* Two consecutive calls with new signals seeded between them produce
  two distinct run ids and two persisted ``MetabolismRun`` rows in
  chronological order.
* The second call surfaces the new ``repeat_search_hits`` window even
  though the first did not.

The error-path test pins down the 4.3 contract: when
``select_replay_window`` raises, the tool returns
``{success: False, error, doctor_pointer}`` and a single
``MetabolismRun(status="error")`` is persisted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import Observation, RetrievalSignal, RuleCandidate
from harness_mem.mcp import server as mcp_server
from harness_mem.mcp.server import set_backend_override, tool_metabolism_preview
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

pytestmark = pytest.mark.mcp


def _seed_initial_state(backend: LocalMemoryBackend, project_name: str) -> None:
    """Two observations + one stale pending rule, no signals yet."""
    now = datetime.now(timezone.utc)
    for index in range(2):
        observation = Observation(
            session_id=f"sess-{project_name}-{index}",
            client="claude-code",
            raw_content=f"Replay-window seed observation #{index}",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
        )
        run(backend.verbatim_store.save(observation))

    stale_rule = RuleCandidate(
        project_name=project_name,
        session_id=f"sess-{project_name}-stale",
        pattern="Use parameterised SQL when writing data access code.",
        trigger="When writing data access code",
        status="pending",
        created_at=now - timedelta(days=8),
    )
    run(backend.structured_store.save_rule_candidate(stale_rule))


def _seed_search_hit_signals(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    repeat_target_id: str,
    singleton_target_id: str,
) -> None:
    """Two ``search_hit`` signals on the repeat target + one singleton."""
    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    now = datetime.now(timezone.utc)
    for index in range(2):
        signal = RetrievalSignal(
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=repeat_target_id,
            recorded_at=now - timedelta(hours=index + 1),
        )
        run(structured_store.save_retrieval_signal(signal))

    singleton = RetrievalSignal(
        project_name=project_name,
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id=singleton_target_id,
        recorded_at=now - timedelta(hours=1),
    )
    run(structured_store.save_retrieval_signal(singleton))


def test_metabolism_preview_two_call_sequence_returns_different_windows(
    tmp_path: Path,
) -> None:
    """Two consecutive previews persist run records in chronological order.

    First call sees no ``search_hit`` signals; second call (after seeding
    a repeat target) reports a non-empty ``repeat_search_hits`` slice and
    a fresh ``run_id``.
    """
    project_name = "v230-4-4-two-call"
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    set_backend_override(backend)
    try:
        _seed_initial_state(backend, project_name)

        # --- First call: no signals seeded yet --------------------------
        result1 = tool_metabolism_preview(project_name=project_name)

        assert result1["success"] is True
        assert result1["signals_used"] == 0
        assert result1["dimensions"]["observations"]["total_seen"] == 2
        assert result1["dimensions"]["pending_candidates"]["total_seen"] == 1
        assert result1["dimensions"]["repeat_search_hits"]["selected_ids"] == []

        run_id_1 = result1["run_id"]

        # --- Seed additional signals between calls ---------------------
        repeat_target_id = "memory-entry-repeat-a"
        singleton_target_id = "memory-entry-singleton-b"
        _seed_search_hit_signals(
            backend,
            project_name,
            repeat_target_id=repeat_target_id,
            singleton_target_id=singleton_target_id,
        )

        # --- Second call: repeat target now qualifies ------------------
        result2 = tool_metabolism_preview(project_name=project_name)

        assert result2["success"] is True
        assert result2["run_id"] != run_id_1
        # Two signals contributed (target_id_a). The singleton on
        # target_id_b is filtered out by the count >= 2 predicate and
        # does not appear in `signals_used`.
        assert result2["signals_used"] == 2
        repeats = result2["dimensions"]["repeat_search_hits"]
        assert repeats["selected_ids"] == [repeat_target_id]
        assert repeats["total_seen"] == 1

        # --- Verify run records persisted in order ---------------------
        runs = run(
            backend.structured_store.list_metabolism_runs(project_name)
        )
        assert len(runs) == 2

        # `list_metabolism_runs` returns newest first.
        assert runs[0].id == result2["run_id"]
        assert runs[1].id == run_id_1

        for record in runs:
            assert record.kind == "preview"
            assert record.status == "preview"
            assert record.output_counts == {"suggestions": 0}

        assert len(runs[0].selected_signal_ids) == 2
        assert runs[1].selected_signal_ids == []

        # The second call started no earlier than the first call finished:
        # this is the chronological ordering invariant the run record
        # contract promises.
        assert runs[1].completed_at is not None
        assert runs[0].started_at >= runs[1].completed_at
    finally:
        set_backend_override(None)
        run(backend.close())


def test_metabolism_preview_error_path_persists_error_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selector failures persist a status="error" run and never raise."""
    project_name = "v230-4-4-error"
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    set_backend_override(backend)
    try:
        async def _boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("boom")

        monkeypatch.setattr(mcp_server, "select_replay_window", _boom)

        result = tool_metabolism_preview(project_name=project_name)

        assert result["success"] is False
        assert result["error"] == "boom"
        assert "doctor_pointer" in result

        runs = run(
            backend.structured_store.list_metabolism_runs(project_name)
        )
        assert len(runs) == 1
        record = runs[0]
        assert record.status == "error"
        assert record.selected_signal_ids == []
        assert record.output_counts == {"suggestions": 0}
        assert record.notes is not None
        assert any("selector failed: boom" in note for note in record.notes)
    finally:
        set_backend_override(None)
        run(backend.close())
