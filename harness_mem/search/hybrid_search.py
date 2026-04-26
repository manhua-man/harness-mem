"""HybridSearchLayer — FTS + optional vector search via Reciprocal Rank Fusion.

Supports mode=auto|fts|hybrid:
- fts: pure SQLite FTS5 search
- hybrid: combine FTS + vector similarity using RRF
- auto: use hybrid if embedding model loaded, otherwise fall back to fts
"""

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

        if requested_mode == "hybrid":
            rows, effective_mode, fallback_reason = self._search_hybrid(
                query,
                table,
                limit,
                extra_where,
                extra_params,
            )
            return SearchResult(
                rows=rows,
                requested_mode=requested_mode,
                effective_mode=effective_mode,
                fallback_reason=fallback_reason,
            )

        # auto mode: try hybrid, fall back to fts
        rows, effective_mode, fallback_reason = self._search_hybrid(
            query,
            table,
            limit,
            extra_where,
            extra_params,
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
        return self._sqlite.search(table, query, limit=limit, extra_where=extra_where, extra_params=extra_params)

    def _search_hybrid(
        self,
        query: str,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> tuple[builtins.list[dict[str, Any]], str, str | None]:
        """Hybrid search: FTS + vector similarity via Reciprocal Rank Fusion."""
        embeddings = self._embed_texts([query])
        if embeddings is None:
            return (
                self._search_fts(query, table, limit, extra_where, extra_params),
                "fts",
                "embedding not available",
            )

        query_embedding = embeddings[0]

        # FTS candidate pool (3x limit for better recall)
        candidate_limit = limit * 3
        fts_results = self._sqlite.search(
            table, query, limit=candidate_limit, extra_where=extra_where, extra_params=extra_params
        )

        # Build FTS rank map: id -> rank (0-based)
        fts_rank: dict[str, int] = {}
        for rank, row in enumerate(fts_results):
            fts_rank[row["id"]] = rank

        if not fts_results:
            return [], "hybrid", None

        content_field = "raw_content" if table == "observations" else "content"
        texts: builtins.list[str] = [str(row.get(content_field, "")) for row in fts_results]

        doc_embeddings = self._embed_texts(texts)
        if doc_embeddings is None:
            return fts_results[:limit], "fts", "embedding not available"

        # Compute vector similarity for all candidates
        sim_scores: dict[str, float] = {}
        for row, doc_emb in zip(fts_results, doc_embeddings):
            sim_scores[row["id"]] = self._cosine_similarity(query_embedding, doc_emb)

        # Build vector rank map: id -> rank (0-based, sorted by similarity desc)
        sorted_by_sim = sorted(sim_scores.items(), key=lambda x: x[1], reverse=True)
        vec_rank: dict[str, int] = {}
        for rank, (row_id, _) in enumerate(sorted_by_sim):
            vec_rank[row_id] = rank

        # Reciprocal Rank Fusion: combine two rank lists
        # RRF(k=60) is the standard default — smooth blending, no calibration needed
        RRF_K = 60
        rrf_scores: dict[str, float] = {}
        for row_id in fts_rank:
            rrf = 0.0
            if row_id in fts_rank:
                rrf += 1.0 / (RRF_K + fts_rank[row_id])
            if row_id in vec_rank:
                rrf += 1.0 / (RRF_K + vec_rank[row_id])
            rrf_scores[row_id] = rrf

        # Attach debug scores and sort by RRF
        id_to_row: dict[str, dict[str, Any]] = {row["id"]: row for row in fts_results}
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        fused: builtins.list[dict[str, Any]] = []
        for row_id, rrf_score in ranked[:limit]:
            row = dict(id_to_row[row_id])
            row["_fts_score"] = fts_rank.get(row_id, -1)
            row["_vec_sim"] = sim_scores.get(row_id, 0.0)
            row["_rrf_score"] = rrf_score
            row["_score"] = rrf_score
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
