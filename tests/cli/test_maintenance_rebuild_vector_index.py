"""Tests for maintenance rebuild-vector-index command (v1.6.2)."""

from __future__ import annotations

from harness_mem.commands.maintenance import cmd_rebuild_vector_index
from harness_mem.core.schemas import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import requires_embeddings, run


@requires_embeddings
def test_rebuild_vector_index_drops_and_recreates(data_dir):
    """Task 9.7: rebuild-vector-index drops and recreates table."""
    async def _test():
        # Setup: create backend with some memory entries
        backend = LocalMemoryBackend(data_dir)
        await backend.init()

        project_name = "test-project"
        entry_id_1 = "entry-1"
        entry_id_2 = "entry-2"

        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id_1,
                project_name=project_name,
                category="bug",
                content="First test entry.",
                source="manual",
                memory_type="episodic",
            )
        )
        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id=entry_id_2,
                project_name=project_name,
                category="decision",
                content="Second test entry.",
                source="manual",
                memory_type="semantic",
            )
        )

        # Verify vectors exist
        conn = backend.structured_store._index._conn_write()
        cursor = conn.execute("SELECT COUNT(*) FROM vec_embeddings")
        count_before = cursor.fetchone()[0]
        assert count_before >= 2, "Should have at least 2 vectors"

        # Manually corrupt a vector (wrong model_id)
        conn.execute(
            "UPDATE vec_embeddings SET model_id = ? WHERE entry_id = ?",
            ("corrupted-model", entry_id_1),
        )
        conn.commit()

        await backend.close()

        # Run rebuild command
        result = await cmd_rebuild_vector_index(project_name)
        assert result == 0, "Rebuild command should succeed"

        # Verify: table was recreated with correct vectors
        backend2 = LocalMemoryBackend(data_dir)
        await backend2.init()

        conn2 = backend2.structured_store._index._conn_write()
        cursor2 = conn2.execute("SELECT COUNT(*) FROM vec_embeddings")
        count_after = cursor2.fetchone()[0]
        assert count_after >= 2, "Should have rebuilt vectors"

        # Verify corrupted vector was fixed
        cursor3 = conn2.execute(
            "SELECT model_id FROM vec_embeddings WHERE entry_id = ?",
            (entry_id_1,),
        )
        row = cursor3.fetchone()
        assert row is not None
        assert row[0] == "all-MiniLM-L6-v2", "Should have correct model_id after rebuild"

        await backend2.close()

    run(_test())
