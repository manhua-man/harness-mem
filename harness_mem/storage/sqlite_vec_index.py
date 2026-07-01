"""sqlite-vec vec0 index helpers for embedding KNN."""

from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

logger = logging.getLogger(__name__)

VEC0_TABLE = "vec_embeddings_vec0"
VEC_EMBEDDINGS_TABLE = "vec_embeddings"


class SqliteVecIndex:
    """Manage vec0 sidecar storage and KNN queries."""

    def __init__(self) -> None:
        self._sqlite_vec_available = False
        self._vec0_dimension: int | None = None

    def mark_extension_loaded(self) -> None:
        self._sqlite_vec_available = True

    @property
    def available(self) -> bool:
        return self._sqlite_vec_available

    def drop(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"DROP TABLE IF EXISTS {VEC0_TABLE}")
        conn.commit()
        self._vec0_dimension = None

    def upsert_row(
        self,
        conn: sqlite3.Connection,
        *,
        entry_id: str,
        model_id: str,
        embedding_blob: bytes,
        dimensions: int,
    ) -> None:
        if not self._ensure_vec0_table(conn, dimensions):
            return
        try:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {VEC0_TABLE}(entry_id, embedding, model_id)
                VALUES (?, ?, ?)
                """,
                (entry_id, embedding_blob, model_id),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.debug("vec0 upsert skipped for %s: %s", entry_id, exc)

    def knn_vec_embeddings(
        self,
        conn: sqlite3.Connection,
        query_blob: bytes,
        *,
        model_id: str,
        limit: int,
        entry_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]] | None:
        if not self._sqlite_vec_available or not query_blob:
            return None

        dimensions = len(query_blob) // 4
        if dimensions <= 0:
            return None
        if not self._ensure_vec0_table(conn, dimensions):
            return None

        allowed = set(entry_ids) if entry_ids is not None else None
        if allowed is not None and not allowed:
            return []

        self._backfill_missing_rows(
            conn,
            model_id=model_id,
            dimensions=dimensions,
            entry_ids=allowed,
        )

        probe_limit = limit
        if allowed is not None:
            probe_limit = min(max(limit * 3, limit), max(len(allowed), limit))

        try:
            rows = conn.execute(
                f"""
                SELECT entry_id, distance
                FROM {VEC0_TABLE}
                WHERE embedding MATCH ?
                  AND model_id = ?
                  AND k = ?
                ORDER BY distance
                """,
                (query_blob, model_id, probe_limit),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.debug("vec0 KNN unavailable: %s", exc)
            return None

        hits: list[tuple[str, float]] = []
        for entry_id, distance in rows:
            row_id = str(entry_id)
            if allowed is not None and row_id not in allowed:
                continue
            try:
                similarity = 1.0 - float(distance)
            except (TypeError, ValueError):
                similarity = 0.0
            hits.append((row_id, similarity))
            if len(hits) >= limit:
                break
        return hits

    def vec0_coverage_report(
        self,
        conn: sqlite3.Connection,
        *,
        model_id: str,
    ) -> dict[str, int]:
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM {VEC_EMBEDDINGS_TABLE} WHERE model_id = ?",
                (model_id,),
            ).fetchone()[0]
        except sqlite3.Error:
            total = 0
        try:
            indexed = conn.execute(
                f"SELECT COUNT(*) FROM {VEC0_TABLE} WHERE model_id = ?",
                (model_id,),
            ).fetchone()[0]
        except sqlite3.Error:
            indexed = 0
        return {
            "vec_embeddings": int(total),
            "vec0_indexed": int(indexed),
            "vec0_missing": max(0, int(total) - int(indexed)),
        }

    def _ensure_vec0_table(self, conn: sqlite3.Connection, dimensions: int) -> bool:
        if not self._sqlite_vec_available:
            return False
        if self._vec0_dimension not in (None, dimensions):
            return False
        try:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {VEC0_TABLE} USING vec0(
                    entry_id TEXT PRIMARY KEY,
                    embedding float[{dimensions}] distance_metric=cosine,
                    model_id TEXT
                )
                """
            )
            self._vec0_dimension = dimensions
            return True
        except sqlite3.Error as exc:
            logger.debug("vec0 table init failed: %s", exc)
            return False

    def _backfill_missing_rows(
        self,
        conn: sqlite3.Connection,
        *,
        model_id: str,
        dimensions: int,
        entry_ids: set[str] | None,
        batch_limit: int = 500,
    ) -> int:
        if not self._ensure_vec0_table(conn, dimensions):
            return 0

        if entry_ids is not None:
            missing_ids = [
                row_id
                for row_id in entry_ids
                if not self._vec0_has_entry(conn, row_id, model_id)
            ]
            if not missing_ids:
                return 0
            placeholders = ",".join("?" * len(missing_ids))
            rows = conn.execute(
                f"""
                SELECT entry_id, embedding
                FROM {VEC_EMBEDDINGS_TABLE}
                WHERE model_id = ? AND entry_id IN ({placeholders})
                """,
                (model_id, *missing_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT v.entry_id, v.embedding
                FROM {VEC_EMBEDDINGS_TABLE} AS v
                LEFT JOIN {VEC0_TABLE} AS z ON z.entry_id = v.entry_id
                WHERE v.model_id = ? AND z.entry_id IS NULL
                LIMIT ?
                """,
                (model_id, batch_limit),
            ).fetchall()

        backfilled = 0
        for entry_id, embedding_blob in rows:
            if not embedding_blob:
                continue
            self.upsert_row(
                conn,
                entry_id=str(entry_id),
                model_id=model_id,
                embedding_blob=embedding_blob,
                dimensions=dimensions,
            )
            backfilled += 1
        if backfilled:
            logger.info(
                "vec0 lazy backfill: indexed %s row(s) for model_id=%s",
                backfilled,
                model_id,
            )
        return backfilled

    @staticmethod
    def _vec0_has_entry(
        conn: sqlite3.Connection,
        entry_id: str,
        model_id: str,
    ) -> bool:
        try:
            row = conn.execute(
                f"SELECT 1 FROM {VEC0_TABLE} WHERE entry_id = ? AND model_id = ? LIMIT 1",
                (entry_id, model_id),
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None