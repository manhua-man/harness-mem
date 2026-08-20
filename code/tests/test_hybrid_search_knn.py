"""Hybrid search vector path with governance filters (extra_where)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from harness_mem.search.hybrid_search import HybridSearchLayer, VectorCandidateState


def test_score_vector_candidates_passes_filtered_entry_ids_to_knn() -> None:
    sqlite = MagicMock()
    sqlite.list.return_value = [
        {"id": "keep", "content": "alpha"},
        {"id": "drop", "content": "beta"},
    ]
    layer = HybridSearchLayer(sqlite)

    captured: dict[str, set[str] | None] = {}

    def fake_knn(
        query_embedding,
        *,
        table,
        candidate_by_id,
        allowed_ids,
        limit,
    ) -> VectorCandidateState:
        captured["allowed_ids"] = set(allowed_ids)
        return VectorCandidateState(
            candidate_by_id=candidate_by_id,
            sim_scores={row_id: 1.0 for row_id in allowed_ids},
        )

    with (
        patch.object(layer, "_embed_texts", return_value=[[0.1, 0.2]]),
        patch.object(layer, "_try_knn_vector_state", side_effect=fake_knn),
    ):
        result = layer._score_vector_candidates(
            "alpha",
            table="memory_entries",
            limit=5,
            extra_where="status = ?",
            extra_params=("user_confirmed",),
        )

    assert result is not None
    sqlite.list.assert_called_once()
    assert captured["allowed_ids"] == {"keep", "drop"}