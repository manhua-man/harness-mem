"""Tests for runtime FTS query handling."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.core.schemas import MemoryEntry, Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def backend(tmp_path: Path):
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        yield backend
    finally:
        run(backend.close())


def test_observation_search_handles_natural_language_query(backend: LocalMemoryBackend):
    run(
        backend.verbatim_store.save(
            Observation(
                session_id="session-degree",
                client="codex",
                raw_content="I graduated with a biology degree and now commute 30 minutes to work.",
                content_type="transcript",
                metadata={"project_name": "demo"},
            )
        )
    )
    run(
        backend.verbatim_store.save(
            Observation(
                session_id="session-distractor",
                client="codex",
                raw_content="I bought a degree wheel for the workshop and cleaned the garage.",
                content_type="transcript",
                metadata={"project_name": "demo"},
            )
        )
    )

    results = run(backend.verbatim_store.search("What degree did I graduate with?"))

    assert results, "Natural-language query should return observation hits"
    assert results[0].session_id == "session-degree"


def test_memory_entry_search_respects_project_filter_with_token_fusion(backend: LocalMemoryBackend):
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="alpha",
                category="api",
                content="Auth endpoints accept Bearer tokens in the Authorization header.",
                source="manual",
            )
        )
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="beta",
                category="api",
                content="Auth endpoints accept session cookies instead of bearer tokens.",
                source="manual",
            )
        )
    )

    results = run(
        backend.structured_store.search_memory_entries(
            "What auth tokens do endpoints accept?",
            project_name="alpha",
            limit=5,
        )
    )

    assert results, "Project-scoped natural-language query should return memory entries"
    assert all(entry.project_name == "alpha" for entry in results)
    assert results[0].content.startswith("Auth endpoints accept Bearer tokens")
