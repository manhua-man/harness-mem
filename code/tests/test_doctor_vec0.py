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


def test_doctor_fails_closed_when_vector_probe_cannot_verify(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value="broken-model",
            ), patch(
                "harness_mem.embedding.get_model_loader",
                side_effect=ValueError("invalid embedding config"),
            ):
                health = _check_vector_index_health(backend, "doctor-project")

            assert health["has_issue"] is True
            assert "HM-206" in health["message"]
            assert health["verification_status"] == "unknown"
            assert "rebuild-vector-index" in health["fix_command"]
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_vector_repair_command_uses_safe_project_placeholder(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data-command")
        await backend.init()
        try:
            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value="missing-model",
            ), patch(
                "harness_mem.embedding.get_model_loader",
                side_effect=ValueError("invalid embedding config"),
            ):
                health = _check_vector_index_health(
                    backend,
                    "unsafe; Remove-Item -Recurse project",
                )

            assert health["fix_command"].endswith("--project <PROJECT_NAME>")
            assert "Remove-Item" not in health["fix_command"]
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_fails_closed_when_vec0_manifest_is_missing(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "missing-manifest")
        await backend.init()
        try:
            index = backend.structured_store.index
            assert isinstance(index, SQLiteIndex)
            model_id = "manifest-model"
            blob = b"\x00\x00\x80\x3f" + b"\x00" * 4
            with index.locked_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO vec_embeddings
                    (entry_id, model_id, model_version, embedding, created_at)
                    VALUES ('manifest-row', ?, 'v1', ?, 1)
                    """,
                    (model_id, blob),
                )
                conn.execute(
                    """
                    CREATE TABLE vec_embeddings_vec0 (
                        entry_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL,
                        model_id TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO vec_embeddings_vec0 VALUES ('manifest-row', ?, ?)",
                    (blob, model_id),
                )
                conn.commit()

            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value=model_id,
            ), patch("harness_mem.embedding.get_model_loader") as loader_mock:
                loader_mock.return_value.dimensions = 2
                health = _check_vector_index_health(backend, "doctor-project")

            assert health["has_issue"] is True
            assert "HM-205" in health["message"]
            assert "manifest is missing" in health["message"]
            assert health["verification_status"] == "missing"
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_detects_same_id_vec0_vector_corruption(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "content-corruption")
        await backend.init()
        try:
            index = backend.structured_store.index
            assert isinstance(index, SQLiteIndex)
            model_id = "content-model"
            original = b"\x00\x00\x80\x3f" + b"\x00" * 4
            corrupted = b"\x00" * 4 + b"\x00\x00\x80\x3f"
            with index.locked_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO vec_embeddings
                    (entry_id, model_id, model_version, embedding, created_at)
                    VALUES ('content-row', ?, 'v1', ?, 1)
                    """,
                    (model_id, original),
                )
                conn.execute(
                    """
                    CREATE TABLE vec_embeddings_vec0 (
                        entry_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL,
                        model_id TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO vec_embeddings_vec0 VALUES ('content-row', ?, ?)",
                    (original, model_id),
                )
                conn.commit()
            source = index.embedding_source_identity(model_id=model_id)
            index.record_index_generation(
                index_name="vec0",
                source_generation=f"embeddings-content:{source['content_hash']}",
                row_count=1,
                id_hash=str(source["id_hash"]),
                model_id=model_id,
                dimensions=2,
                metadata={"content_hash": source["content_hash"]},
                activate=True,
            )
            with index.locked_connection() as conn:
                conn.execute(
                    "UPDATE vec_embeddings_vec0 SET embedding = ? "
                    "WHERE entry_id = 'content-row'",
                    (corrupted,),
                )
                conn.commit()

            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value=model_id,
            ), patch("harness_mem.embedding.get_model_loader") as loader_mock:
                loader_mock.return_value.dimensions = 2
                health = _check_vector_index_health(backend, "doctor-project")

            assert health["has_issue"] is True
            assert "HM-205" in health["message"]
            assert "content_hash" in health["message"]
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_accepts_verified_incremental_vec0_growth(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "incremental-growth")
        await backend.init()
        try:
            index = backend.structured_store.index
            assert isinstance(index, SQLiteIndex)
            model_id = "incremental-model"
            first = b"\x00\x00\x80\x3f" + b"\x00" * 4
            second = b"\x00" * 4 + b"\x00\x00\x80\x3f"
            with index.locked_connection() as conn:
                conn.executemany(
                    """
                    INSERT INTO vec_embeddings
                    (entry_id, model_id, model_version, embedding, created_at)
                    VALUES (?, ?, 'v1', ?, 1)
                    """,
                    [("row-1", model_id, first)],
                )
                conn.execute(
                    """
                    CREATE TABLE vec_embeddings_vec0 (
                        entry_id TEXT PRIMARY KEY,
                        embedding BLOB NOT NULL,
                        model_id TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO vec_embeddings_vec0 VALUES ('row-1', ?, ?)",
                    (first, model_id),
                )
                conn.commit()
            source = index.embedding_source_identity(model_id=model_id)
            index.record_index_generation(
                index_name="vec0",
                source_generation=f"embeddings-content:{source['content_hash']}",
                row_count=1,
                id_hash=str(source["id_hash"]),
                model_id=model_id,
                dimensions=2,
                metadata={"content_hash": source["content_hash"]},
                activate=True,
            )
            with index.locked_connection() as conn:
                conn.execute(
                    "INSERT INTO vec_embeddings VALUES ('row-2', ?, 'v1', ?, 2)",
                    (model_id, second),
                )
                conn.execute(
                    "INSERT INTO vec_embeddings_vec0 VALUES ('row-2', ?, ?)",
                    (second, model_id),
                )
                conn.commit()

            with patch(
                "harness_mem.commands.support.get_embedding_model_id",
                return_value=model_id,
            ), patch("harness_mem.embedding.get_model_loader") as loader_mock:
                loader_mock.return_value.dimensions = 2
                health = _check_vector_index_health(backend, "doctor-project")

            assert health["has_issue"] is False
            reports = health["manifest_reports"]
            assert reports[0]["assessment"] == "healthy_incremental"
            assert reports[0]["reason"] == "verified_incremental_growth"
        finally:
            await backend.close()

    asyncio.run(exercise())
