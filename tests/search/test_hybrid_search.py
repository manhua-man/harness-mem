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


def test_hybrid_search_uses_weighted_rrf(monkeypatch: pytest.MonkeyPatch):
    layer = HybridSearchLayer(FakeSQLite())

    def fake_embed_texts(texts: list[str]):
        if texts == ["vector wins"]:
            return [[1.0, 0.0]]
        return [
            [0.0, 1.0] if text == "exact lexical match" else [1.0, 0.0]
            for text in texts
        ]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)

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
        if texts == ["vector wins"]:
            return [[1.0, 0.0]]
        return [
            [1.0, 0.0] if text == "semantic-only match" else [0.0, 1.0]
            for text in texts
        ]

    monkeypatch.setattr(layer, "_embed_texts", fake_embed_texts)

    result = layer.search("vector wins", table="memory_entries", limit=2, mode="hybrid")

    vector_only = next(row for row in result.rows if row["id"] == "vector-only")
    assert vector_only["_fts_rank"] == -1
    assert vector_only["_vec_rank"] == 0


