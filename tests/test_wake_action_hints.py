from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness_mem.commands.wake import build_wake_snapshot
from harness_mem.core.schemas.memory_entry import MemoryEntry
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


def test_wake_snapshot_includes_optional_action_hints(backend) -> None:
    entry_id = _run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="wakehinttoken current decision should guide action",
                source="test",
                status="accepted",
                confidence=0.95,
            )
        )
    )

    snapshot = _run(build_wake_snapshot(backend, "demo"))

    assert snapshot["action_hints"]
    hint = next(
        item
        for item in snapshot["action_hints"]
        if item["source_id"] == entry_id
    )
    assert hint["source_kind"] == "memory_entry"
    assert hint["tool"] == "search_memory"
    assert hint["arguments"]["project_name"] == "demo"
    assert hint["why_it_matters"]
    assert hint["action"]
    entry = next(
        item
        for item in snapshot["essential_truth"]
        if item["source_ids"] == [entry_id]
    )
    assert entry["action_hint"] == hint
