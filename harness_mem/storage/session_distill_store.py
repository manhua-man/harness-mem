"""Distill-job persistence inside the lossless transcript ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Literal, Set
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.session_distill import (
    CompletionDisposition,
    DistillChunkCheckpoint,
    DistillJobStatus,
    SessionDistillJob,
    SessionSemanticReview,
    SourceCleanupStatus,
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
        active_limit: int | None = None,
        recent_first: bool = True,
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
                    raise ValueError(
                        "only complete synced transcript sources can be queued"
                    )
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

                idempotency_key = (
                    f"{source.id}:{source.source_revision}:{pipeline_version}"
                )
                existing_row = self._conn.execute(
                    "SELECT data FROM distill_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_row is not None:
                    existing = SessionDistillJob.from_dict(
                        json.loads(existing_row["data"])
                    )
                    self._mark_older_jobs_stale_locked(source)
                    if active_limit is not None:
                        self._rebalance_locked(
                            source.project_name,
                            target_active=max(0, active_limit),
                            recent_first=recent_first,
                        )
                    refreshed = self._get_job_locked(existing.id) or existing
                    self._conn.commit()
                    return refreshed

                self._mark_older_jobs_stale_locked(source)
                job = SessionDistillJob(
                    id=str(
                        uuid5(NAMESPACE_URL, f"harness-mem://distill/{idempotency_key}")
                    ),
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
                    zero_candidate_challenge_version="v1",
                    last_progress_at=datetime.now(timezone.utc),
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
                if active_limit is not None:
                    self._rebalance_locked(
                        source.project_name,
                        target_active=max(0, active_limit),
                        recent_first=recent_first,
                    )
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def get(self, job_id: str) -> SessionDistillJob | None:
        with self._lock:
            return self._get_job_locked(job_id)

    def enable_zero_candidate_challenge(
        self,
        job_id: str,
    ) -> SessionDistillJob:
        """Upgrade an active legacy job once semantic v1 evidence is available."""

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if (
                    job.status != "completed"
                    and job.zero_candidate_challenge_version is None
                ):
                    job.zero_candidate_challenge_version = "v1"
                    job.updated_at = datetime.now(timezone.utc)
                    self._upsert_job_locked(job)
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

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

    def list_checkpoints(self, job_id: str) -> List[DistillChunkCheckpoint]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM distill_job_chunks
                WHERE job_id = ? ORDER BY chunk_index ASC
                """,
                (job_id,),
            ).fetchall()
        return [
            DistillChunkCheckpoint.from_dict(json.loads(row["data"])) for row in rows
        ]

    def reconcile(
        self,
        *,
        project_name: str | None = None,
        now: datetime | None = None,
        recovery_budget: int | None = None,
    ) -> dict[str, int]:
        """Reconcile job state from durable checkpoints after a restart.

        Chunk lease reclamation alone can leave a parent job looking active
        forever. This pass is intentionally synchronous and bounded: it only
        repairs durable state, never performs semantic work or claims a new
        Agent lease. Repeated recovery events exhaust a per-job budget and
        become an explicit terminal failure.
        """

        current = now or datetime.now(timezone.utc)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                clauses: list[str] = []
                params: list[Any] = []
                if project_name is not None:
                    clauses.append("project_name = ?")
                    params.append(project_name)
                sql = "SELECT data FROM distill_jobs"
                if clauses:
                    sql += " WHERE " + " AND ".join(clauses)
                rows = self._conn.execute(sql, params).fetchall()
                summary = {
                    "inspected": 0,
                    "recovered": 0,
                    "advanced_to_review": 0,
                    "failed_recovery_budget": 0,
                }
                terminal = {"completed", "failed", "stale"}
                for row in rows:
                    job = SessionDistillJob.from_dict(json.loads(row["data"]))
                    summary["inspected"] += 1
                    if job.status in terminal:
                        continue
                    checkpoint_rows = self._conn.execute(
                        """
                        SELECT data FROM distill_job_chunks
                        WHERE job_id = ? ORDER BY chunk_index ASC
                        """,
                        (job.id,),
                    ).fetchall()
                    checkpoints = [
                        DistillChunkCheckpoint.from_dict(json.loads(item["data"]))
                        for item in checkpoint_rows
                    ]
                    completed_count = sum(
                        checkpoint.status == "completed" for checkpoint in checkpoints
                    )
                    expired = [
                        checkpoint
                        for checkpoint in checkpoints
                        if checkpoint.status == "processing"
                        and checkpoint.lease_until is not None
                        and checkpoint.lease_until <= current
                    ]
                    changed = False
                    if expired:
                        self._recover_expired_checkpoints_locked(
                            job,
                            checkpoints,
                            now=current,
                            recovery_budget=recovery_budget,
                        )
                        changed = True
                        summary["recovered"] += len(expired)
                        if job.status == "failed":
                            summary["failed_recovery_budget"] += 1

                    if job.status not in terminal:
                        if (
                            completed_count == job.expected_chunk_count
                            and job.expected_chunk_count > 0
                        ):
                            if job.status != "reviewing":
                                job.status = "reviewing"
                                job.phase = "review"
                                summary["advanced_to_review"] += 1
                            job.completed_chunk_count = completed_count
                            job.last_progress_at = current
                            job.updated_at = current
                            job.retry_after = None
                            changed = True
                        elif job.status == "processing":
                            active = [
                                checkpoint
                                for checkpoint in checkpoints
                                if checkpoint.status == "processing"
                                and checkpoint.lease_until is not None
                                and checkpoint.lease_until > current
                            ]
                            pending = [
                                checkpoint
                                for checkpoint in checkpoints
                                if checkpoint.status in {"pending", "retryable"}
                            ]
                            if not active and pending and not expired:
                                job.recovery_count += 1
                                if recovery_budget is not None:
                                    job.recovery_budget = max(1, int(recovery_budget))
                                job.recovery_reason_codes = list(
                                    dict.fromkeys(
                                        [
                                            *job.recovery_reason_codes,
                                            "processing_without_active_lease",
                                        ]
                                    )
                                )
                                job.last_recovery_at = current
                                job.last_progress_at = current
                                job.updated_at = current
                                changed = True
                                summary["recovered"] += 1
                                if job.recovery_count >= max(
                                    1, int(job.recovery_budget)
                                ):
                                    job.status = "failed"
                                    job.error = "distill recovery budget exhausted"
                                    job.recovery_exhausted_at = current
                                    for checkpoint in checkpoints:
                                        if checkpoint.status == "completed":
                                            continue
                                        checkpoint.status = "failed"
                                        checkpoint.lease_owner = None
                                        checkpoint.lease_until = None
                                        checkpoint.error = "recovery budget exhausted"
                                        checkpoint.updated_at = current
                                        self._upsert_checkpoint_locked(checkpoint)
                                    summary["failed_recovery_budget"] += 1
                                else:
                                    job.status = "retryable"
                                    job.retry_after = current + timedelta(
                                        seconds=min(
                                            6 * 3600,
                                            300 * (2 ** min(job.recovery_count - 1, 7)),
                                        )
                                    )
                    if changed:
                        self._upsert_job_locked(job)
                self._conn.commit()
                return summary
            except Exception:
                self._conn.rollback()
                raise

    def rebalance(
        self,
        project_name: str,
        *,
        target_active: int = 2,
        recent_first: bool = True,
    ) -> dict[str, int]:
        """Keep a bounded active lane and park excess cold evidence jobs."""

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                result = self._rebalance_locked(
                    project_name,
                    target_active=max(0, target_active),
                    recent_first=recent_first,
                )
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

    def mark_agent_offered(
        self,
        project_name: str,
        job_ids: List[str],
        *,
        offered_at: datetime | None = None,
    ) -> int:
        """Record unique daily Agent offers for budget and throughput reporting."""

        selected: Set[str] = set(job_ids)
        if not selected:
            return 0
        now = offered_at or datetime.now(timezone.utc)
        day = now.date().isoformat()
        newly_offered = 0
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute(
                    "SELECT data FROM distill_jobs WHERE project_name = ?",
                    (project_name,),
                ).fetchall()
                for row in rows:
                    job = SessionDistillJob.from_dict(json.loads(row["data"]))
                    if job.id not in selected:
                        continue
                    if job.agent_offer_day != day:
                        job.agent_offer_day = day
                        job.agent_offer_count = 0
                        newly_offered += 1
                    job.agent_offer_count += 1
                    job.last_agent_offered_at = now
                    job.updated_at = now
                    self._upsert_job_locked(job)
                self._conn.commit()
                return newly_offered
            except Exception:
                self._conn.rollback()
                raise

    def claim_chunks(
        self,
        job_id: str,
        *,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 300,
    ) -> List[tuple[TranscriptChunk, DistillChunkCheckpoint]]:
        """Atomically claim pending chunks and reclaim expired leases."""

        if not lease_owner.strip():
            raise ValueError("lease_owner is required")
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=max(1, lease_seconds))
        claimed: List[tuple[TranscriptChunk, DistillChunkCheckpoint]] = []
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job.status in {"completed", "failed", "stale", "parked"}:
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
                if self._recover_expired_checkpoints_locked(
                    job,
                    checkpoints,
                    now=now,
                ):
                    self._conn.commit()
                    return []
                if job.retry_after is not None and job.retry_after > now:
                    self._conn.rollback()
                    return []
                eligible = []
                for checkpoint in checkpoints:
                    if checkpoint.status in {"pending", "retryable"}:
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
                    job.retry_after = None
                    job.last_progress_at = now
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
                    raise PermissionError(
                        "distill chunk lease is not owned by this caller"
                    )
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
                job.last_progress_at = now
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
        output_candidate_ids: List[str] | None = None,
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
                if job.status == "completed":
                    # Finalize is an idempotent MCP boundary. Processed-source
                    # cleanup deliberately removes checkpoints and raw chunks,
                    # so a transport retry must return the durable completion
                    # receipt instead of trying to reconstruct deleted input.
                    self._conn.rollback()
                    return job
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
                job.output_candidate_ids = list(
                    dict.fromkeys(output_candidate_ids or [])
                )
                job.completed_chunk_count = complete_count
                job.status = "completed"
                job.phase = "done"
                job.error = None
                job.completed_at = now
                job.last_progress_at = now
                job.updated_at = now
                self._upsert_job_locked(job)
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def defer(self, job_id: str, *, error: str) -> SessionDistillJob:
        """Release active leases and move one failed job behind healthy work."""

        now = datetime.now(timezone.utc)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job.status in {"completed", "stale", "failed"}:
                    self._conn.rollback()
                    return job
                rows = self._conn.execute(
                    "SELECT data FROM distill_job_chunks WHERE job_id = ?",
                    (job_id,),
                ).fetchall()
                for row in rows:
                    checkpoint = DistillChunkCheckpoint.from_dict(
                        json.loads(row["data"])
                    )
                    if checkpoint.status == "processing":
                        checkpoint.status = "retryable"
                        checkpoint.lease_owner = None
                        checkpoint.lease_until = None
                        checkpoint.error = error[:512]
                        checkpoint.updated_at = now
                        self._upsert_checkpoint_locked(checkpoint)
                job.status = "retryable"
                job.error = error[:512]
                retry_number = max(1, job.attempt_count)
                backoff_seconds = min(6 * 3600, 300 * (2 ** min(retry_number - 1, 7)))
                job.retry_after = now + timedelta(seconds=backoff_seconds)
                job.last_progress_at = now
                job.updated_at = now
                self._upsert_job_locked(job)
                self._conn.commit()
                return job
            except Exception:
                self._conn.rollback()
                raise

    def record_completion_outcome(
        self,
        job_id: str,
        *,
        disposition: CompletionDisposition | None,
        reason_codes: List[str],
        promotion_summary: dict[str, Any],
        source_cleanup_status: SourceCleanupStatus,
        source_cleanup_receipt_id: str | None = None,
    ) -> SessionDistillJob:
        """Persist post-distill truth and cleanup outcomes on the existing job."""

        now = datetime.now(timezone.utc)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job.status != "completed":
                    raise ValueError(
                        "completion outcome requires a completed distill job"
                    )
                job.completion_disposition = disposition
                job.completion_reason_codes = list(dict.fromkeys(reason_codes))
                job.promotion_summary = dict(promotion_summary)
                job.source_cleanup_status = source_cleanup_status
                job.source_cleanup_receipt_id = source_cleanup_receipt_id
                job.last_progress_at = now
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

    def _recover_expired_checkpoints_locked(
        self,
        job: SessionDistillJob,
        checkpoints: List[DistillChunkCheckpoint],
        *,
        now: datetime,
        recovery_budget: int | None = None,
    ) -> bool:
        expired = [
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.status == "processing"
            and checkpoint.lease_until is not None
            and checkpoint.lease_until <= now
        ]
        if not expired:
            return False

        for checkpoint in expired:
            checkpoint.status = "retryable"
            checkpoint.lease_owner = None
            checkpoint.lease_until = None
            checkpoint.error = "chunk lease expired during recovery"
            checkpoint.updated_at = now
            self._upsert_checkpoint_locked(checkpoint)

        job.recovery_count += 1
        if recovery_budget is not None:
            job.recovery_budget = max(1, int(recovery_budget))
        job.recovery_reason_codes = list(
            dict.fromkeys([*job.recovery_reason_codes, "expired_chunk_lease"])
        )
        job.last_recovery_at = now
        job.last_progress_at = now
        job.updated_at = now

        if job.recovery_count >= max(1, int(job.recovery_budget)):
            job.status = "failed"
            job.error = "distill recovery budget exhausted"
            job.retry_after = None
            job.recovery_exhausted_at = now
            for checkpoint in checkpoints:
                if checkpoint.status == "completed":
                    continue
                checkpoint.status = "failed"
                checkpoint.lease_owner = None
                checkpoint.lease_until = None
                checkpoint.error = "recovery budget exhausted"
                checkpoint.updated_at = now
                self._upsert_checkpoint_locked(checkpoint)
        else:
            job.status = "retryable"
            job.retry_after = now + timedelta(
                seconds=min(
                    6 * 3600,
                    300 * (2 ** min(job.recovery_count - 1, 7)),
                )
            )
        self._upsert_job_locked(job)
        return True

    def _mark_older_jobs_stale_locked(self, source: TranscriptSource) -> None:
        rows = self._conn.execute(
            """
            SELECT data FROM distill_jobs
            WHERE source_id = ? AND source_revision != ?
              AND status IN ('queued', 'processing', 'reviewing', 'retryable', 'parked')
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

    def _rebalance_locked(
        self,
        project_name: str,
        *,
        target_active: int,
        recent_first: bool,
    ) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT rowid AS queue_ordinal, data FROM distill_jobs
            WHERE project_name = ?
            """,
            (project_name,),
        ).fetchall()
        jobs = [SessionDistillJob.from_dict(json.loads(row["data"])) for row in rows]
        queue_ordinal = {
            job.id: int(row["queue_ordinal"])
            for job, row in zip(jobs, rows, strict=True)
        }
        now = datetime.now(timezone.utc)
        protected = [job for job in jobs if job.status in {"processing", "reviewing"}]
        candidates = [
            job
            for job in jobs
            if job.status in {"queued", "retryable", "parked"}
            and (job.retry_after is None or job.retry_after <= now)
        ]
        waiting_retry = [
            job
            for job in jobs
            if job.status in {"queued", "retryable", "parked"}
            and job.retry_after is not None
            and job.retry_after > now
        ]
        available_slots = max(0, target_active - len(protected))
        currently_active = [job for job in candidates if job.status == "queued"]
        selected: List[SessionDistillJob] = []
        if len(currently_active) <= available_slots:
            selected.extend(currently_active)
        pool = [
            job for job in candidates if job.id not in {item.id for item in selected}
        ]

        history = sorted(
            (job for job in jobs if job.drainer_selected_at is not None),
            key=lambda job: (
                job.drainer_selected_at or datetime.min.replace(tzinfo=timezone.utc)
            ),
        )
        recent_streak = 0
        for historical in reversed(history):
            if historical.drainer_lane != "recent":
                break
            recent_streak += 1

        selected_recent = 0
        selected_oldest = 0

        def age_key(job: SessionDistillJob) -> tuple[datetime, int]:
            return job.created_at, queue_ordinal[job.id]

        while len(selected) < available_slots and pool:
            healthy = [job for job in pool if job.error is None]
            lane_pool = healthy or pool
            choose_recent = recent_first and recent_streak < 3
            chosen = (
                max(lane_pool, key=age_key)
                if choose_recent
                else min(
                    lane_pool,
                    key=age_key,
                )
            )
            lane: Literal["recent", "oldest"] = "recent" if choose_recent else "oldest"
            chosen.drainer_lane = lane
            chosen.drainer_selected_at = now
            if lane == "recent":
                recent_streak += 1
                selected_recent += 1
            else:
                recent_streak = 0
                selected_oldest += 1
            selected.append(chosen)
            pool = [job for job in pool if job.id != chosen.id]

        selected_ids = {job.id for job in selected}
        for job in candidates:
            desired: DistillJobStatus = "queued" if job.id in selected_ids else "parked"
            if job.status == desired:
                if job.id in selected_ids and job.drainer_selected_at == now:
                    self._upsert_job_locked(job)
                continue
            job.status = desired
            job.updated_at = now
            self._upsert_job_locked(job)
        return {
            "active": len(protected) + len(selected_ids),
            "parked": len(pool),
            "retry_backoff": len(waiting_retry),
            "selected_recent": selected_recent,
            "selected_oldest": selected_oldest,
        }


__all__ = ["SessionDistillStore"]
