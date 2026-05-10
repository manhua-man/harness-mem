"""HybridSearchLayer — FTS + optional vector search via Reciprocal Rank Fusion."""

from __future__ import annotations
import builtins
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness_mem.storage.sqlite_index import SQLiteIndex


@dataclass
class SearchResult:
    rows: list[dict[str, Any]]
    requested_mode: str
    effective_mode: str
    fallback_reason: str | None = None


class HybridSearchLayer:
    """Hybrid search layer combining FTS5 with optional vector embeddings.

    Lazy-loads the embedding model. Falls back to pure FTS when
    no embedding is available or on any embedding error.
    """

    def __init__(self, sqlite_index: "SQLiteIndex"):
        self._sqlite = sqlite_index
        self._embedding_model: Any | None = None
        self._embedding_loaded = False
        self._mode = "auto"

    def set_mode(self, mode: str) -> None:
        """Set search mode: fts, hybrid, or auto."""
        if mode not in ("fts", "hybrid", "auto"):
            raise ValueError(f"Invalid mode: {mode}. Must be fts, hybrid, or auto.")
        self._mode = mode

    def mode(self) -> str:
        """Return current search mode."""
        return self._mode

    def _ensure_embedding(self) -> bool:
        """Lazy-load embedding model. Returns True if loaded."""
        if self._embedding_loaded:
            return self._embedding_model is not None
        self._embedding_loaded = True
        try:
            import importlib.util
            if importlib.util.find_spec("sentence_transformers") is None:
                return False
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            return True
        except Exception:
            self._embedding_model = None
            return False

    def _embed_texts(self, texts: builtins.list[str]) -> builtins.list[builtins.list[float]] | None:
        """Generate embeddings for texts. Returns None on failure."""
        if not self._ensure_embedding() or self._embedding_model is None:
            return None
        try:
            embeddings = self._embedding_model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception:
            return None

    def search(
        self,
        query: str,
        table: str = "memory_entries",
        limit: int = 20,
        extra_where: str | None = None,
        extra_params: tuple = (),
        mode: str | None = None,
    ) -> SearchResult:
        """Search using current mode (fts/hybrid/auto)."""
        requested_mode = mode or self._mode
        if requested_mode == "fts":
            return SearchResult(
                rows=self._search_fts(query, table, limit, extra_where, extra_params),
                requested_mode=requested_mode,
                effective_mode="fts",
            )
        rows, effective_mode, fallback_reason = self._search_hybrid(
            query, table, limit, extra_where, extra_params,
        )
        return SearchResult(
            rows=rows,
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            fallback_reason=fallback_reason,
        )

    def _search_fts(
        self,
        query: str,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> builtins.list[dict[str, Any]]:
        """Pure FTS5 search."""
        return self._sqlite.search(
            table, query, limit=limit,
            extra_where=extra_where, extra_params=extra_params,
        )

    def _search_hybrid(
        self,
        query: str,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> tuple[builtins.list[dict[str, Any]], str, str | None]:
        """Hybrid search: FTS + vector via weighted Reciprocal Rank Fusion."""
        embeddings = self._embed_texts([query])
        if embeddings is None:
            return (
                self._search_fts(query, table, limit, extra_where, extra_params),
                "fts",
                "embedding not available",
            )

        query_embedding = embeddings[0]

        # FTS candidate pool: 10x limit.
        candidate_limit = limit * 10
        fts_results = self._sqlite.search(
            table, query, limit=candidate_limit,
            extra_where=extra_where, extra_params=extra_params,
        )

        # Semantic retrieval must not be gated only by lexical hits. Pull a
        # bounded recent/all-row pool for vector ranking, then union it with
        # FTS candidates so exact matches are never dropped.
        vector_results = self._list_vector_candidates(
            table,
            limit=max(candidate_limit, 500),
            extra_where=extra_where,
            extra_params=extra_params,
        )
        candidate_by_id: dict[str, dict[str, Any]] = {}
        for row in vector_results:
            candidate_by_id[row["id"]] = row
        for row in fts_results:
            candidate_by_id[row["id"]] = row

        candidates = list(candidate_by_id.values())
        if not candidates:
            return [], "hybrid", None

        content_field = self._content_field(table)
        texts: builtins.list[str] = [str(row.get(content_field, "")) for row in candidates]

        doc_embeddings = self._embed_texts(texts)
        if doc_embeddings is None:
            return fts_results[:limit], "fts", "embedding not available"

        # Compute cosine similarity for each candidate
        sim_scores: dict[str, float] = {}
        for row, doc_emb in zip(candidates, doc_embeddings):
            sim_scores[row["id"]] = self._cosine_similarity(query_embedding, doc_emb)

        fts_rank: dict[str, int] = {
            row["id"]: rank for rank, row in enumerate(fts_results)
        }
        vec_rank: dict[str, int] = {
            row_id: rank
            for rank, (row_id, _) in enumerate(
                sorted(sim_scores.items(), key=lambda item: item[1], reverse=True)
            )
        }

        rrf_k = 40
        vector_weight = 5.0
        fused_scores: dict[str, float] = {}
        for row_id in candidate_by_id:
            score = 0.0
            if row_id in fts_rank:
                score += 1.0 / (rrf_k + fts_rank[row_id])
            if row_id in vec_rank:
                score += vector_weight / (rrf_k + vec_rank[row_id])
            fused_scores[row_id] = score

        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        fused: builtins.list[dict[str, Any]] = []
        for row_id, fused_score in ranked[:limit]:
            row = dict(candidate_by_id[row_id])
            row["_fts_rank"] = fts_rank.get(row_id, -1)
            row["_vec_rank"] = vec_rank.get(row_id, -1)
            row["_vec_sim"] = sim_scores.get(row_id, 0.0)
            row["_rrf_score"] = fused_score
            row["_hybrid_score"] = fused_score
            row["_score"] = fused_score
            fused.append(row)

        return fused, "hybrid", None

    def _list_vector_candidates(
        self,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> builtins.list[dict[str, Any]]:
        order_by = {
            "observations": "timestamp DESC",
            "memory_entries": "updated_at DESC",
            "task_handoffs": "last_activity DESC",
            "rule_candidates": "created_at DESC",
            "confirmed_rules": "confirmed_at DESC",
        }.get(table, "rowid DESC")
        try:
            return self._sqlite.list(
                table,
                where=extra_where,
                where_params=extra_params,
                order_by=order_by,
                limit=limit,
            )
        except Exception:
            try:
                return self._sqlite.list(
                    table,
                    where=extra_where,
                    where_params=extra_params,
                    order_by="rowid DESC",
                    limit=limit,
                )
            except Exception:
                return []

    @staticmethod
    def _content_field(table: str) -> str:
        return {
            "observations": "raw_content",
            "memory_entries": "content",
            "task_handoffs": "summary",
            "rule_candidates": "pattern",
            "confirmed_rules": "pattern",
        }.get(table, "content")

    @staticmethod
    def _cosine_similarity(a: builtins.list[float], b: builtins.list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
