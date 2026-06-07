"""ReflectionJobStore — persistence layer for ``ReflectionJob`` records.

Thin wrapper over :class:`SQLiteIndex` exposing the operations
:func:`reflection_once` needs: upsert, point read, filtered list,
compare-and-set lease updates, and idempotency-key lookup.

Persistence layout (matches design.md > Data Models > SQLite Table):

* Index columns (``id, project_name, status, kind, phase, source,
  idempotency_key, created_at, updated_at, lease_owner, lease_until,
  attempt_count``) drive the WHERE clauses for compare-and-set and list.
* The ``data`` column carries the full ``ReflectionJob.to_dict()`` blob
  so unknown / forward-compatible fields round-trip without us listing
  them as columns.

The store does NOT introduce its own table — the schema is registered
in :mod:`harness_mem.storage.sqlite_index._TABLE_SCHEMAS` and created by
:meth:`SQLiteIndex.init_db`. That keeps coexistence with verbatim,
structured, and project-profile stores trivially safe (Req 2.7 / 10.4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.storage.sqlite_index import SQLiteIndex


# Columns we mirror onto the table from inside the JSON blob. Anything
# NOT in this set goes into the ``data`` blob only and can't be filtered
# on at the SQL level — that's intentional, the schema is forward-compat.
_INDEX_COLUMNS: tuple[str, ...] = (
    "id",
    "project_name",
    "status",
    "kind",
    "phase",
    "source",
    "idempotency_key",
    "data",
    "created_at",
    "updated_at",
    "lease_owner",
    "lease_until",
    "attempt_count",
)

_TERMINAL_STATUSES: tuple[str, ...] = ("completed", "failed")


class ReflectionJobStore:
    """SQLite-backed persistence for :class:`ReflectionJob`.

    Args:
        index: Initialized :class:`SQLiteIndex` whose ``init_db`` has run.
            We do NOT call ``init_db`` ourselves — the backend / caller
            owns the lifecycle so this store stays composable with the
            other stores sharing the same connection.
    """

    def __init__(self, index: SQLiteIndex) -> None:
        self._index = index

    # ---- save -------------------------------------------------------------

    def save(self, job: ReflectionJob) -> None:
        """Upsert a job (Req 2.3, 2.8).

        Sets ``job.updated_at`` to UTC now BEFORE serializing so the
        in-memory object and the persisted row agree. The actual write
        is a single ``INSERT ... ON CONFLICT(id) DO UPDATE`` so callers
        don't need to know whether the row already exists.
        """
        conn = self._index._conn_write()
        with self._index._lock:
            self._save_locked(conn, job)

    def save_if_no_active_processing(
        self,
        job: ReflectionJob,
        *,
        stale_before: datetime,
    ) -> ReflectionJob | None:
        """Save ``job`` only when no fresh processing job exists.

        Returns the active job that blocked insertion, or ``None`` when the
        supplied job was saved. The check and insert happen under the same
        SQLite write lock so scheduler ticks cannot both start a dream run.
        """
        conn = self._index._conn_write()
        with self._index._lock:
            rows = conn.execute(
                """
                SELECT data FROM reflection_jobs
                WHERE project_name = ? AND kind = ? AND status = 'processing'
                ORDER BY updated_at DESC
                """,
                (job.project_name, job.kind),
            ).fetchall()
            for row in rows:
                active = ReflectionJob.from_dict(json.loads(row["data"]))
                updated_at = active.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if updated_at >= stale_before:
                    return active
            self._save_locked(conn, job)
        return None

    # ---- get --------------------------------------------------------------

    def get(self, job_id: str) -> ReflectionJob | None:
        """Return the job by id, or ``None`` (Req 2.4, 2.5)."""
        conn = self._index._conn_write()
        with self._index._lock:
            row = conn.execute(
                "SELECT data FROM reflection_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return ReflectionJob.from_dict(json.loads(row["data"]))

    # ---- list -------------------------------------------------------------

    def list(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[ReflectionJob]:
        """List jobs newest-first, filtered by the supplied keys (Req 2.6).

        ``None`` filters are skipped — the WHERE clause only mentions
        the dimensions the caller actually constrained.
        """
        where: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            where.append("project_name = ?")
            params.append(project_name)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if kind is not None:
            where.append("kind = ?")
            params.append(kind)

        sql = "SELECT data FROM reflection_jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        conn = self._index._conn_write()
        with self._index._lock:
            rows = conn.execute(sql, params).fetchall()
        return [ReflectionJob.from_dict(json.loads(row["data"])) for row in rows]

    # ---- compare_and_set --------------------------------------------------

    def compare_and_set(
        self,
        job_id: str,
        expected_status: str,
        expected_lease_owner: str | None,
        updates: dict[str, Any],
    ) -> bool:
        """Conditional update used for lease acquisition (Req 4.6).

        Atomic, in the SQLite sense: we hold ``self._index._lock`` from
        the SELECT through the COMMIT, and SQLite serializes writers, so
        no other caller can slip in between the read of ``data`` and the
        UPDATE that writes the merged blob back.

        ``updates`` is a flat mapping of column-name → new-value. Each
        key that maps to an index column is written to that column;
        every key is also merged into the ``data`` JSON so the blob
        stays in sync (it's the source of truth on read).

        Returns ``True`` iff exactly one row matched the WHERE clause
        and was updated. Never raises — a missed CAS is a normal
        outcome (another worker won) per Req 4.7.
        """
        if not updates:
            # No-op CAS would still need to bump updated_at for callers
            # that just want to refresh the timestamp, but a strict
            # "no updates" means there's nothing to write — return False
            # rather than silently match. Practically callers always
            # pass at least one field.
            return False

        now_iso = datetime.now(timezone.utc).isoformat()

        # --- build SET clause -------------------------------------------------
        # We always touch ``updated_at`` and ``data``; everything else
        # comes from ``updates``. Unknown keys (not in _INDEX_COLUMNS)
        # are still merged into the JSON blob so callers can stash
        # forward-compat fields without us listing them here.
        column_assignments: list[str] = ["updated_at = ?", "data = ?"]

        index_columns_to_update: list[str] = []
        for key in updates:
            if key in _INDEX_COLUMNS and key not in ("id", "data", "updated_at"):
                index_columns_to_update.append(key)
                column_assignments.append(f"{key} = ?")

        # WHERE clause: id + status + lease_owner. We use a single
        # ``lease_owner IS ?`` predicate by emitting either ``IS NULL``
        # or ``= ?`` so the same UPDATE works for both branches without
        # SQLite parameter-binding NULL ambiguity.
        where = ["id = ?", "status = ?"]
        where_params: list[Any] = [job_id, expected_status]
        if expected_lease_owner is None:
            where.append("lease_owner IS NULL")
        else:
            where.append("lease_owner = ?")
            where_params.append(expected_lease_owner)

        conn = self._index._conn_write()
        with self._index._lock:
            row = conn.execute(
                "SELECT data FROM reflection_jobs WHERE "
                + " AND ".join(where),
                where_params,
            ).fetchone()
            if row is None:
                # CAS failed — either job doesn't exist, status mismatch,
                # or lease_owner mismatch. No mutation, no exception.
                return False

            blob = json.loads(row["data"])
            for key, value in updates.items():
                blob[key] = self._json_safe(value)
            blob["updated_at"] = now_iso

            # Now bind parameters in the same order as ``column_assignments``.
            # updated_at, data, then each index-column update in declared order.
            params: list[Any] = [now_iso, json.dumps(blob)]
            for key in index_columns_to_update:
                params.append(self._scalar_for_column(updates[key]))
            params.extend(where_params)

            cursor = conn.execute(
                "UPDATE reflection_jobs SET "
                + ", ".join(column_assignments)
                + " WHERE "
                + " AND ".join(where),
                params,
            )
            conn.commit()
            return cursor.rowcount == 1

    # ---- find_by_idempotency_key -----------------------------------------

    def find_by_idempotency_key(self, key: str) -> ReflectionJob | None:
        """Return the latest non-terminal job for ``key``, or ``None``.

        Terminal statuses (``completed`` / ``failed``) are filtered out
        so :func:`reflection_once` treats a finished prior run as
        "no live job" — callers who want to retry after completion
        should mint a new ``trigger_id`` (Req 5.3).
        """
        placeholders = ",".join("?" for _ in _TERMINAL_STATUSES)
        sql = (
            "SELECT data FROM reflection_jobs "
            f"WHERE idempotency_key = ? AND status NOT IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT 1"
        )
        params = [key, *_TERMINAL_STATUSES]
        conn = self._index._conn_write()
        with self._index._lock:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return ReflectionJob.from_dict(json.loads(row["data"]))

    def find_terminal_by_idempotency_key(self, key: str) -> ReflectionJob | None:
        """Return the latest terminal (``completed`` / ``failed``) job for ``key``.

        Companion to :meth:`find_by_idempotency_key`; together they cover
        the full row-set with the same idempotency key. Used by
        :func:`reflection_once` to disambiguate "same trigger replayed"
        from "new trigger reusing parameters" per Req 5.3.
        """
        placeholders = ",".join("?" for _ in _TERMINAL_STATUSES)
        sql = (
            "SELECT data FROM reflection_jobs "
            f"WHERE idempotency_key = ? AND status IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT 1"
        )
        params = [key, *_TERMINAL_STATUSES]
        conn = self._index._conn_write()
        with self._index._lock:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return ReflectionJob.from_dict(json.loads(row["data"]))

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _row_from_job(job: ReflectionJob) -> dict[str, Any]:
        """Project a :class:`ReflectionJob` onto its index columns.

        The ``idempotency_key`` is sourced from ``model_extra`` because
        the schema's ``extra="allow"`` policy lets callers stuff it on
        the model without us pulling it onto the typed surface.
        """
        extra = job.model_extra or {}
        idempotency_key = extra.get("idempotency_key")
        return {
            "id": job.id,
            "project_name": job.project_name,
            "status": job.status,
            "kind": job.kind,
            "phase": job.phase,
            "source": job.source,
            "idempotency_key": idempotency_key,
            "data": json.dumps(job.to_dict()),
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "lease_owner": job.lease_owner,
            "lease_until": job.lease_until.isoformat() if job.lease_until else None,
            "attempt_count": job.attempt_count,
        }

    def _save_locked(self, conn: Any, job: ReflectionJob) -> None:
        job.updated_at = datetime.now(timezone.utc)
        row = self._row_from_job(job)
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        update_assignments = ",".join(
            f"{col}=excluded.{col}" for col in cols if col != "id"
        )
        sql = (
            f"INSERT INTO reflection_jobs ({','.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {update_assignments}"
        )
        conn.execute(sql, [row[c] for c in cols])
        conn.commit()

    @staticmethod
    def _scalar_for_column(value: Any) -> Any:
        """Coerce a Python value to something SQLite will accept on UPDATE."""
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Coerce a value to JSON-serialisable form for the ``data`` blob."""
        if isinstance(value, datetime):
            return value.isoformat()
        return value


__all__ = ["ReflectionJobStore"]
