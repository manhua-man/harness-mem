"""E2E test: verify MemoryEntry and Observation write + read from SQLite."""

from __future__ import annotations
import asyncio
from pathlib import Path

import pytest

from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.tools.e2e import (
    check_memory_entry_roundtrip,
    check_observation_roundtrip,
    check_search,
    check_structured_list,
    check_timeline,
)


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


def test_observation_roundtrip(backend: LocalMemoryBackend):
    run(check_observation_roundtrip(backend, verbose=False))


def test_memory_entry_roundtrip(backend: LocalMemoryBackend):
    run(check_memory_entry_roundtrip(backend, verbose=False))


def test_search(backend: LocalMemoryBackend):
    run(check_search(backend, verbose=False))


def test_timeline(backend: LocalMemoryBackend):
    run(check_timeline(backend, verbose=False))


def test_structured_list(backend: LocalMemoryBackend):
    run(check_structured_list(backend, verbose=False))
