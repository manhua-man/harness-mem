from __future__ import annotations

import pytest

from harness_mem.search.hybrid_search import HybridSearchLayer


pytestmark = pytest.mark.storage


class FakeSQLite:
    _rows = [
        {"id": "fts-top", "content": "exact lexical match"},
        {"id": "vector-top", "content": "semantic match"},
    ]

    def search(self, table: str, query: str, limit: int, extra_where=None, extra_params=()):
        assert table == "memory_entries"
        assert query == "vector wins"
        return self._rows[:limit]

    def list(self, table: str, where=None, where_params=(), order_by="updated_at DESC", limit=100):
        assert table == "memory_entries"
        assert order_by == "updated_at DESC"
        return self._rows[:limit]


def _unit_vector_for_similarity(similarity: float) -> list[float]:
    remainder = max(0.0, 1.0 - (similarity * similarity))
    return [similarity, remainder**0.5]


def _patch_persisted_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    layer: HybridSearchLayer,
    embeddings_by_id: dict[str, list[float]],
) -> None:
    def fake_read_persisted_embeddings(entry_ids: list[str]):
        return {
            entry_id: embeddings_by_id[entry_id]
            for entry_id in entry_ids
            if entry_id in embeddings_by_id
        }

    monkeypatch.setattr(
        layer,
        "_read_persisted_embeddings",
        fake_read_persisted_embeddings,
    )


def test_hybrid_search_uses_weighted_rrf(monkeypatch: pytest.MonkeyPatch):
    layer = HybridSearchLayer(FakeSQLite())

    def fake_embed_texts(texts: list[str]):
        assert texts == ["vector wins"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)
    _patch_persisted_embeddings(
        monkeypatch,
        layer,
        {
            "fts-top": [0.0, 1.0],
            "vector-top": [1.0, 0.0],
        },
    )

    result = layer.search("vector wins", table="memory_entries", limit=2, mode="hybrid")

    assert result.effective_mode == "hybrid"
    assert [row["id"] for row in result.rows] == ["vector-top", "fts-top"]
    assert result.rows[0]["_fts_rank"] == 1
    assert result.rows[0]["_vec_rank"] == 0
    assert result.rows[0]["_rrf_score"] == result.rows[0]["_hybrid_score"]


def test_hybrid_search_includes_semantic_candidates_without_fts_hit(
    monkeypatch: pytest.MonkeyPatch,
):
    class SemanticOnlySQLite(FakeSQLite):
        _rows = [
            {"id": "fts-top", "content": "exact lexical match"},
            {"id": "vector-only", "content": "semantic-only match"},
            {"id": "noise-1", "content": "noise"},
            {"id": "noise-2", "content": "more noise"},
        ]

        def search(self, table: str, query: str, limit: int, extra_where=None, extra_params=()):
            assert table == "memory_entries"
            assert query == "vector wins"
            return [{"id": "fts-top", "content": "exact lexical match"}]

    layer = HybridSearchLayer(SemanticOnlySQLite())

    def fake_embed_texts(texts: list[str]):
        assert texts == ["vector wins"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)
    _patch_persisted_embeddings(
        monkeypatch,
        layer,
        {
            "fts-top": [0.0, 1.0],
            "vector-only": [1.0, 0.0],
            "noise-1": [0.0, 1.0],
            "noise-2": [0.0, 1.0],
        },
    )

    result = layer.search("vector wins", table="memory_entries", limit=2, mode="hybrid")

    vector_only = next(row for row in result.rows if row["id"] == "vector-only")
    assert vector_only["_fts_rank"] == -1
    assert vector_only["_vec_rank"] == 0


def test_vector_search_uses_semantic_ranking_without_fts_dependency(
    monkeypatch: pytest.MonkeyPatch,
):
    class SemanticOnlySQLite(FakeSQLite):
        _rows = [
            {"id": "fts-top", "content": "exact lexical match"},
            {"id": "vector-top", "content": "semantic match"},
            {"id": "noise-1", "content": "noise"},
        ]

    layer = HybridSearchLayer(SemanticOnlySQLite())

    def fake_embed_texts(texts: list[str]):
        assert texts == ["vector wins"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)
    _patch_persisted_embeddings(
        monkeypatch,
        layer,
        {
            "fts-top": [0.0, 1.0],
            "vector-top": [1.0, 0.0],
            "noise-1": [0.0, 1.0],
        },
    )

    result = layer.search_vector("vector wins", table="memory_entries", limit=2)

    assert result.effective_mode == "vector"
    assert [row["id"] for row in result.rows] == ["vector-top", "fts-top"]
    assert result.rows[0]["_vec_rank"] == 0
    assert result.rows[0]["_score"] == result.rows[0]["_vec_sim"]


def test_hybrid_search_keeps_strong_lexical_match_when_vector_noise_is_stronger(
    monkeypatch: pytest.MonkeyPatch,
):
    class LexicalRescueSQLite(FakeSQLite):
        _rows = [
            {"id": "vec-top", "content": "vector top", "_fts_score": -0.000001},
            {"id": "vec-mid", "content": "vector mid", "_fts_score": -0.000001},
            {"id": "lexical-answer", "content": "lexical answer", "_fts_score": -3.08},
            {"id": "vec-other", "content": "vector other", "_fts_score": -0.000001},
            {"id": "lexical-support", "content": "lexical support", "_fts_score": -3.24},
            {"id": "lexical-top", "content": "lexical top", "_fts_score": -3.55},
        ]

        def search(self, table: str, query: str, limit: int, extra_where=None, extra_params=()):
            assert query == "road trip hours"
            return self._rows[:limit]

    layer = HybridSearchLayer(LexicalRescueSQLite())
    similarity_by_text = {
        "vector top": 0.2743858735,
        "vector mid": 0.2553843747,
        "lexical answer": 0.1778410306,
        "vector other": 0.2232024699,
        "lexical support": 0.1899386117,
        "lexical top": 0.1500000000,
    }

    def fake_embed_texts(texts: list[str]):
        assert texts == ["road trip hours"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)
    _patch_persisted_embeddings(
        monkeypatch,
        layer,
        {
            row["id"]: _unit_vector_for_similarity(similarity_by_text[row["content"]])
            for row in LexicalRescueSQLite._rows
        },
    )

    result = layer.search("road trip hours", table="memory_entries", limit=5, mode="hybrid")

    assert "lexical-answer" in [row["id"] for row in result.rows]


def test_hybrid_search_keeps_vector_supported_answer_when_fts_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
):
    class SemanticRescueSQLite(FakeSQLite):
        _rows = [
            {"id": "fts-top", "content": "fts top", "_fts_score": -5.34},
            {"id": "fts-mid", "content": "fts mid", "_fts_score": -3.32},
            {"id": "fts-low", "content": "fts low", "_fts_score": -2.40},
            {"id": "semantic-answer", "content": "semantic answer", "_fts_score": -0.000001},
            {"id": "vec-top", "content": "vec top", "_fts_score": -0.000001},
            {"id": "vec-mid", "content": "vec mid", "_fts_score": -0.000001},
        ]

        def search(self, table: str, query: str, limit: int, extra_where=None, extra_params=()):
            assert query == "dinner ingredients"
            return self._rows[:limit]

    layer = HybridSearchLayer(SemanticRescueSQLite())
    similarity_by_text = {
        "fts top": 0.3777057334,
        "fts mid": 0.4849217940,
        "fts low": 0.1800000000,
        "semantic answer": 0.3383512080,
        "vec top": 0.5322946333,
        "vec mid": 0.3822347529,
    }

    def fake_embed_texts(texts: list[str]):
        assert texts == ["dinner ingredients"]
        return [[1.0, 0.0]]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)
    _patch_persisted_embeddings(
        monkeypatch,
        layer,
        {
            row["id"]: _unit_vector_for_similarity(similarity_by_text[row["content"]])
            for row in SemanticRescueSQLite._rows
        },
    )

    result = layer.search("dinner ingredients", table="memory_entries", limit=5, mode="hybrid")

    assert "semantic-answer" in [row["id"] for row in result.rows]
