"""sqlite-vec vec0 index helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.storage.sqlite_index import SQLiteIndex
from harness_mem.storage.sqlite_vec_index import SqliteVecIndex


def test_vec0_lazy_backfill_indexes_missing_rows(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")
    index = SQLiteIndex(tmp_path / "structured_index.sqlite")
    index.init_db()
    conn = index._conn_write()
    index._vec_index.mark_extension_loaded()

    blob_a = b"\x00\x00\x80\x3f" + b"\x00" * 4
    blob_b = b"\x00\x00\x00\x00" + b"\x00\x00\x80\x3f"
    conn.execute(
        """
        INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at)
        VALUES ('a', 'demo-model', 'v1', ?, 1),
               ('b', 'demo-model', 'v1', ?, 2)
        """,
        (blob_a, blob_b),
    )
    conn.commit()

    vec = SqliteVecIndex()
    vec.mark_extension_loaded()
    backfilled = vec._backfill_missing_rows(
        conn,
        model_id="demo-model",
        dimensions=2,
        entry_ids={"a", "b"},
    )
    assert backfilled == 2

    hits = vec.knn_vec_embeddings(
        conn,
        blob_a,
        model_id="demo-model",
        limit=2,
        entry_ids={"a", "b"},
    )
    assert hits is not None
    assert {row_id for row_id, _ in hits} <= {"a", "b"}


def test_knn_respects_entry_id_filter(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")
    index = SQLiteIndex(tmp_path / "structured_index.sqlite")
    index.init_db()
    conn = index._conn_write()
    vec = index._vec_index
    vec.mark_extension_loaded()

    blob_a = b"\x00\x00\x80\x3f" + b"\x00" * 4
    blob_b = b"\x00\x00\x00\x00" + b"\x00\x00\x80\x3f"
    for entry_id, blob in (("a", blob_a), ("b", blob_b)):
        vec.upsert_row(
            conn,
            entry_id=entry_id,
            model_id="demo-model",
            embedding_blob=blob,
            dimensions=2,
        )

    hits = vec.knn_vec_embeddings(
        conn,
        blob_a,
        model_id="demo-model",
        limit=5,
        entry_ids={"a"},
    )
    assert hits is not None
    assert hits and hits[0][0] == "a"


def test_rebuild_from_embeddings_indexes_all_rows(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")
    index = SQLiteIndex(tmp_path / "structured_index.sqlite")
    index.init_db()
    conn = index._conn_write()
    vec = index._vec_index
    vec.mark_extension_loaded()

    blob_a = b"\x00\x00\x80\x3f" + b"\x00" * 4
    blob_b = b"\x00\x00\x00\x00" + b"\x00\x00\x80\x3f"
    conn.execute(
        """
        INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at)
        VALUES ('a', 'demo-model', 'v1', ?, 1),
               ('b', 'demo-model', 'v1', ?, 2)
        """,
        (blob_a, blob_b),
    )
    conn.commit()

    indexed = vec.rebuild_from_embeddings(conn, model_id="demo-model")
    assert indexed == 2
    report = vec.vec0_coverage_report(conn, model_id="demo-model")
    assert report["vec0_missing"] == 0


def test_vec0_coverage_report_counts_missing(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "structured_index.sqlite")
    index.init_db()
    conn = index._conn_write()
    conn.execute(
        """
        INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at)
        VALUES ('only', 'demo-model', 'v1', ?, 1)
        """,
        (b"\x00\x00\x80\x3f" + b"\x00" * 4,),
    )
    conn.commit()
    report = index._vec_index.vec0_coverage_report(conn, model_id="demo-model")
    assert report["vec_embeddings"] == 1
    assert report["vec0_indexed"] == 0
    assert report["vec0_missing"] == 1