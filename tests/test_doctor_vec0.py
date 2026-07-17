"""Doctor HM-204 vec0 coverage guidance."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_mem.commands.doctor import _check_vector_index_health
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.sqlite_index import SQLiteIndex


async def _exercise_doctor_vec0(data_dir: Path) -> None:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        structured = backend.structured_store
        index = structured.index
        assert isinstance(index, SQLiteIndex)
        index._vec_index.mark_extension_loaded()

        model_id = "doctor-vec0-model"
        blob = b"\x00\x00\x80\x3f" + b"\x00" * 4
        conn = index._conn_write()
        conn.execute(
            """
            INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at)
            VALUES ('doc-row', ?, 'v1', ?, 1)
            """,
            (model_id, blob),
        )
        conn.commit()

        with patch(
            "harness_mem.commands.support.get_embedding_model_id",
            return_value=model_id,
        ), patch(
            "harness_mem.embedding.get_model_loader",
        ) as loader_mock:
            loader_mock.return_value.dimensions = 2
            before = _check_vector_index_health(backend, "doctor-project")

        assert before["has_issue"] is True
        assert "HM-204" in before["message"]
        assert "rebuild-vector-index" in before["fix_command"]

        indexed = index.rebuild_vec0_index(model_id=model_id)
        assert indexed == 1

        with patch(
            "harness_mem.commands.support.get_embedding_model_id",
            return_value=model_id,
        ), patch(
            "harness_mem.embedding.get_model_loader",
        ) as loader_mock:
            loader_mock.return_value.dimensions = 2
            after = _check_vector_index_health(backend, "doctor-project")

        assert after["has_issue"] is False
    finally:
        await backend.close()


def test_doctor_reports_hm204_then_clears_after_vec0_rebuild(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")
    asyncio.run(_exercise_doctor_vec0(tmp_path / "data"))


def test_doctor_accepts_verbatim_only_vector_index(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")

    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            index = backend.verbatim_store.index
            assert isinstance(index, SQLiteIndex)
            index._vec_index.mark_extension_loaded()
            model_id = "doctor-verbatim-model"
            blob = b"\x00\x00\x80\x3f" + b"\x00" * 4
            conn = index._conn_write()
            conn.execute(
                """
                INSERT INTO vec_embeddings (
                    entry_id, model_id, model_version, embedding, created_at
                ) VALUES ('observation-row', ?, 'v1', ?, 1)
                """,
                (model_id, blob),
            )
            conn.commit()
            assert index.rebuild_vec0_index(model_id=model_id) == 1

            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value=model_id,
            ), patch(
                "harness_mem.embedding.get_model_loader",
            ) as loader_mock:
                loader_mock.return_value.dimensions = 2
                health = _check_vector_index_health(backend, "doctor-project")

            assert health["has_issue"] is False
        finally:
            await backend.close()

    asyncio.run(exercise())
