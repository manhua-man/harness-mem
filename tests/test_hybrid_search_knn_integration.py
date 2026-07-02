"""Integration proof: filtered hybrid vector path uses vec0 KNN when available."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.sqlite_index import SQLiteIndex


def _seed_memory_entry(
    index: SQLiteIndex,
    *,
    entry_id: str,
    content: str,
    status: str,
) -> None:
    now = "2026-01-01T00:00:00+00:00"
    index.insert(
        "memory_entries",
        {
            "id": entry_id,
            "project_name": "knn-integration",
            "category": "note",
            "content": content,
            "confidence": 0.9,
            "status": status,
            "source": "benchmark:knn",
            "created_at": now,
            "updated_at": now,
        },
    )


def _seed_vec_row(
    index: SQLiteIndex,
    *,
    entry_id: str,
    model_id: str,
    blob: bytes,
) -> None:
    conn = index._conn_write()
    conn.execute(
        """
        INSERT OR REPLACE INTO vec_embeddings
        (entry_id, model_id, model_version, embedding, created_at)
        VALUES (?, ?, 'v1', ?, 1)
        """,
        (entry_id, model_id, blob),
    )
    conn.commit()
    index._vec_index.upsert_row(
        conn,
        entry_id=entry_id,
        model_id=model_id,
        embedding_blob=blob,
        dimensions=len(blob) // 4,
    )


def test_hybrid_vector_path_uses_vec0_knn_with_extra_where(tmp_path) -> None:
    pytest.importorskip("sqlite_vec")
    pytest.importorskip("numpy")

    index = SQLiteIndex(tmp_path / "structured.sqlite")
    index.init_db()
    index._vec_index.mark_extension_loaded()

    model_id = "knn-integration-model"
    blob_keep = b"\x00\x00\x80\x3f" + b"\x00" * 4
    blob_drop = b"\x00\x00\x00\x00" + b"\x00\x00\x80\x3f"

    _seed_memory_entry(
        index,
        entry_id="keep",
        content="alpha knn integration token",
        status="user_confirmed",
    )
    _seed_memory_entry(
        index,
        entry_id="drop",
        content="alpha knn integration noise",
        status="pending",
    )
    _seed_vec_row(index, entry_id="keep", model_id=model_id, blob=blob_keep)
    _seed_vec_row(index, entry_id="drop", model_id=model_id, blob=blob_drop)

    layer = HybridSearchLayer(index)
    batch_calls: list[str] = []

    def _batch_must_not_run(*_args, **_kwargs):
        batch_calls.append("called")
        raise AssertionError("batch cosine must not run when vec0 KNN succeeds")

    with (
        patch.object(layer, "_embed_texts", return_value=[[1.0, 0.0]]),
        patch(
            "harness_mem.commands.support.get_embedding_model_id",
            return_value=model_id,
        ),
        patch.object(layer, "_batch_cosine_vector_state", side_effect=_batch_must_not_run),
    ):
        result = layer._score_vector_candidates(
            "alpha knn integration",
            table="memory_entries",
            limit=5,
            extra_where="status = ?",
            extra_params=("user_confirmed",),
        )

    assert result is not None
    assert not batch_calls
    candidate_by_id, sim_scores, _vec_rank = result
    assert set(candidate_by_id) == {"keep"}
    assert "drop" not in sim_scores