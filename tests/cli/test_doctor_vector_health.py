"""Tests for doctor command vector index health checks (v1.6.2)."""

from __future__ import annotations

from harness_mem.commands.doctor import cmd_doctor
from harness_mem.core.schemas import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.commands.support import set_active_project
from tests.helpers import run


def test_doctor_detects_missing_vec_table(tmp_path, capsys):
    """Task 9.8: doctor detects HM-201 (missing vec_embeddings table)."""
    async def _test():
        # Setup: create backend and drop vec_embeddings table
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()

        project_name = "test-project"
        set_active_project(project_name)

        # Save a memory entry
        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="test-entry",
                project_name=project_name,
                category="bug",
                content="Test entry.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Drop vec_embeddings table
        conn = backend.structured_store._index._conn_write()
        conn.execute("DROP TABLE IF EXISTS vec_embeddings")
        conn.commit()

        await backend.close()

        # Run doctor
        await cmd_doctor(project_name)
        captured = capsys.readouterr()

        # Should detect HM-201
        assert "HM-201" in captured.out or "Vector index not built" in captured.out, \
            "Doctor should detect missing vec_embeddings table"
        assert "rebuild-vector-index" in captured.out, \
            "Doctor should suggest rebuild command"

    run(_test())


def test_doctor_detects_model_id_mismatch(tmp_path, capsys):
    """Task 9.8: doctor detects HM-201 (model_id mismatch)."""
    async def _test():
        # Setup: create backend with vectors using different model_id
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()

        project_name = "test-project"
        set_active_project(project_name)

        # Save a memory entry
        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="test-entry",
                project_name=project_name,
                category="bug",
                content="Test entry.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Change all vectors to use a different model_id
        conn = backend.structured_store._index._conn_write()
        conn.execute("UPDATE vec_embeddings SET model_id = ?", ("old-model-id",))
        conn.commit()

        await backend.close()

        # Run doctor
        await cmd_doctor(project_name)
        captured = capsys.readouterr()

        # Should detect model_id mismatch
        assert "Vector index uses different model" in captured.out or "model_id" in captured.out, \
            "Doctor should detect model_id mismatch"
        assert "rebuild-vector-index" in captured.out, \
            "Doctor should suggest rebuild command"

    run(_test())


def test_doctor_detects_empty_vec_table(tmp_path, capsys):
    """Task 9.8: doctor detects HM-201 (empty vec_embeddings table)."""
    async def _test():
        # Setup: create backend with memory entries but no vectors
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()

        project_name = "test-project"
        set_active_project(project_name)

        # Save a memory entry (but prevent vector persistence)
        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="test-entry",
                project_name=project_name,
                category="bug",
                content="Test entry.",
                source="manual",
                memory_type="episodic",
            )
        )

        # Delete all vectors
        conn = backend.structured_store._index._conn_write()
        conn.execute("DELETE FROM vec_embeddings")
        conn.commit()

        await backend.close()

        # Run doctor
        await cmd_doctor(project_name)
        captured = capsys.readouterr()

        # Should detect empty vec_embeddings table
        assert "HM-201" in captured.out or "Vector index is empty" in captured.out, \
            "Doctor should detect empty vec_embeddings table"
        assert "rebuild-vector-index" in captured.out, \
            "Doctor should suggest rebuild command"

    run(_test())
