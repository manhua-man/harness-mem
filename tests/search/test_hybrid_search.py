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


def test_temporal_bias_is_opt_in_tie_breaker(monkeypatch: pytest.MonkeyPatch):
    older = {
        "id": "older-fts",
        "content": "older lexical",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    newer = {
        "id": "newer-vector",
        "content": "newer semantic",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
    decoys = [
        {
            "id": f"decoy-{index}",
            "content": f"decoy {index}",
            "updated_at": "2026-01-15T00:00:00+00:00",
        }
        for index in range(9)
    ]

    class TemporalTieSQLite:
        def search(self, table: str, query: str, limit: int, extra_where=None, extra_params=()):
            assert table == "memory_entries"
            assert query == "tie query"
            return [older][:limit]

        def list(
            self,
            table: str,
            where=None,
            where_params=(),
            order_by="updated_at DESC",
            limit=100,
        ):
            assert table == "memory_entries"
            assert order_by == "updated_at DESC"
            return [older, *decoys, newer][:limit]

    def fake_embed_texts(texts: list[str]):
        if texts == ["tie query"]:
            return [[0.0]]
        embeddings = []
        for text in texts:
            if text == "newer semantic":
                embeddings.append([1.0])
            elif text.startswith("decoy "):
                index = int(text.split()[1])
                embeddings.append([0.9 - index * 0.01])
            else:
                embeddings.append([0.0])
        return embeddings

    default_layer = HybridSearchLayer(TemporalTieSQLite())
    monkeypatch.setattr(default_layer, "_embed_texts", fake_embed_texts)
    monkeypatch.setattr(default_layer, "_cosine_similarity", lambda _query, doc: doc[0])

    biased_layer = HybridSearchLayer(TemporalTieSQLite(), temporal_bias=True)
    monkeypatch.setattr(biased_layer, "_embed_texts", fake_embed_texts)
    monkeypatch.setattr(biased_layer, "_cosine_similarity", lambda _query, doc: doc[0])

    default_result = default_layer.search(
        "tie query", table="memory_entries", limit=2, mode="hybrid"
    )
    biased_result = biased_layer.search(
        "tie query", table="memory_entries", limit=2, mode="hybrid"
    )
    per_call_result = default_layer.search(
        "tie query",
        table="memory_entries",
        limit=2,
        mode="hybrid",
        temporal_bias=True,
    )

    assert default_result.rows[0]["id"] == "older-fts"
    assert biased_result.rows[0]["id"] == "newer-vector"
    assert per_call_result.rows[0]["id"] == "newer-vector"
    assert biased_result.rows[0]["_hybrid_score"] == biased_result.rows[1]["_hybrid_score"]
