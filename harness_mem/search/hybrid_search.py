"""HybridSearchLayer — FTS + optional vector search via Reciprocal Rank Fusion."""

from __future__ import annotations
import builtins
import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from harness_mem.storage.sqlite_index import SQLiteIndex


# RRF + confidence-factor defaults.
#
# The exponents below shape per-source confidence factors after we min-max
# normalize each source's scores into [0, 1]. With exponent = 1 the factor is
# linear; with exponent = 2 we square the normalized score, biasing the fusion
# toward documents the source is highly confident about and damping mid-rank
# noise. We use 2.0 for vector because cosine similarities cluster tightly
# (most candidates fall in 0.4 - 0.7) and a linear factor lets borderline
# matches outvote a sharp top-1; FTS scores are already long-tailed via bm25
# rank, so 1.0 keeps that signal as-is.
#
# These values were chosen by inspection during recall analysis. They are NOT
# the result of a grid search: probe replays showed adjusting RRF weights or
# these exponents alone did not produce a net R@5 improvement. The recall lift
# came from a Porter-stem FTS fallback in SQLiteIndex.search(). Treat these as
# conservative starting points and re-evaluate alongside any embedding-model
# upgrade.
DEFAULT_RRF_K = 40
DEFAULT_FTS_WEIGHT = 2.0
DEFAULT_VECTOR_WEIGHT = 6.0
DEFAULT_FTS_CONFIDENCE_EXPONENT = 1.0
DEFAULT_VECTOR_CONFIDENCE_EXPONENT = 2.0

logger = logging.getLogger(__name__)


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
        self._rrf_k = DEFAULT_RRF_K
        self._fts_weight = DEFAULT_FTS_WEIGHT
        self._vector_weight = DEFAULT_VECTOR_WEIGHT
        self._fts_confidence_exponent = DEFAULT_FTS_CONFIDENCE_EXPONENT
        self._vector_confidence_exponent = DEFAULT_VECTOR_CONFIDENCE_EXPONENT

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
            from harness_mem.embedding import embeddings_disabled
            if embeddings_disabled():
                # Opt-out escape hatch (HARNESS_MEM_DISABLE_EMBEDDINGS): never
                # load the model; hybrid search degrades to FTS-only.
                return False
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
        try:
            from harness_mem.commands.support import get_embedding_model_id
            from harness_mem.embedding import embeddings_disabled, get_model_loader

            if embeddings_disabled():
                return None
            model_id = get_embedding_model_id()
            loader = get_model_loader(model_id)
            embeddings = loader.encode(texts)
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

    def search_vector(
        self,
        query: str,
        table: str = "memory_entries",
        limit: int = 20,
        extra_where: str | None = None,
        extra_params: tuple = (),
    ) -> SearchResult:
        """Semantic-only search used by diagnostics and retrieval checks."""
        rows, effective_mode, fallback_reason = self._search_vector_only(
            query,
            table,
            limit,
            extra_where,
            extra_params,
        )
        return SearchResult(
            rows=rows,
            requested_mode="vector",
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
        candidate_limit = limit * 10
        fts_results = self._sqlite.search(
            table, query, limit=candidate_limit,
            extra_where=extra_where, extra_params=extra_params,
        )
        vector_state = self._score_vector_candidates(
            query,
            table,
            limit=limit,
            extra_where=extra_where,
            extra_params=extra_params,
            seed_rows=fts_results,
        )
        if vector_state is None:
            return fts_results[:limit], "fts", "embedding not available"
        candidate_by_id, sim_scores, vec_rank = vector_state

        fts_rank: dict[str, int] = {
            row["id"]: rank for rank, row in enumerate(fts_results)
        }
        fts_confidence = self._confidence_factors_from_scores(
            {
                row["id"]: (
                    abs(float(row.get("_fts_score_total", row.get("_fts_score", 0.0))))
                    * max(1, int(row.get("_fts_match_count", 1)))
                )
                for row in fts_results
            },
            exponent=self._fts_confidence_exponent,
        )
        vector_confidence = self._confidence_factors_from_scores(
            sim_scores,
            exponent=self._vector_confidence_exponent,
        )

        fused_scores: dict[str, float] = {}
        for row_id in candidate_by_id:
            score = 0.0
            if row_id in fts_rank:
                score += (
                    self._fts_weight
                    * fts_confidence.get(row_id, 1.0)
                    / (self._rrf_k + fts_rank[row_id])
                )
            if row_id in vec_rank:
                score += (
                    self._vector_weight
                    * vector_confidence.get(row_id, 1.0)
                    / (self._rrf_k + vec_rank[row_id])
                )
            fused_scores[row_id] = score

        ranked = sorted(
            fused_scores.items(),
            key=lambda item: -item[1],
        )
        fused: builtins.list[dict[str, Any]] = []
        for row_id, fused_score in ranked[:limit]:
            row = dict(candidate_by_id[row_id])
            row["_fts_rank"] = fts_rank.get(row_id, -1)
            row["_vec_rank"] = vec_rank.get(row_id, -1)
            row["_vec_sim"] = sim_scores.get(row_id, 0.0)
            row["_fts_factor"] = fts_confidence.get(row_id, 0.0)
            row["_vec_factor"] = vector_confidence.get(row_id, 0.0)
            row["_rrf_score"] = fused_score
            row["_hybrid_score"] = fused_score
            row["_score"] = fused_score
            fused.append(row)

        return fused, "hybrid", None

    def _search_vector_only(
        self,
        query: str,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> tuple[builtins.list[dict[str, Any]], str, str | None]:
        vector_state = self._score_vector_candidates(
            query,
            table,
            limit=limit,
            extra_where=extra_where,
            extra_params=extra_params,
        )
        if vector_state is None:
            return (
                self._search_fts(query, table, limit, extra_where, extra_params),
                "fts",
                "embedding not available",
            )

        candidate_by_id, sim_scores, vec_rank = vector_state
        ranked = sorted(
            sim_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        rows: builtins.list[dict[str, Any]] = []
        for row_id, score in ranked[:limit]:
            row = dict(candidate_by_id[row_id])
            row["_vec_rank"] = vec_rank[row_id]
            row["_vec_sim"] = score
            row["_score"] = score
            rows.append(row)
        return rows, "vector", None

    def _score_vector_candidates(
        self,
        query: str,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
        seed_rows: Sequence[dict[str, Any]] | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, float],
        dict[str, int],
    ] | None:
        embeddings = self._embed_texts([query])
        if embeddings is None:
            return None

        query_embedding = embeddings[0]
        candidate_limit = max(limit * 10, 500)
        vector_results = self._list_vector_candidates(
            table,
            limit=candidate_limit,
            extra_where=extra_where,
            extra_params=extra_params,
        )
        candidate_by_id = {row["id"]: row for row in vector_results}
        if seed_rows:
            for row in seed_rows:
                candidate_by_id[row["id"]] = row
        if not candidate_by_id:
            return {}, {}, {}

        candidates = list(candidate_by_id.values())

        # v1.6.2: Read persisted embeddings from vec_embeddings table.
        # If the table is missing, empty, or no rows survive filtering, fall
        # back to FTS rather than re-encoding documents on the hot path.
        doc_embeddings_dict = self._read_persisted_embeddings(
            [row["id"] for row in candidates]
        )
        if doc_embeddings_dict is None:
            return None

        sim_scores: dict[str, float] = {}
        for row in candidates:
            doc_emb = doc_embeddings_dict.get(row["id"])
            if doc_emb is not None:
                sim_scores[row["id"]] = self._cosine_similarity(query_embedding, doc_emb)

        vec_rank: dict[str, int] = {
            row_id: rank
            for rank, (row_id, _) in enumerate(
                sorted(sim_scores.items(), key=lambda item: item[1], reverse=True)
            )
        }
        return candidate_by_id, sim_scores, vec_rank

    @staticmethod
    def _confidence_factors_from_scores(
        scores: dict[str, float],
        *,
        exponent: float,
    ) -> dict[str, float]:
        if not scores:
            return {}
        values = list(scores.values())
        lo = min(values)
        hi = max(values)
        if hi <= lo:
            return {row_id: 1.0 for row_id in scores}

        factors: dict[str, float] = {}
        for row_id, value in scores.items():
            normalized = (value - lo) / (hi - lo)
            normalized = max(0.0, min(1.0, normalized))
            factors[row_id] = normalized**exponent if exponent > 0 else 1.0
        return factors

    def _read_persisted_embeddings(
        self, entry_ids: builtins.list[str]
    ) -> dict[str, builtins.list[float]] | None:
        """Read persisted embeddings from vec_embeddings table (v1.6.2).

        Returns dict mapping entry_id to embedding vector (as list of floats).
        Returns ``None`` if the table is missing, empty, or every row is
        filtered out, so the caller can fall back to FTS.
        """
        if not entry_ids:
            return None

        try:
            from harness_mem.commands.support import get_embedding_model_id
            from harness_mem.embedding import get_model_loader
            import numpy as np

            model_id = get_embedding_model_id()
            loader = get_model_loader(model_id)
            expected_dim = loader.dimensions

            # Build SQL query with IN clause
            placeholders = ','.join('?' * len(entry_ids))
            query = f"""
                SELECT entry_id, embedding
                FROM vec_embeddings
                WHERE entry_id IN ({placeholders}) AND model_id = ?
            """
            params = (*entry_ids, model_id)

            with self._sqlite.locked_connection() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
            if not rows:
                logger.warning(
                    "No persisted vectors found for current model_id=%s; falling back to FTS. "
                    "Run: harness-mem maintenance rebuild-vector-index",
                    model_id,
                )
                return None

            result: dict[str, builtins.list[float]] = {}

            for row in rows:
                entry_id = row[0]
                embedding_blob = row[1]

                # Deserialize BLOB to numpy array
                embedding_array = np.frombuffer(embedding_blob, dtype=np.float32)

                # Dimension mismatch detection (v1.6.2)
                if len(embedding_array) != expected_dim:
                    logger.warning(
                        "Dimension mismatch for entry %s: stored=%s, expected=%s. "
                        "Skipping this vector. Run: harness-mem maintenance rebuild-vector-index",
                        entry_id,
                        len(embedding_array),
                        expected_dim,
                    )
                    continue

                result[entry_id] = embedding_array.tolist()

            # Log if all vectors filtered out
            if rows and not result:
                logger.warning(
                    "All %s persisted vectors were filtered out; falling back to FTS. "
                    "Run: harness-mem maintenance rebuild-vector-index",
                    len(rows),
                )
                return None

            return result or None
        except sqlite3.OperationalError as exc:
            if "vec_embeddings" in str(exc):
                logger.warning("vec_embeddings table not found, falling back to FTS")
            else:
                logger.warning("Could not read persisted vectors, falling back to FTS: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Could not read persisted vectors, falling back to FTS: %s", exc)
            return None

    def _list_vector_candidates(
        self,
        table: str,
        limit: int,
        extra_where: str | None,
        extra_params: tuple,
    ) -> builtins.list[dict[str, Any]]:
        timestamp_field = self._timestamp_field(table)
        order_by = f"{timestamp_field} DESC" if timestamp_field else "rowid DESC"
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
    def _timestamp_field(table: str) -> str | None:
        return {
            "observations": "timestamp",
            "memory_entries": "updated_at",
            "task_handoffs": "last_activity",
            "rule_candidates": "created_at",
            "confirmed_rules": "confirmed_at",
        }.get(table)

    @staticmethod
    def _cosine_similarity(a: builtins.list[float], b: builtins.list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
