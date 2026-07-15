"""Distill-job persistence inside the lossless transcript ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.session_distill import (
    DistillChunkCheckpoint,
    SessionDistillJob,
    SessionSemanticReview,
)
from harness_mem.core.schemas.transcript import TranscriptChunk, TranscriptSource
from harness_mem.transcript_chunking import sha256_text


class SessionDistillStore:
    """Transactional job/checkpoint operations sharing the transcript ledger."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: threading.RLock,
        *,
        get_source: Callable[[str], TranscriptSource | None],
        reconstruct: Callable[..., str],
    ) -> None:
        self._conn = connection
        self._lock = lock
        self._get_source = get_source
        self._reconstruct = reconstruct

    def enqueue(
        self,
        source_id: str,
        *,
        pipeline_version: str = "lossless-distill-v1",
    ) -> SessionDistillJob:
        """Idempotently queue every chunk from one complete current revision."""

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                source_row = self._conn.execute(
                    "SELECT data FROM transcript_sources WHERE id = ?",
                    (source_id,),
                ).fetchone()
                if source_row is None:
                    raise KeyError(source_id)
                source = TranscriptSource.from_dict(json.loads(source_row["data"]))
                if source.coverage != "complete" or source.status != "synced":
                    raise ValueError("only complete synced transcript sources can be queued")
                chunk_rows = self._conn.execute(
                    """
                    SELECT id, chunk_index FROM transcript_chunks
                    WHERE source_id = ? AND source_revision = ?
                    ORDER BY chunk_index
                    """,
                    (source.id, source.source_revision),
                ).fetchall()
                if len(chunk_rows) != source.chunk_count:
                    raise ValueError("transcript source chunk count is incomplete")

                idempotency_key = f"{source.id}:{source.source_revision}:{pipeline_version}"
                existing_row = self._conn.execute(
                    "SELECT data FROM distill_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    self._conn.rollback()
                    return SessionDistillJob.from_dict(json.loads(existing_row["data"]))

                self._mark_older_jobs_stale_locked(source)
                job = SessionDistillJob(
                    id=str(uuid5(NAMESPACE_URL, f"harness-mem://distill/{idempotency_key}")),
                    idempotency_key=idempotency_key,
                    project_name=source.project_name,
                    project_root=source.project_root,
                    client=source.client,
                    session_id=source.session_id,
                    source_id=source.id,
                    source_revision=source.source_revision,
                    pipeline_version=pipeline_version,
                    status="queued",
                    phase="chunks",
                    expected_chunk_count=len(chunk_rows),
                )
                self._upsert_job_locked(job)
                for row in chunk_rows:
                    self._upsert_checkpoint_locked(
                        DistillChunkCheckpoint(
                            job_id=job.id,
                            chunk_id=str(row["id"]),
                            chunk_index=int(row["chunk_index"]),
                        )
                    )
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def get(self, job_id: str) -> SessionDistillJob | None:
        with self._lock:
            return self._get_job_locked(job_id)

    def list(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SessionDistillJob]:
        where: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            where.append("project_name = ?")
            params.append(project_name)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT data FROM distill_jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(1, limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [SessionDistillJob.from_dict(json.loads(row["data"])) for row in rows]

    def list_checkpoints(self, job_id: str) -> list[DistillChunkCheckpoint]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM distill_job_chunks
                WHERE job_id = ? ORDER BY chunk_index ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            DistillChunkCheckpoint.from_dict(json.loads(row["data"]))
            for row in rows
        ]

    def claim_chunks(
        self,
        job_id: str,
        *,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 300,
    ) -> list[tuple[TranscriptChunk, DistillChunkCheckpoint]]:
        """Atomically claim pending chunks and reclaim expired leases."""

        if not lease_owner.strip():
            raise ValueError("lease_owner is required")
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        claimed: list[tuple[TranscriptChunk, DistillChunkCheckpoint]] = []
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job.status in {"completed", "failed", "stale"}:
                    self._conn.rollback()
                    return []
                rows = self._conn.execute(
                    """
                    SELECT data FROM distill_job_chunks
                    WHERE job_id = ? ORDER BY chunk_index ASC
                    """,
                    (job_id,),
                ).fetchall()
                checkpoints = [
                    DistillChunkCheckpoint.from_dict(json.loads(row["data"]))
                    for row in rows
                ]
                eligible = []
                for checkpoint in checkpoints:
                    expired = bool(
                        checkpoint.status == "processing"
                        and checkpoint.lease_until is not None
                        and checkpoint.lease_until <= now
                    )
                    if checkpoint.status in {"pending", "retryable"} or expired:
                        eligible.append(checkpoint)
                for checkpoint in eligible[: max(1, limit)]:
                    checkpoint.status = "processing"
                    checkpoint.attempt_count += 1
                    checkpoint.lease_owner = lease_owner
                    checkpoint.lease_until = lease_until
                    checkpoint.error = None
                    checkpoint.updated_at = now
                    self._upsert_checkpoint_locked(checkpoint)
                    chunk = self._get_chunk_locked(checkpoint.chunk_id)
                    if chunk is None:
                        raise ValueError(
                            f"distill input chunk is missing: {checkpoint.chunk_id}"
                        )
                    claimed.append((chunk, checkpoint))
                if claimed:
                    job.status = "processing"
                    job.phase = "chunks"
                    job.attempt_count += 1
                    job.updated_at = now
                    self._upsert_job_locked(job)
                self._conn.commit()
                return claimed
            except Exception:
                self._conn.rollback()
                raise

    def checkpoint_chunk(
        self,
        job_id: str,
        chunk_id: str,
        *,
        lease_owner: str,
        result: dict,
    ) -> SessionDistillJob:
        """Persist one Agent result only when the caller owns the active lease."""

        now = datetime.now(timezone.utc)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                row = self._conn.execute(
                    """
                    SELECT data FROM distill_job_chunks
                    WHERE job_id = ? AND chunk_id = ?
                    """,
                    (job_id, chunk_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"{job_id}:{chunk_id}")
                checkpoint = DistillChunkCheckpoint.from_dict(json.loads(row["data"]))
                if checkpoint.status == "completed":
                    self._conn.rollback()
                    return job
                if (
                    checkpoint.status != "processing"
                    or checkpoint.lease_owner != lease_owner
                ):
                    raise PermissionError("distill chunk lease is not owned by this caller")
                if checkpoint.lease_until is None or checkpoint.lease_until < now:
                    raise TimeoutError("distill chunk lease has expired")
                checkpoint.status = "completed"
                checkpoint.result = dict(result)
                checkpoint.error = None
                checkpoint.lease_owner = None
                checkpoint.lease_until = None
                checkpoint.completed_at = now
                checkpoint.updated_at = now
                self._upsert_checkpoint_locked(checkpoint)
                completed_count = int(
                    self._conn.execute(
                        """
                        SELECT COUNT(*) FROM distill_job_chunks
                        WHERE job_id = ? AND status = 'completed'
                        """,
                        (job_id,),
                    ).fetchone()[0]
                )
                job.completed_chunk_count = completed_count
                job.updated_at = now
                if completed_count == job.expected_chunk_count:
                    job.status = "reviewing"
                    job.phase = "review"
                self._upsert_job_locked(job)
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def finalize(
        self,
        job_id: str,
        *,
        semantic_review: dict,
        output_candidate_ids: list[str] | None = None,
    ) -> SessionDistillJob:
        """Complete one explicit job after structural and semantic review."""

        review = SessionSemanticReview(**semantic_review)
        now = datetime.now(timezone.utc)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                source = self._get_source(job.source_id)
                if source is None:
                    raise ValueError("distill source no longer exists")
                if source.source_revision != job.source_revision:
                    job.status = "stale"
                    job.error = "source revision changed before finalization"
                    job.updated_at = now
                    self._upsert_job_locked(job)
                    self._conn.commit()
                    return job
                checkpoints = self.list_checkpoints(job_id)
                complete_count = sum(
                    checkpoint.status == "completed" for checkpoint in checkpoints
                )
                if complete_count != job.expected_chunk_count:
                    raise ValueError("not all distill chunks are complete")
                reconstructed = self._reconstruct(
                    job.source_id,
                    source_revision=job.source_revision,
                )
                job.structural_audit = {
                    "coverage": "complete",
                    "expected_chunks": job.expected_chunk_count,
                    "completed_chunks": complete_count,
                    "normalized_sha256": sha256_text(reconstructed),
                    "source_revision_current": True,
                }
                job.semantic_review = review.to_dict()
                job.output_candidate_ids = list(dict.fromkeys(output_candidate_ids or []))
                job.completed_chunk_count = complete_count
                job.status = "completed"
                job.phase = "done"
                job.error = None
                job.completed_at = now
                job.updated_at = now
                self._upsert_job_locked(job)
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def _upsert_job_locked(self, job: SessionDistillJob) -> None:
        self._conn.execute(
            """
            INSERT INTO distill_jobs (
                id, idempotency_key, project_name, source_id, source_revision,
                status, phase, created_at, updated_at, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                phase=excluded.phase,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                job.id,
                job.idempotency_key,
                job.project_name,
                job.source_id,
                job.source_revision,
                job.status,
                job.phase,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
                json.dumps(job.to_dict(), ensure_ascii=False),
            ),
        )

    def _upsert_checkpoint_locked(self, checkpoint: DistillChunkCheckpoint) -> None:
        self._conn.execute(
            """
            INSERT INTO distill_job_chunks (
                job_id, chunk_id, chunk_index, status, lease_owner,
                lease_until, updated_at, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, chunk_id) DO UPDATE SET
                status=excluded.status,
                lease_owner=excluded.lease_owner,
                lease_until=excluded.lease_until,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                checkpoint.job_id,
                checkpoint.chunk_id,
                checkpoint.chunk_index,
                checkpoint.status,
                checkpoint.lease_owner,
                checkpoint.lease_until.isoformat() if checkpoint.lease_until else None,
                checkpoint.updated_at.isoformat(),
                json.dumps(checkpoint.to_dict(), ensure_ascii=False),
            ),
        )

    def _get_job_locked(self, job_id: str) -> SessionDistillJob | None:
        row = self._conn.execute(
            "SELECT data FROM distill_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return SessionDistillJob.from_dict(json.loads(row["data"]))

    def _get_chunk_locked(self, chunk_id: str) -> TranscriptChunk | None:
        row = self._conn.execute(
            "SELECT data FROM transcript_chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            return None
        return TranscriptChunk.from_dict(json.loads(row["data"]))

    def _mark_older_jobs_stale_locked(self, source: TranscriptSource) -> None:
        rows = self._conn.execute(
            """
            SELECT data FROM distill_jobs
            WHERE source_id = ? AND source_revision != ?
              AND status IN ('queued', 'processing', 'reviewing', 'retryable')
            """,
            (source.id, source.source_revision),
        ).fetchall()
        now = datetime.now(timezone.utc)
        for row in rows:
            job = SessionDistillJob.from_dict(json.loads(row["data"]))
            job.status = "stale"
            job.error = "superseded by a newer transcript source revision"
            job.updated_at = now
            self._upsert_job_locked(job)


__all__ = ["SessionDistillStore"]
