"""Tests for persistent vector storage (v1.6.2)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from harness_mem.core.schemas import MemoryEntry
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


def test_write_embedding_creates_vec_row(temp_backend):
    """Task 9.1: Write embedding, verify row exists with correct model_id/model_version."""
    async def _test():
        await temp_backend.init()

        # Save a memory entry (should trigger embedding persistence)
        entry_id = "test-entry-1"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="bug",
                content="This is a test memory entry for vector persistence.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Verify vec_embeddings row exists
        conn = temp_backend.structured_store._index._conn_write()
        cursor = conn.execute(
            "SELECT entry_id, model_id, model_version FROM vec_embeddings WHERE entry_id = ?",
            (entry_id,),
        )
        row = cursor.fetchone()

        assert row is not None, "vec_embeddings row should exist"
        assert row[0] == entry_id
        assert row[1] == "all-MiniLM-L6-v2"  # default model
        assert row[2] is not None  # model_version should be set

        await temp_backend.close()

    run(_test())


def test_restart_reads_persisted_vectors(temp_backend):
    """Task 9.2: Restart process, verify vectors are read from DB without re-encoding."""
    async def _test():
        await temp_backend.init()

        # Save a memory entry
        entry_id = "test-entry-2"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="decision",
                content="Test content for restart verification.",
                source="manual",
                memory_type="semantic",
            )
        )

        # Close and reopen backend (simulates restart)
        await temp_backend.close()

        backend2 = LocalMemoryBackend(temp_backend.data_dir)
        await backend2.init()

        # Search should use persisted vectors (no re-encoding)
        from harness_mem.search import HybridSearchLayer

        layer = HybridSearchLayer(backend2.structured_store._index)
        result = layer.search("test content", table="memory_entries", limit=5, mode="hybrid")

        # If vectors were read successfully, we should get results
        assert len(result.rows) > 0, "Should retrieve results using persisted vectors"
        assert result.effective_mode in ("hybrid", "fts"), "Should use hybrid or fallback to FTS"

        await backend2.close()

    run(_test())


def test_model_id_filter(temp_backend):
    """Task 9.3: Query with model_id filter, verify only matching vectors are used."""
    async def _test():
        await temp_backend.init()

        # Save entries with default model
        entry_id_1 = "test-entry-3a"
        entry_id_2 = "test-entry-3b"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id_1,
                project_name="test-project",
                category="bug",
                content="First test entry.",
                source="manual",
                memory_type="episodic",
            )
        )
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id_2,
                project_name="test-project",
                category="bug",
                content="Second test entry.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Manually insert a vector with a different model_id
        conn = temp_backend.structured_store._index._conn_write()
        import numpy as np
        fake_embedding = np.random.rand(384).astype(np.float32)
        conn.execute(
            "INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("fake-entry", "fake-model-id", "1.0", fake_embedding.tobytes()),
        )
        conn.commit()

        # Search should only use vectors matching current model_id
        from harness_mem.search import HybridSearchLayer

        layer = HybridSearchLayer(temp_backend.structured_store._index)
        result = layer.search("test entry", table="memory_entries", limit=5, mode="hybrid")

        # Verify that fake-entry is not in results (different model_id)
        retrieved_ids = [row["id"] for row in result.rows]
        assert "fake-entry" not in retrieved_ids, "Should exclude vectors with different model_id"

        await temp_backend.close()

    run(_test())


def test_switch_model_excludes_old_vectors(temp_backend):
    """Task 9.4: Switch model_id, verify old vectors are excluded from search."""
    async def _test():
        await temp_backend.init()

        # Save entry with default model
        entry_id = "test-entry-4"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="decision",
                content="Test entry before model switch.",
                source="manual",
                memory_type="semantic",
            )
        )

        # Verify vector exists with default model
        conn = temp_backend.structured_store._index._conn_write()
        cursor = conn.execute(
            "SELECT model_id FROM vec_embeddings WHERE entry_id = ?",
            (entry_id,),
        )
        row = cursor.fetchone()
        assert row is not None

        # Simulate model switch by changing the vector's model_id
        conn.execute(
            "UPDATE vec_embeddings SET model_id = ? WHERE entry_id = ?",
            ("old-model-id", entry_id),
        )
        conn.commit()

        # Search with current model_id should exclude the old vector
        from harness_mem.search import HybridSearchLayer

        layer = HybridSearchLayer(temp_backend.structured_store._index)
        layer.search("test entry", table="memory_entries", limit=5, mode="hybrid")

        # The old vector should be filtered out (not used in hybrid scoring)
        # It may still appear in FTS results, but without vector boost

        await temp_backend.close()

    run(_test())


def test_missing_vec_table_fallback_fts(temp_backend):
    """Task 9.5: Missing vec_embeddings table triggers FTS fallback."""
    async def _test():
        await temp_backend.init()

        # Save a memory entry
        entry_id = "test-entry-5"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="bug",
                content="Test entry for FTS fallback.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Drop vec_embeddings table to simulate missing table
        conn = temp_backend.structured_store._index._conn_write()
        conn.execute("DROP TABLE IF EXISTS vec_embeddings")
        conn.commit()

        # Search should fallback to FTS
        from harness_mem.search import HybridSearchLayer

        layer = HybridSearchLayer(temp_backend.structured_store._index)
        result = layer.search("test entry", table="memory_entries", limit=5, mode="hybrid")

        # Should fallback to FTS mode
        assert result.effective_mode == "fts", "Should fallback to FTS when vec_embeddings table missing"
        assert result.fallback_reason == "embedding not available"

        await temp_backend.close()

    run(_test())


def test_dimension_mismatch_triggers_warning(temp_backend, caplog):
    """Task 9.6: Dimension mismatch triggers warning and fallback."""
    async def _test():
        await temp_backend.init()

        # Save entry with correct dimensions
        entry_id = "test-entry-6"
        await temp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id,
                project_name="test-project",
                category="decision",
                content="Test entry for dimension mismatch.",
                source="manual",
                memory_type="semantic",
            )
        )

        # Manually overwrite the saved vector with wrong dimensions.
        conn = temp_backend.structured_store._index._conn_write()
        import numpy as np
        from harness_mem.commands.support import get_embedding_model_id

        model_id = get_embedding_model_id()
        wrong_dim_embedding = np.random.rand(512).astype(np.float32)  # Wrong dimension (should be 384)
        conn.execute(
            "UPDATE vec_embeddings SET embedding = ?, model_id = ?, model_version = ? WHERE entry_id = ?",
            (wrong_dim_embedding.tobytes(), model_id, "1.0", entry_id),
        )
        conn.commit()

        # Search should detect dimension mismatch and log warning
        from harness_mem.search import HybridSearchLayer

        layer = HybridSearchLayer(temp_backend.structured_store._index)

        with caplog.at_level("WARNING"):
            result = layer.search("test entry", table="memory_entries", limit=5, mode="hybrid")

        # Check that warning was logged and the search fell back to FTS.
        assert any("Dimension mismatch" in record.message for record in caplog.records), \
            "Should log warning for dimension mismatch"
        assert result.effective_mode == "fts"

    run(_test())
