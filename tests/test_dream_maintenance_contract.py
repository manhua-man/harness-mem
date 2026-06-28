from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import harness_mem.commands.dream as dream_module
from harness_mem.commands.dream import dream_once
from harness_mem.commands.metabolism_pass import MetabolismPass
from harness_mem.commands.replay_window import ReplayWindow
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


async def _new_backend(data_dir: Path) -> LocalMemoryBackend:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    return backend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = _run(_new_backend(tmp_path))
    try:
        yield backend
    finally:
        _run(backend.close())


def _empty_window() -> ReplayWindow:
    now = datetime.now(timezone.utc)
    return ReplayWindow(
        time_range=(now - timedelta(days=1), now),
        dimensions={},
    )


def test_dream_supersede_candidates_wait_for_explicit_review(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="supersede-review-token old local-first storage decision",
                source="test",
                status="accepted",
            )
        )
    )
    new_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="supersede-review-token new canonical storage decision",
                source="test",
                status="accepted",
            )
        )
    )
    candidate = SupersedeCandidate(
        project_name="demo",
        target_type="memory_entry",
        target_id=old_id,
        replacement_type="memory_entry",
        replacement_id=new_id,
        reason="New current decision supersedes the old one.",
        evidence="dream found matching evidence",
        source="test",
        confidence=0.92,
    )

    async def fake_select_metabolism_pass(*_args, **_kwargs) -> MetabolismPass:
        return MetabolismPass(
            window=_empty_window(),
            merge=[],
            stale=[],
            supersede=[candidate],
            notes=["fake supersede pass"],
        )

    monkeypatch.setattr(
        dream_module,
        "select_metabolism_pass",
        fake_select_metabolism_pass,
    )

    run = _run(dream_once(backend, project_name="demo", config=None, source="agent"))

    reloaded_candidate = _run(backend.structured_store.get_supersede_candidate(candidate.id))
    old_entry = _run(backend.structured_store.get_memory_entry(old_id))
    new_entry = _run(backend.structured_store.get_memory_entry(new_id))

    assert reloaded_candidate is not None
    assert reloaded_candidate.status == "pending"
    assert old_entry is not None
    assert old_entry.valid_to is None
    assert old_entry.superseded_by == []
    assert new_entry is not None
    assert new_entry.supersedes == []
    assert run.handling_summary["pending_review"] == 1
    assert run.handling_summary["applied"] == 0
    assert run.items[0].final_action == "pending_review"
    assert run.items[0].result["candidate_status"] == "pending"
    assert run.items[0].result["review_tools"] == [
        "confirm_supersede",
        "reject_supersede",
    ]
