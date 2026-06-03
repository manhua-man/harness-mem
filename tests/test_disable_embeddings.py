"""Tests for the HARNESS_MEM_DISABLE_EMBEDDINGS opt-out switch.

Some environments cannot import the sentence-transformers stack — most commonly
because ``import torch`` *hangs* (not raises) on a broken install or a CI box
with no cached model. The existing ``try/except ImportError`` guards only catch
a clean import failure, not a hang. ``HARNESS_MEM_DISABLE_EMBEDDINGS`` lets such
environments skip embedding model loading entirely.

These tests prove the guard short-circuits *before* any model load is attempted
(so they never touch torch), that a memory save still succeeds with zero vector
rows, and that production default behavior is unchanged when the env is unset.
All writes target ``tmp_path`` (project rule P1: data-path isolation).
"""

from __future__ import annotations

import tempfile
import time
import threading
from pathlib import Path

import pytest

from harness_mem.core.schemas import MemoryEntry
from harness_mem.embedding import embeddings_disabled
from harness_mem.embedding.model_loader import _DISABLE_ENV_VAR
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


@pytest.fixture
def temp_backend():
    """Create a temporary backend for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = LocalMemoryBackend(Path(tmpdir))
        try:
            yield backend
        finally:
            run(backend.close())


# ---- embeddings_disabled() env parsing -----------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " on "])
def test_truthy_values_disable(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_DISABLE_ENV_VAR, value)
    assert embeddings_disabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "nope"])
def test_falsy_or_unset_values_keep_embeddings_enabled(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_DISABLE_ENV_VAR, value)
    assert embeddings_disabled() is False


def test_unset_env_keeps_embeddings_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_DISABLE_ENV_VAR, raising=False)
    assert embeddings_disabled() is False


# ---- persist_embedding short-circuits before any model load --------------


def test_persist_embedding_skips_model_load_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the switch on, persist_embedding must not call get_model_loader.

    The loader is monkeypatched to explode if reached, so this proves the guard
    short-circuits *before* the sentence-transformers/torch import path.
    """
    monkeypatch.setenv(_DISABLE_ENV_VAR, "1")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("get_model_loader must not be called when disabled")

    monkeypatch.setattr("harness_mem.embedding.get_model_loader", _boom)

    from harness_mem.storage.sqlite_index import SQLiteIndex

    with tempfile.TemporaryDirectory() as tmpdir:
        index = SQLiteIndex(Path(tmpdir) / "index.db")
        index.init_db()
        try:
            # Must not raise: the guard returns before loading the model.
            index.persist_embedding("entry-1", "some text", "all-MiniLM-L6-v2")
        finally:
            index.close()


def test_save_succeeds_with_no_vec_row_when_disabled(
    temp_backend: LocalMemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A memory save still succeeds, but writes zero vec_embeddings rows."""
    monkeypatch.setenv(_DISABLE_ENV_VAR, "1")

    async def _test() -> None:
        await temp_backend.init()
        entry_id = "disabled-entry-1"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="bug",
                content="A test memory entry saved with embeddings disabled.",
                source="manual",
                memory_type="episodic",
            )
        )
        conn = temp_backend.structured_store._index._conn_write()
        row = conn.execute(
            "SELECT entry_id FROM vec_embeddings WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        assert row is None, "no vec row should be written when embeddings disabled"

    run(_test())


def test_persist_embedding_times_out_and_skips_vec_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung encode must not block the write path forever."""

    class _HangingLoader:
        model_id = "all-MiniLM-L6-v2"
        model_version = "test"

        def __init__(self) -> None:
            self.calls = 0
            self.release = threading.Event()

        def encode(self, _text: str):
            self.calls += 1
            self.release.wait(5)
            return [0.1, 0.2, 0.3]

    loader = _HangingLoader()

    monkeypatch.delenv(_DISABLE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index.EMBEDDING_WRITE_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index._EMBEDDING_WRITE_TIMED_OUT_MODELS", set()
    )
    monkeypatch.setattr(
        "harness_mem.embedding.get_model_loader",
        lambda _model_id: loader,
    )

    from harness_mem.storage.sqlite_index import SQLiteIndex

    with tempfile.TemporaryDirectory() as tmpdir:
        index = SQLiteIndex(Path(tmpdir) / "index.db")
        index.init_db()
        start = time.perf_counter()
        try:
            index.persist_embedding("entry-timeout-1", "some text", "all-MiniLM-L6-v2")
        finally:
            elapsed = time.perf_counter() - start
            conn = index._conn_write()
            row = conn.execute(
                "SELECT entry_id FROM vec_embeddings WHERE entry_id = ?",
                ("entry-timeout-1",),
            ).fetchone()
            loader.release.set()
            index.close()

    assert elapsed < 0.5, "persist_embedding should fail fast on hung encode"
    assert row is None, "timed-out encode should not write a vec row"
    assert loader.calls == 1


def test_timeout_circuit_breaker_skips_second_model_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the first timeout, later writes should skip the same model fast."""

    class _HangingLoader:
        model_id = "all-MiniLM-L6-v2"
        model_version = "test"

        def __init__(self) -> None:
            self.calls = 0
            self.release = threading.Event()

        def encode(self, _text: str):
            self.calls += 1
            self.release.wait(5)
            return [0.1, 0.2, 0.3]

    loader = _HangingLoader()

    monkeypatch.delenv(_DISABLE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index.EMBEDDING_WRITE_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index._EMBEDDING_WRITE_TIMED_OUT_MODELS", set()
    )
    monkeypatch.setattr(
        "harness_mem.embedding.get_model_loader",
        lambda _model_id: loader,
    )

    from harness_mem.storage.sqlite_index import SQLiteIndex

    with tempfile.TemporaryDirectory() as tmpdir:
        index = SQLiteIndex(Path(tmpdir) / "index.db")
        index.init_db()
        try:
            index.persist_embedding("entry-timeout-1", "some text", "all-MiniLM-L6-v2")
            start = time.perf_counter()
            index.persist_embedding("entry-timeout-2", "some text", "all-MiniLM-L6-v2")
            elapsed = time.perf_counter() - start
        finally:
            loader.release.set()
            index.close()

    assert loader.calls == 1, "second write should skip without re-entering encode"
    assert elapsed < 0.1, "circuit breaker should make later writes return immediately"


def test_save_succeeds_with_no_vec_row_when_encode_times_out(
    temp_backend: LocalMemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structured save should still succeed when write-path embeddings hang."""

    class _HangingLoader:
        model_id = "all-MiniLM-L6-v2"
        model_version = "test"

        def __init__(self) -> None:
            self.release = threading.Event()

        def encode(self, _text: str):
            self.release.wait(5)
            return [0.1, 0.2, 0.3]

    loader = _HangingLoader()

    monkeypatch.delenv(_DISABLE_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index.EMBEDDING_WRITE_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "harness_mem.storage.sqlite_index._EMBEDDING_WRITE_TIMED_OUT_MODELS", set()
    )
    monkeypatch.setattr(
        "harness_mem.embedding.get_model_loader",
        lambda _model_id: loader,
    )

    async def _test() -> None:
        await temp_backend.init()
        entry_id = "timeout-entry-1"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="decision",
                content="A test memory entry saved while the embedding encode hangs.",
                source="observation:timeout-entry-1",
                memory_type="semantic",
            )
        )
        conn = temp_backend.structured_store._index._conn_write()
        row = conn.execute(
            "SELECT entry_id FROM vec_embeddings WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        assert row is None, "timed-out encode should still leave vec row empty"

    try:
        run(_test())
    finally:
        loader.release.set()
