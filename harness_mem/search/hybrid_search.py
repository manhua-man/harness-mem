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
        """Hybrid search: FTS + vector via score-level fusion.

        Fuses normalized BM25 and cosine-similarity scores directly. RRF discards
        magnitude information; score fusion preserves it, making rank-5 vs rank-50
        vector similarity distinguishable.
        """
        embeddings = self._embed_texts([query])
        if embeddings is None:
            return (
                self._search_fts(query, table, limit, extra_where, extra_params),
                "fts",
                "embedding not available",
            )

        query_embedding = embeddings[0]

        # FTS candidate pool: 10x limit
        candidate_limit = limit * 10
        fts_results = self._sqlite.search(
            table, query, limit=candidate_limit,
            extra_where=extra_where, extra_params=extra_params,
        )
        if not fts_results:
            return [], "hybrid", None

        content_field = "raw_content" if table == "observations" else "content"
        texts: builtins.list[str] = [str(row.get(content_field, "")) for row in fts_results]

        doc_embeddings = self._embed_texts(texts)
        if doc_embeddings is None:
            return fts_results[:limit], "fts", "embedding not available"

        # Collect raw BM25 scores
        bm_raws: list[float] = []
        for row in fts_results:
            raw_score = row.get("score", 0.0)
            bm_raws.append(float(raw_score))

        fts_min = min(bm_raws) if bm_raws else 0.0
        fts_max = max(bm_raws) if bm_raws else 0.0
        fts_range = fts_max - fts_min

        # Compute cosine similarity for each candidate
        sim_scores: dict[str, float] = {}
        for row, doc_emb in zip(fts_results, doc_embeddings):
            sim_scores[row["id"]] = self._cosine_similarity(query_embedding, doc_emb)

        # Score-level fusion: W_FTS * norm_BM25 + W_VEC * cos_sim
        W_FTS = 0.4
        W_VEC = 0.6
        fused_scores: dict[str, float] = {}
        for row in fts_results:
            row_id = row["id"]
            bm_raw = float(row.get("score", 0.0))
            # Normalize BM25: most negative (best) -> 1.0, least negative (worst) -> 0.0
            bm_norm = 1.0 - (bm_raw - fts_min) / fts_range if fts_range != 0 else 0.5
            vec_sim = sim_scores.get(row_id, 0.0)
            fused_scores[row_id] = W_FTS * bm_norm + W_VEC * vec_sim

        id_to_row: dict[str, dict[str, Any]] = {row["id"]: row for row in fts_results}
        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        fused: builtins.list[dict[str, Any]] = []
        for row_id, fused_score in ranked[:limit]:
            row = dict(id_to_row[row_id])
            bm_r = float(row.get("score", 0.0))
            bm_n = 1.0 - (bm_r - fts_min) / fts_range if fts_range != 0 else 0.5
            row["_fts_norm"] = bm_n
            row["_vec_sim"] = sim_scores.get(row_id, 0.0)
            row["_fused_score"] = fused_score
            row["_score"] = fused_score
            fused.append(row)

        return fused, "hybrid", None

    @staticmethod
    def _cosine_similarity(a: builtins.list[float], b: builtins.list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
