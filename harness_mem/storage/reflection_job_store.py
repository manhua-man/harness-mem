"""ReflectionJobStore — internal dream job ledger persistence.

The historical table/model names still say ``reflection`` for storage
compatibility, but the product path now uses this store only for dream job
dedupe, point reads, and runtime health.

Persistence layout (matches design.md > Data Models > SQLite Table):

* Index columns (``id, project_name, status, kind, phase, source,
  idempotency_key, created_at, updated_at, lease_owner, lease_until,
  attempt_count``) drive the WHERE clauses for active-job checks and list.
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
from harness_mem.storage.derived_index import DerivedIndex


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

class ReflectionJobStore:
    """SQLite-backed persistence for :class:`ReflectionJob`.

    Args:
        index: Initialized :class:`DerivedIndex` whose ``init_db`` has run.
            We do NOT call ``init_db`` ourselves — the backend / caller
            owns the lifecycle so this store stays composable with the
            other stores sharing the same connection.
    """

    def __init__(self, index: DerivedIndex) -> None:
        self._index = index

    # ---- save -------------------------------------------------------------

    def save(self, job: ReflectionJob) -> None:
        """Upsert a job (Req 2.3, 2.8).

        Sets ``job.updated_at`` to UTC now BEFORE serializing so the
        in-memory object and the persisted row agree. The actual write
        is a single ``INSERT ... ON CONFLICT(id) DO UPDATE`` so callers
        don't need to know whether the row already exists.
        """
        with self._index.locked_connection() as conn:
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
        SQLite write lock so dream auto ticks cannot both start a dream run.
        """
        with self._index.locked_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
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
                        conn.commit()
                        return active
                self._save_locked(conn, job)
            except Exception:
                conn.rollback()
                raise
        return None

    # ---- get --------------------------------------------------------------

    def get(self, job_id: str) -> ReflectionJob | None:
        """Return the job by id, or ``None`` (Req 2.4, 2.5)."""
        with self._index.locked_connection() as conn:
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

        with self._index.locked_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ReflectionJob.from_dict(json.loads(row["data"])) for row in rows]

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

__all__ = ["ReflectionJobStore"]
