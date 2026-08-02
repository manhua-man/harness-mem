"""sqlite-vec vec0 index helpers for embedding KNN."""

from __future__ import annotations

import logging
import hashlib
import sqlite3
from collections.abc import Callable, Iterable
from uuid import uuid4

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

    def drop(self, conn: sqlite3.Connection, *, table_name: str = VEC0_TABLE) -> None:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()
        if table_name == VEC0_TABLE:
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

    def rebuild_from_embeddings(
        self,
        conn: sqlite3.Connection,
        *,
        model_id: str,
        batch_limit: int = 500,
        failpoint: Callable[[str], None] | None = None,
        publish_generation: (
            Callable[[sqlite3.Connection, int, tuple[str, ...], int, str], None]
            | None
        ) = None,
    ) -> int:
        """Rebuild vec0 from ``vec_embeddings`` rows for one model."""

        if not self._sqlite_vec_available:
            return 0
        try:
            row = conn.execute(
                f"""
                SELECT length(embedding)
                FROM {VEC_EMBEDDINGS_TABLE}
                WHERE model_id = ?
                LIMIT 1
                """,
                (model_id,),
            ).fetchone()
        except sqlite3.Error:
            return 0
        if not row or not row[0]:
            return 0
        dimensions = int(row[0]) // 4
        if dimensions <= 0:
            return 0

        staging_table = f"{VEC0_TABLE}_staging_{uuid4().hex}"
        # Build a complete staged virtual table first. The active table is
        # untouched until validation succeeds. Publication recreates it inside
        # one transaction because sqlite-vec shadow tables cannot be renamed.
        try:
            rows = conn.execute(
                f"""
                SELECT entry_id, embedding
                FROM {VEC_EMBEDDINGS_TABLE}
                WHERE model_id = ?
                """,
                (model_id,),
            ).fetchall()
        except sqlite3.Error:
            return 0

        if not self._ensure_vec0_table(
            conn,
            dimensions,
            table_name=staging_table,
        ):
            self.drop(conn, table_name=staging_table)
            return 0
        valid_rows = [
            (str(entry_id), embedding_blob, model_id)
            for entry_id, embedding_blob in rows
            if embedding_blob
        ]
        source_fingerprint = self.stable_vector_fingerprint(valid_rows)
        previous_dimension = self._vec0_dimension
        try:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO {staging_table}(entry_id, embedding, model_id)
                VALUES (?, ?, ?)
                """,
                valid_rows,
            )
            if failpoint is not None:
                failpoint("after_staging_write")
            indexed = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {staging_table} WHERE model_id = ?",
                    (model_id,),
                ).fetchone()[0]
            )
            if indexed != len(valid_rows):
                raise sqlite3.IntegrityError(
                    f"staged vec0 row mismatch: {indexed} != {len(valid_rows)}"
                )
            staged_rows = conn.execute(
                f"SELECT entry_id, embedding, model_id FROM {staging_table}"
            ).fetchall()
            staged_fingerprint = self.stable_vector_fingerprint(
                (str(row[0]), bytes(row[1]), str(row[2])) for row in staged_rows
            )
            if staged_fingerprint != source_fingerprint:
                raise sqlite3.IntegrityError("staged vec0 content mismatch")
            # Finish the staging transaction before opening the publication
            # transaction. Without this commit, BEGIN IMMEDIATE fails with
            # "cannot start a transaction within a transaction" and the
            # previous implementation silently reported a zero-row rebuild.
            conn.commit()
            if failpoint is not None:
                failpoint("after_staging_validation")

            conn.execute("BEGIN IMMEDIATE")
            current_rows = conn.execute(
                f"""
                SELECT entry_id, embedding
                FROM {VEC_EMBEDDINGS_TABLE}
                WHERE model_id = ?
                """,
                (model_id,),
            ).fetchall()
            current_source = [
                (str(entry_id), embedding_blob, model_id)
                for entry_id, embedding_blob in current_rows
                if embedding_blob
            ]
            if self.stable_vector_fingerprint(current_source) != source_fingerprint:
                raise sqlite3.IntegrityError(
                    "embedding source changed during vec0 rebuild"
                )
            publish_rows = conn.execute(
                f"SELECT entry_id, embedding, model_id FROM {staging_table}"
            ).fetchall()
            publish_fingerprint = self.stable_vector_fingerprint(
                (str(row[0]), bytes(row[1]), str(row[2])) for row in publish_rows
            )
            if publish_fingerprint != staged_fingerprint:
                raise sqlite3.IntegrityError(
                    "vec0 staging content changed before publish"
                )
            if failpoint is not None:
                failpoint("after_source_validation")
            conn.execute(f"DROP TABLE IF EXISTS {VEC0_TABLE}")
            self._vec0_dimension = None
            if failpoint is not None:
                failpoint("after_active_drop")
            if not self._ensure_vec0_table(conn, dimensions):
                raise sqlite3.IntegrityError("active vec0 table could not be created")
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO {VEC0_TABLE}(entry_id, embedding, model_id)
                VALUES (?, ?, ?)
                """,
                publish_rows,
            )
            active_rows = conn.execute(
                f"SELECT entry_id, embedding, model_id FROM {VEC0_TABLE}"
            ).fetchall()
            active_fingerprint = self.stable_vector_fingerprint(
                (str(row[0]), bytes(row[1]), str(row[2])) for row in active_rows
            )
            if active_fingerprint != publish_fingerprint:
                raise sqlite3.IntegrityError(
                    "published vec0 content does not match staging"
                )
            if publish_generation is not None:
                publish_generation(
                    conn,
                    indexed,
                    tuple(sorted(row[0] for row in valid_rows)),
                    dimensions,
                    publish_fingerprint,
                )
            if failpoint is not None:
                failpoint("before_publish_commit")
            conn.execute(f"DROP TABLE {staging_table}")
            conn.commit()
            self._vec0_dimension = dimensions
        except Exception as exc:
            conn.rollback()
            self._vec0_dimension = previous_dimension
            # A publication rollback restores the old active table. Remove a
            # residual staging generation separately; cleanup failure is
            # logged but never converted into a successful rebuild.
            try:
                conn.execute(f"DROP TABLE IF EXISTS {staging_table}")
                conn.commit()
            except sqlite3.Error as cleanup_exc:
                conn.rollback()
                logger.warning(
                    "vec0 staging cleanup failed after rebuild error: %s",
                    cleanup_exc,
                )
            logger.debug("vec0 batch rebuild unavailable: %s", exc)
            return 0

        if indexed:
            logger.info(
                "vec0 rebuild: indexed %s row(s) for model_id=%s",
                indexed,
                model_id,
            )
        return indexed

    @staticmethod
    def stable_vector_fingerprint(rows: Iterable[tuple[str, bytes, str]]) -> str:
        digest = hashlib.sha256()
        for entry_id, embedding_blob, model_id in sorted(rows, key=lambda row: row[0]):
            digest.update(entry_id.encode("utf-8"))
            digest.update(b"\0")
            digest.update(model_id.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes(embedding_blob))
            digest.update(b"\n")
        return digest.hexdigest()

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

    def _ensure_vec0_table(
        self,
        conn: sqlite3.Connection,
        dimensions: int,
        *,
        table_name: str = VEC0_TABLE,
    ) -> bool:
        if not self._sqlite_vec_available:
            return False
        if table_name == VEC0_TABLE and self._vec0_dimension not in (None, dimensions):
            return False
        try:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING vec0(
                    entry_id TEXT PRIMARY KEY,
                    embedding float[{dimensions}] distance_metric=cosine,
                    model_id TEXT
                )
                """
            )
            if table_name == VEC0_TABLE:
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
            if self._vec0_has_entry(conn, str(entry_id), model_id):
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
