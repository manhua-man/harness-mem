"""Durable local ledger for lossless transcript sources and chunks."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas.session_distill import (
    DistillChunkCheckpoint,
    SessionDistillJob,
)
from harness_mem.core.schemas.transcript import (
    TranscriptChunk,
    TranscriptScanFrontier,
    TranscriptSource,
    TranscriptSourceRevision,
)
from harness_mem.transcript_chunking import (
    reconstruct_transcript,
    sha256_bytes,
    sha256_text,
)
from harness_mem.storage.session_distill_store import SessionDistillStore

TRANSCRIPT_LEDGER_SCHEMA_VERSION = 6


class TranscriptStore:
    """SQLite-backed source-revision ledger independent of derived search data."""

    def __init__(self, data_dir: Path) -> None:
        self.db_path = Path(data_dir) / "transcript_ledger.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=10,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._distill = SessionDistillStore(
            self._conn,
            self._lock,
            get_source=self.get_source,
            reconstruct=self.reconstruct,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def flush_sensitive_deletes(self) -> None:
        """Commit secure deletes and truncate the transcript-ledger WAL."""

        with self._lock:
            self._conn.commit()
            row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row is not None and int(row[0] or 0) != 0:
                raise RuntimeError("transcript ledger WAL checkpoint remained busy")

    def save_source(self, source: TranscriptSource) -> None:
        """Upsert the logical source and its current-revision pointer."""

        source.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._upsert_source_locked(source)
            self._conn.commit()

    def save_snapshot(
        self,
        source: TranscriptSource,
        chunks: list[TranscriptChunk],
        *,
        raw_bytes: bytes | None = None,
    ) -> None:
        """Atomically persist one complete immutable revision and its chunks."""

        native_bytes = raw_bytes if raw_bytes is not None else (
            "".join(chunk.raw_content for chunk in chunks).encode("utf-8")
        )
        normalized_text = self._validate_snapshot(source, chunks, native_bytes)
        now = datetime.now(timezone.utc)
        source.chunk_count = len(chunks)
        source.status = "synced"
        source.coverage = "complete"
        source.error = None
        source.synced_at = now
        source.updated_at = now
        revision = TranscriptSourceRevision(
            source_id=source.id,
            source_revision=source.source_revision,
            project_name=source.project_name,
            project_root=source.project_root,
            client=source.client,
            session_id=source.session_id,
            source_kind=source.source_kind,
            source_uri=source.source_uri,
            raw_sha256=source.raw_sha256,
            normalized_sha256=source.normalized_sha256,
            raw_size_bytes=source.raw_size_bytes,
            normalized_size_bytes=source.normalized_size_bytes,
            mtime_ns=source.mtime_ns,
            parser_version=source.parser_version,
            coverage="complete",
            chunk_count=len(chunks),
            sequence_count=source.sequence_count,
            metadata=dict(source.metadata),
            captured_at=now,
        )

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._assert_compatible_revision_locked(revision, normalized_text)
                self._upsert_source_locked(source)
                self._conn.execute(
                    """
                    INSERT INTO transcript_source_revisions (
                        source_id, source_revision, raw_sha256,
                        normalized_sha256, raw_size_bytes,
                        normalized_size_bytes, raw_bytes, captured_at, data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, source_revision) DO NOTHING
                    """,
                    (
                        source.id,
                        source.source_revision,
                        source.raw_sha256,
                        source.normalized_sha256,
                        source.raw_size_bytes,
                        source.normalized_size_bytes,
                        sqlite3.Binary(native_bytes),
                        now.isoformat(),
                        json.dumps(revision.to_dict(), ensure_ascii=False),
                    ),
                )
                self._conn.execute(
                    "DELETE FROM transcript_chunks WHERE source_id = ? AND source_revision = ?",
                    (source.id, source.source_revision),
                )
                for chunk in chunks:
                    self._insert_chunk_locked(chunk)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def get_source(self, source_id: str) -> TranscriptSource | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM transcript_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        return self._source_from_row(row)

    def find_source(
        self,
        *,
        project_name: str,
        client: str,
        session_id: str,
        source_uri: str | None = None,
    ) -> TranscriptSource | None:
        where_uri = " AND source_uri = ?" if source_uri is not None else ""
        params: tuple[Any, ...] = (project_name, client, session_id)
        if source_uri is not None:
            params = (*params, source_uri)
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT data FROM transcript_sources
                WHERE project_name = ? AND client = ? AND session_id = ?
                {where_uri}
                ORDER BY updated_at DESC LIMIT 1
                """,
                params,
            ).fetchone()
        return self._source_from_row(row)

    def list_sources_for_session(
        self,
        *,
        project_name: str,
        client: str,
        session_id: str,
    ) -> list[TranscriptSource]:
        """Return every locator ever observed for one native session identifier."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM transcript_sources
                WHERE project_name = ? AND client = ? AND session_id = ?
                ORDER BY updated_at DESC
                """,
                (project_name, client, session_id),
            ).fetchall()
        return [TranscriptSource.from_dict(json.loads(row["data"])) for row in rows]

    def get_revision(
        self,
        source_id: str,
        source_revision: str,
    ) -> TranscriptSourceRevision | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT data FROM transcript_source_revisions
                WHERE source_id = ? AND source_revision = ?
                """,
                (source_id, source_revision),
            ).fetchone()
        if row is None:
            return None
        return TranscriptSourceRevision.from_dict(json.loads(row["data"]))

    def list_revisions(self, source_id: str) -> list[TranscriptSourceRevision]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM transcript_source_revisions
                WHERE source_id = ? ORDER BY captured_at ASC
                """,
                (source_id,),
            ).fetchall()
        return [
            TranscriptSourceRevision.from_dict(json.loads(row["data"]))
            for row in rows
        ]

    def list_sources(
        self,
        *,
        project_name: str | None = None,
        client: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TranscriptSource]:
        where: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            where.append("project_name = ?")
            params.append(project_name)
        if client is not None:
            where.append("client = ?")
            params.append(client)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT data FROM transcript_sources"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [TranscriptSource.from_dict(json.loads(row["data"])) for row in rows]

    def list_chunks(
        self,
        source_id: str,
        *,
        source_revision: str | None = None,
    ) -> list[TranscriptChunk]:
        revision = source_revision
        if revision is None:
            source = self.get_source(source_id)
            if source is None:
                return []
            revision = source.source_revision
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT data FROM transcript_chunks
                WHERE source_id = ? AND source_revision = ?
                ORDER BY chunk_index ASC
                """,
                (source_id, revision),
            ).fetchall()
        return [TranscriptChunk.from_dict(json.loads(row["data"])) for row in rows]

    def reconstruct(self, source_id: str, *, source_revision: str | None = None) -> str:
        revision_id = source_revision
        if revision_id is None:
            source = self.get_source(source_id)
            if source is None:
                raise KeyError(source_id)
            revision_id = source.source_revision
        revision = self.get_revision(source_id, revision_id)
        if revision is None:
            raise KeyError(f"{source_id}@{revision_id}")
        chunks = self.list_chunks(source_id, source_revision=revision_id)
        if not chunks and revision.normalized_size_bytes == 0:
            return ""
        return reconstruct_transcript(
            chunks,
            expected_sha256=revision.normalized_sha256,
        )

    def reconstruct_raw(
        self,
        source_id: str,
        *,
        source_revision: str | None = None,
    ) -> bytes:
        revision_id = source_revision
        if revision_id is None:
            source = self.get_source(source_id)
            if source is None:
                raise KeyError(source_id)
            revision_id = source.source_revision
        with self._lock:
            row = self._conn.execute(
                """
                SELECT raw_bytes, raw_sha256 FROM transcript_source_revisions
                WHERE source_id = ? AND source_revision = ?
                """,
                (source_id, revision_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"{source_id}@{revision_id}")
        value = bytes(row["raw_bytes"])
        if sha256_bytes(value) != row["raw_sha256"]:
            raise ValueError("stored transcript source bytes failed hash validation")
        return value

    def get_scan_frontier(
        self,
        *,
        project_name: str,
        client: str,
        source_root: str,
    ) -> TranscriptScanFrontier | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT data FROM transcript_scan_frontiers
                WHERE project_name = ? AND client = ? AND source_root = ?
                """,
                (project_name, client, source_root),
            ).fetchone()
        if row is None:
            return None
        return TranscriptScanFrontier.from_dict(json.loads(row["data"]))

    def save_scan_frontier(self, frontier: TranscriptScanFrontier) -> None:
        frontier.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO transcript_scan_frontiers (
                    project_name, client, source_root, cursor_key,
                    scan_cycle, updated_at, data
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_name, client, source_root) DO UPDATE SET
                    cursor_key=excluded.cursor_key,
                    scan_cycle=excluded.scan_cycle,
                    updated_at=excluded.updated_at,
                    data=excluded.data
                """,
                (
                    frontier.project_name,
                    frontier.client,
                    frontier.source_root,
                    frontier.cursor_key,
                    frontier.scan_cycle,
                    frontier.updated_at.isoformat(),
                    json.dumps(frontier.to_dict(), ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def list_scan_frontiers(
        self,
        *,
        project_name: str | None = None,
        client: str | None = None,
    ) -> list[TranscriptScanFrontier]:
        where: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            where.append("project_name = ?")
            params.append(project_name)
        if client is not None:
            where.append("client = ?")
            params.append(client)
        sql = "SELECT data FROM transcript_scan_frontiers"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [TranscriptScanFrontier.from_dict(json.loads(row["data"])) for row in rows]

    def reset_scan_frontier(
        self,
        *,
        project_name: str,
        client: str,
        source_root: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM transcript_scan_frontiers
                WHERE project_name = ? AND client = ? AND source_root = ?
                """,
                (project_name, client, source_root),
            )
            self._conn.commit()

    def mark_sources_missing_from_inventory(
        self,
        *,
        project_name: str,
        client: str,
        observed_session_ids: set[str],
    ) -> list[TranscriptSource]:
        """Mark absent sources missing without deleting any captured revision.

        Callers must pass the complete host inventory for the project/client
        scope. This deliberately keys on native session IDs rather than paths:
        a moved locator remains present while its transcript ledger aliases are
        retained for audit.
        """

        observed = {str(value) for value in observed_session_ids}
        sources = self.list_sources(project_name=project_name, client=client, limit=100_000)
        now = datetime.now(timezone.utc)
        missing: list[TranscriptSource] = []
        for source in sources:
            if source.session_id in observed or source.status == "missing":
                continue
            source.status = "missing"
            source.error = None
            source.updated_at = now
            source.metadata = {
                **dict(source.metadata),
                "missing_since": now.isoformat(),
                "missing_reason": "absent_from_complete_host_inventory",
            }
            missing.append(source)
        if not missing:
            return []
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for source in missing:
                    self._upsert_source_locked(source)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return missing

    def enqueue_distill_job(
        self,
        source_id: str,
        *,
        pipeline_version: str = "lossless-distill-v1",
        active_limit: int | None = None,
        recent_first: bool = True,
    ) -> SessionDistillJob:
        return self._distill.enqueue(
            source_id,
            pipeline_version=pipeline_version,
            active_limit=active_limit,
            recent_first=recent_first,
        )

    def get_distill_job(self, job_id: str) -> SessionDistillJob | None:
        return self._distill.get(job_id)

    def enable_zero_candidate_challenge(
        self,
        job_id: str,
    ) -> SessionDistillJob:
        return self._distill.enable_zero_candidate_challenge(job_id)

    def defer_distill_job(self, job_id: str, *, error: str) -> SessionDistillJob:
        return self._distill.defer(job_id, error=error)

    def rebalance_distill_jobs(
        self,
        project_name: str,
        *,
        target_active: int = 2,
        recent_first: bool = True,
    ) -> dict[str, int]:
        return self._distill.rebalance(
            project_name,
            target_active=target_active,
            recent_first=recent_first,
        )

    def reconcile_distill_jobs(
        self,
        *,
        project_name: str | None = None,
        now: datetime | None = None,
        recovery_budget: int | None = None,
    ) -> dict[str, int]:
        """Recompute job state from durable checkpoints after a restart."""

        return self._distill.reconcile(
            project_name=project_name,
            now=now,
            recovery_budget=recovery_budget,
        )

    def mark_distill_jobs_agent_offered(
        self,
        project_name: str,
        job_ids: list[str],
        *,
        offered_at: datetime | None = None,
    ) -> int:
        return self._distill.mark_agent_offered(
            project_name,
            job_ids,
            offered_at=offered_at,
        )

    def list_distill_jobs(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SessionDistillJob]:
        return self._distill.list(
            project_name=project_name,
            status=status,
            limit=limit,
        )

    def list_distill_checkpoints(self, job_id: str) -> list[DistillChunkCheckpoint]:
        return self._distill.list_checkpoints(job_id)

    def claim_distill_chunks(
        self,
        job_id: str,
        *,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 300,
    ) -> list[tuple[TranscriptChunk, DistillChunkCheckpoint]]:
        return self._distill.claim_chunks(
            job_id,
            lease_owner=lease_owner,
            limit=limit,
            lease_seconds=lease_seconds,
        )

    def checkpoint_distill_chunk(
        self,
        job_id: str,
        chunk_id: str,
        *,
        lease_owner: str,
        result: dict,
    ) -> SessionDistillJob:
        return self._distill.checkpoint_chunk(
            job_id,
            chunk_id,
            lease_owner=lease_owner,
            result=result,
        )

    def finalize_distill_job(
        self,
        job_id: str,
        *,
        semantic_review: dict,
        output_candidate_ids: list[str] | None = None,
    ) -> SessionDistillJob:
        return self._distill.finalize(
            job_id,
            semantic_review=semantic_review,
            output_candidate_ids=output_candidate_ids,
        )

    def record_distill_completion_outcome(
        self,
        job_id: str,
        *,
        disposition: str | None,
        reason_codes: list[str],
        promotion_summary: dict[str, Any],
        source_cleanup_status: str,
        source_cleanup_receipt_id: str | None = None,
    ) -> SessionDistillJob:
        """Record automatic promotion and source-cleanup results for one job."""

        return self._distill.record_completion_outcome(
            job_id,
            disposition=disposition,  # type: ignore[arg-type]
            reason_codes=reason_codes,
            promotion_summary=promotion_summary,
            source_cleanup_status=source_cleanup_status,  # type: ignore[arg-type]
            source_cleanup_receipt_id=source_cleanup_receipt_id,
        )

    def prune_completed_distill_evidence(
        self,
        job_id: str,
        *,
        receipt_id: str,
    ) -> dict[str, int]:
        """Remove one completed job's raw evidence while retaining its receipt row.

        ``distill_jobs`` has an intentional foreign key to the immutable source
        revision.  A processed-source cleanup therefore retains a zero-content
        revision/source stub and a redacted completed job instead of weakening
        the FK or creating a second completion ledger.
        """

        empty_sha = sha256_bytes(b"")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                job = self._distill._get_job_locked(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job.status != "completed":
                    raise ValueError(
                        "processed-source cleanup requires a completed distill job"
                    )
                revision_rows = self._conn.execute(
                    "SELECT data FROM transcript_source_revisions "
                    "WHERE source_id = ? ORDER BY captured_at ASC",
                    (job.source_id,),
                ).fetchall()
                if not revision_rows:
                    raise ValueError("distill source revision no longer exists")
                source_row = self._conn.execute(
                    "SELECT data FROM transcript_sources WHERE id = ?",
                    (job.source_id,),
                ).fetchone()
                if source_row is None:
                    raise ValueError("distill source no longer exists")

                checkpoint_count = int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM distill_job_chunks c "
                        "JOIN distill_jobs j ON j.id = c.job_id "
                        "WHERE j.source_id = ?",
                        (job.source_id,),
                    ).fetchone()[0]
                )
                chunk_count = int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM transcript_chunks "
                        "WHERE source_id = ?",
                        (job.source_id,),
                    ).fetchone()[0]
                )
                raw_bytes = int(
                    self._conn.execute(
                        "SELECT COALESCE(SUM(length(raw_bytes)), 0) "
                        "FROM transcript_source_revisions WHERE source_id = ?",
                        (job.source_id,),
                    ).fetchone()[0]
                    or 0
                )

                # Checkpoints reference chunks without ON DELETE CASCADE, so the
                # job-owned checkpoints must be removed first.
                self._conn.execute(
                    "DELETE FROM distill_job_chunks WHERE job_id IN "
                    "(SELECT id FROM distill_jobs WHERE source_id = ?)",
                    (job.source_id,),
                )
                self._conn.execute(
                    "DELETE FROM transcript_chunks WHERE source_id = ?",
                    (job.source_id,),
                )

                for revision_row in revision_rows:
                    revision = TranscriptSourceRevision.from_dict(
                        json.loads(revision_row["data"])
                    )
                    revision.project_root = ""
                    revision.session_id = ""
                    revision.source_uri = ""
                    revision.raw_sha256 = empty_sha
                    revision.normalized_sha256 = empty_sha
                    revision.raw_size_bytes = 0
                    revision.normalized_size_bytes = 0
                    revision.mtime_ns = None
                    revision.chunk_count = 0
                    revision.sequence_count = 0
                    revision.metadata = {
                        "evidence_state": "source_pruned",
                        "cleanup_receipt_id": receipt_id,
                    }
                    self._conn.execute(
                        """
                        UPDATE transcript_source_revisions
                        SET raw_sha256 = ?, normalized_sha256 = ?,
                            raw_size_bytes = 0, normalized_size_bytes = 0,
                            raw_bytes = ?, data = ?
                        WHERE source_id = ? AND source_revision = ?
                        """,
                        (
                            empty_sha,
                            empty_sha,
                            sqlite3.Binary(b""),
                            json.dumps(revision.to_dict(), ensure_ascii=False),
                            job.source_id,
                            revision.source_revision,
                        ),
                    )

                source = TranscriptSource.from_dict(json.loads(source_row["data"]))
                if source.source_revision != job.source_revision:
                    raise ValueError(
                        "transcript source changed before processed-source cleanup"
                    )
                source.project_root = ""
                source.session_id = ""
                source.source_uri = f"processed-source://{source.id}"
                source.raw_sha256 = empty_sha
                source.normalized_sha256 = empty_sha
                source.raw_size_bytes = 0
                source.normalized_size_bytes = 0
                source.mtime_ns = None
                source.status = "missing"
                source.coverage = "complete"
                source.chunk_count = 0
                source.sequence_count = 0
                source.error = None
                source.metadata = {
                    "evidence_state": "source_pruned",
                    "cleanup_receipt_id": receipt_id,
                }
                self._upsert_source_locked(source)

                job_rows = self._conn.execute(
                    "SELECT data FROM distill_jobs WHERE source_id = ?",
                    (job.source_id,),
                ).fetchall()
                completed_jobs = 0
                for job_row in job_rows:
                    source_job = SessionDistillJob.from_dict(json.loads(job_row["data"]))
                    review = dict(source_job.semantic_review)
                    source_job.project_root = ""
                    source_job.session_id = ""
                    source_job.semantic_review = {
                        "last_turn_status": review.get("last_turn_status", "unknown"),
                        "evidence_status": review.get(
                            "evidence_status", "not_applicable"
                        ),
                        "promotion_decision": review.get(
                            "promotion_decision", "no_promotion"
                        ),
                        "contradiction_count": len(review.get("contradictions") or []),
                        "unfinished_work_count": len(
                            review.get("unfinished_work") or []
                        ),
                        "evidence_state": "source_pruned",
                    }
                    source_job.source_cleanup_status = "deleted"
                    source_job.source_cleanup_receipt_id = receipt_id
                    source_job.updated_at = datetime.now(timezone.utc)
                    completed_jobs += int(source_job.status == "completed")
                    self._distill._upsert_job_locked(source_job)
                self._conn.commit()
                return {
                    "revisions_pruned": len(revision_rows),
                    "raw_bytes_pruned": raw_bytes,
                    "chunks_deleted": chunk_count,
                    "checkpoints_deleted": checkpoint_count,
                    "completed_jobs_retained": completed_jobs,
                }
            except Exception:
                self._conn.rollback()
                raise

    def verify_completed_distill_evidence_pruned(self, job_id: str) -> dict[str, int]:
        """Return residual raw-ledger counts for a processed-source cleanup."""

        with self._lock:
            job = self._distill._get_job_locked(job_id)
            if job is None:
                return {"completed_job": 0, "raw_bytes": 1, "chunks": 1, "checkpoints": 1}
            revision = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(length(raw_bytes)), 0), "
                "COALESCE(SUM(raw_size_bytes), 0), "
                "COALESCE(SUM(normalized_size_bytes), 0) "
                "FROM transcript_source_revisions WHERE source_id = ?",
                (job.source_id,),
            ).fetchone()
            raw_residual = int(
                revision is None
                or int(revision[0] or 0) == 0
                or bool(
                    int(revision[1] or 0)
                    or int(revision[2] or 0)
                    or int(revision[3] or 0)
                )
            )
            chunks = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM transcript_chunks WHERE source_id = ?",
                    (job.source_id,),
                ).fetchone()[0]
            )
            checkpoints = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM distill_job_chunks c "
                    "JOIN distill_jobs j ON j.id = c.job_id "
                    "WHERE j.source_id = ?",
                    (job.source_id,),
                ).fetchone()[0]
            )
        return {
            "completed_job": int(job.status == "completed"),
            "raw_bytes": raw_residual,
            "chunks": chunks,
            "checkpoints": checkpoints,
        }

    def plan_hard_delete(
        self,
        *,
        project_name: str,
        session_id: str | None = None,
        source_id: str | None = None,
        before: datetime | None = None,
    ) -> dict[str, Any]:
        """Preview raw revisions, chunks, and jobs selected for erasure."""

        where = ["s.project_name = ?"]
        params: list[Any] = [project_name]
        if session_id is not None:
            where.append("s.session_id = ?")
            params.append(session_id)
        if source_id is not None:
            where.append("r.source_id = ?")
            params.append(source_id)
        if before is not None:
            cutoff = before if before.tzinfo else before.replace(tzinfo=timezone.utc)
            where.append("r.captured_at < ?")
            params.append(cutoff.astimezone(timezone.utc).isoformat())
        sql = f"""
            SELECT r.source_id, r.source_revision, r.raw_size_bytes,
                   r.normalized_size_bytes, r.captured_at,
                   s.session_id, s.client, s.source_uri
            FROM transcript_source_revisions r
            JOIN transcript_sources s ON s.id = r.source_id
            WHERE {' AND '.join(where)}
            ORDER BY r.captured_at ASC
        """
        with self._lock:
            revisions = [dict(row) for row in self._conn.execute(sql, params).fetchall()]
            keys = [(str(row["source_id"]), str(row["source_revision"])) for row in revisions]
            chunk_count = 0
            jobs: list[dict[str, Any]] = []
            for selected_source_id, selected_revision in keys:
                chunk_count += int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM transcript_chunks "
                        "WHERE source_id = ? AND source_revision = ?",
                        (selected_source_id, selected_revision),
                    ).fetchone()[0]
                )
                jobs.extend(
                    dict(row)
                    for row in self._conn.execute(
                        "SELECT id, status, phase, source_id, source_revision "
                        "FROM distill_jobs WHERE source_id = ? AND source_revision = ?",
                        (selected_source_id, selected_revision),
                    ).fetchall()
                )
        return {
            "project_name": project_name,
            "session_id": session_id,
            "source_id": source_id,
            "before": before.isoformat() if before is not None else None,
            "revisions": revisions,
            "revision_keys": keys,
            "source_ids": sorted({str(row["source_id"]) for row in revisions}),
            "session_ids": sorted({str(row["session_id"]) for row in revisions}),
            "jobs": jobs,
            "job_ids": sorted({str(row["id"]) for row in jobs}),
            "revision_count": len(revisions),
            "chunk_count": chunk_count,
            "raw_bytes": sum(int(row["raw_size_bytes"]) for row in revisions),
        }

    def hard_delete_revisions(
        self,
        revision_keys: list[tuple[str, str]],
        *,
        project_name: str,
        reason: str,
        audit_counts: dict[str, int] | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Delete selected raw revisions and dependent ledger rows atomically."""

        unique_keys = list(dict.fromkeys((str(a), str(b)) for a, b in revision_keys))
        deleted_revisions = 0
        deleted_jobs = 0
        deleted_chunks = 0
        affected_sources = {source_id for source_id, _revision in unique_keys}
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for selected_source_id, selected_revision in unique_keys:
                    deleted_chunks += int(
                        self._conn.execute(
                            "SELECT COUNT(*) FROM transcript_chunks "
                            "WHERE source_id = ? AND source_revision = ?",
                            (selected_source_id, selected_revision),
                        ).fetchone()[0]
                    )
                    deleted_jobs += int(
                        self._conn.execute(
                            "SELECT COUNT(*) FROM distill_jobs "
                            "WHERE source_id = ? AND source_revision = ?",
                            (selected_source_id, selected_revision),
                        ).fetchone()[0]
                    )
                    self._conn.execute(
                        "DELETE FROM distill_jobs WHERE source_id = ? AND source_revision = ?",
                        (selected_source_id, selected_revision),
                    )
                    cursor = self._conn.execute(
                        "DELETE FROM transcript_source_revisions "
                        "WHERE source_id = ? AND source_revision = ?",
                        (selected_source_id, selected_revision),
                    )
                    deleted_revisions += max(0, cursor.rowcount)

                deleted_sources = 0
                for selected_source_id in affected_sources:
                    remaining = self._conn.execute(
                        "SELECT data FROM transcript_source_revisions "
                        "WHERE source_id = ? ORDER BY captured_at DESC LIMIT 1",
                        (selected_source_id,),
                    ).fetchone()
                    if remaining is None:
                        deleted_sources += max(
                            0,
                            self._conn.execute(
                                "DELETE FROM transcript_sources WHERE id = ?",
                                (selected_source_id,),
                            ).rowcount,
                        )
                        continue
                    revision = TranscriptSourceRevision.from_dict(json.loads(remaining["data"]))
                    source_row = self._conn.execute(
                        "SELECT data FROM transcript_sources WHERE id = ?",
                        (selected_source_id,),
                    ).fetchone()
                    if source_row is None:
                        continue
                    source = TranscriptSource.from_dict(json.loads(source_row["data"]))
                    source.source_revision = revision.source_revision
                    source.raw_sha256 = revision.raw_sha256
                    source.normalized_sha256 = revision.normalized_sha256
                    source.raw_size_bytes = revision.raw_size_bytes
                    source.normalized_size_bytes = revision.normalized_size_bytes
                    source.chunk_count = revision.chunk_count
                    source.sequence_count = revision.sequence_count
                    source.mtime_ns = revision.mtime_ns
                    source.parser_version = revision.parser_version
                    source.updated_at = datetime.now(timezone.utc)
                    source.metadata = {
                        **dict(source.metadata),
                        "restored_after_hard_delete": revision.source_revision,
                    }
                    self._upsert_source_locked(source)

                counts = {
                    "revisions": deleted_revisions,
                    "chunks": deleted_chunks,
                    "distill_jobs": deleted_jobs,
                    "sources": deleted_sources,
                    **(audit_counts or {}),
                }
                audit_id = str(receipt.get("id")) if receipt else str(uuid4())
                now = datetime.now(timezone.utc)
                audit_payload = {
                    **(receipt or {}),
                    "id": audit_id,
                    "project_name": project_name,
                    "reason": reason,
                    "counts": counts,
                    "target_digests": [
                        sha256_text(f"{source_id}@{revision}")
                        for source_id, revision in unique_keys
                    ],
                    "deleted_at": now.isoformat(),
                }
                self._conn.execute(
                    "INSERT OR REPLACE INTO transcript_deletion_audit "
                    "(id, project_name, deleted_at, reason, data) VALUES (?, ?, ?, ?, ?)",
                    (
                        audit_id,
                        project_name,
                        now.isoformat(),
                        reason,
                        json.dumps(audit_payload, ensure_ascii=False),
                    ),
                )
                self._conn.commit()
                return audit_payload
            except Exception:
                self._conn.rollback()
                raise

    def save_deletion_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Durably upsert a privacy-safe hard-delete receipt.

        The caller owns receipt redaction. This store intentionally persists
        only the supplied summary and never enriches it with transcript rows.
        """

        receipt_id = str(receipt.get("id") or "")
        project_name = str(receipt.get("project_name") or "")
        reason = str(receipt.get("reason") or "")
        timestamp = str(
            receipt.get("completed_at")
            or receipt.get("requested_at")
            or datetime.now(timezone.utc).isoformat()
        )
        if not receipt_id or not project_name or not reason:
            raise ValueError("deletion receipt requires id, project_name, and reason")
        payload = dict(receipt)
        payload["id"] = receipt_id
        payload["project_name"] = project_name
        payload["reason"] = reason
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO transcript_deletion_audit "
                "(id, project_name, deleted_at, reason, data) VALUES (?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    project_name,
                    timestamp,
                    reason,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        return payload

    def verify_hard_delete(
        self,
        revision_keys: list[tuple[str, str]],
        *,
        job_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Count selected ledger records that still exist after erasure."""

        remaining = {"revisions": 0, "chunks": 0, "distill_jobs": 0}
        unique_keys = list(dict.fromkeys((str(a), str(b)) for a, b in revision_keys))
        with self._lock:
            for source_id, source_revision in unique_keys:
                remaining["revisions"] += int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM transcript_source_revisions "
                        "WHERE source_id = ? AND source_revision = ?",
                        (source_id, source_revision),
                    ).fetchone()[0]
                )
                remaining["chunks"] += int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM transcript_chunks "
                        "WHERE source_id = ? AND source_revision = ?",
                        (source_id, source_revision),
                    ).fetchone()[0]
                )
            for job_id in set(map(str, job_ids or [])):
                remaining["distill_jobs"] += int(
                    self._conn.execute(
                        "SELECT COUNT(*) FROM distill_jobs WHERE id = ?",
                        (job_id,),
                    ).fetchone()[0]
                )
        return remaining

    def list_deletion_audit(
        self,
        *,
        project_name: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT data FROM transcript_deletion_audit"
        params: tuple[Any, ...] = ()
        if project_name is not None:
            sql += " WHERE project_name = ?"
            params = (project_name,)
        sql += " ORDER BY deleted_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def matches_hard_delete_tombstone(
        self,
        *,
        project_name: str,
        client: str,
        session_id: str,
        source_id: str,
        source_revision: str | None = None,
    ) -> bool:
        """Return whether explicit erasure forbids recapturing this source.

        Session/source erasure is durable privacy intent.  Retention cutoffs
        are intentionally excluded because they must not block future
        revisions.  In-progress and partial receipts also fail closed: a
        concurrent adapter must not recreate evidence while erasure is being
        verified or repaired.
        """

        session_digest = sha256_text(session_id)
        source_digest = sha256_text(source_id)
        source_identity_digest = sha256_text(f"{client}\x1f{session_id}")
        for receipt in self.list_deletion_audit(project_name=project_name):
            if (
                receipt.get("kind") == "processed_source_cleanup"
                and receipt.get("status")
                in {"in_progress", "succeeded", "partial_failure"}
                and source_revision is not None
            ):
                scope = receipt.get("scope")
                if not isinstance(scope, dict):
                    continue
                identity_matches = bool(
                    scope.get("source_id_sha256") == source_digest
                    or scope.get("session_id_sha256") == session_digest
                )
                if (
                    identity_matches
                    and (
                        scope.get("source_revision_sha256")
                        == sha256_text(source_revision)
                        or sha256_text(source_revision)
                        in set(scope.get("source_revision_sha256s") or [])
                    )
                ):
                    return True
                continue
            if receipt.get("kind") != "hard_delete" or receipt.get("status") not in {
                "in_progress",
                "succeeded",
                "partial_failure",
            }:
                continue
            scope = receipt.get("scope")
            if not isinstance(scope, dict) or scope.get("before") is not None:
                continue
            if scope.get("session_id_sha256") == session_digest:
                return True
            if scope.get("source_id_sha256") == source_digest:
                return True
            source_identities = scope.get("source_identity_sha256")
            if (
                isinstance(source_identities, list)
                and source_identity_digest in source_identities
            ):
                return True
        return False

    def _init_schema(self) -> None:
        with self._lock:
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version > TRANSCRIPT_LEDGER_SCHEMA_VERSION:
                raise RuntimeError(
                    "transcript ledger schema is newer than this harness-mem runtime"
                )
            has_legacy = self._table_exists_locked("transcript_sources") and not (
                self._table_exists_locked("transcript_source_revisions")
            )
            if has_legacy:
                self._migrate_legacy_v1_locked()
            else:
                if (
                    self._table_exists_locked("transcript_sources")
                    and not self._column_exists_locked(
                        "transcript_sources",
                        "source_uri",
                    )
                ):
                    self._conn.execute(
                        "ALTER TABLE transcript_sources "
                        "ADD COLUMN source_uri TEXT NOT NULL DEFAULT ''"
                    )
                    rows = self._conn.execute(
                        "SELECT id, data FROM transcript_sources"
                    ).fetchall()
                    for row in rows:
                        payload = json.loads(row["data"])
                        self._conn.execute(
                            "UPDATE transcript_sources SET source_uri = ? WHERE id = ?",
                            (str(payload.get("source_uri") or ""), row["id"]),
                        )
                self._create_schema_locked()
            self._conn.execute(
                f"PRAGMA user_version={TRANSCRIPT_LEDGER_SCHEMA_VERSION}"
            )
            self._conn.commit()

    def _create_schema_locked(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcript_sources (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                client TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL,
                UNIQUE(project_name, client, session_id, source_uri)
            );
            CREATE INDEX IF NOT EXISTS idx_transcript_sources_project_status
                ON transcript_sources(project_name, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_transcript_sources_client
                ON transcript_sources(client, updated_at DESC);

            CREATE TABLE IF NOT EXISTS transcript_source_revisions (
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                normalized_sha256 TEXT NOT NULL,
                raw_size_bytes INTEGER NOT NULL,
                normalized_size_bytes INTEGER NOT NULL,
                raw_bytes BLOB NOT NULL,
                captured_at TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY(source_id, source_revision),
                FOREIGN KEY(source_id) REFERENCES transcript_sources(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transcript_chunks (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                data TEXT NOT NULL,
                UNIQUE(source_id, source_revision, chunk_index),
                FOREIGN KEY(source_id, source_revision)
                    REFERENCES transcript_source_revisions(source_id, source_revision)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_transcript_chunks_source_revision
                ON transcript_chunks(source_id, source_revision, chunk_index);

            CREATE TABLE IF NOT EXISTS distill_jobs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                project_name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL,
                FOREIGN KEY(source_id, source_revision)
                    REFERENCES transcript_source_revisions(source_id, source_revision)
            );
            CREATE INDEX IF NOT EXISTS idx_distill_jobs_project_status
                ON distill_jobs(project_name, status, created_at ASC);

            CREATE TABLE IF NOT EXISTS distill_job_chunks (
                job_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                lease_owner TEXT,
                lease_until TEXT,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY(job_id, chunk_id),
                FOREIGN KEY(job_id) REFERENCES distill_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(chunk_id) REFERENCES transcript_chunks(id)
            );
            CREATE INDEX IF NOT EXISTS idx_distill_job_chunks_claim
                ON distill_job_chunks(job_id, status, chunk_index);

            CREATE TABLE IF NOT EXISTS transcript_scan_frontiers (
                project_name TEXT NOT NULL,
                client TEXT NOT NULL,
                source_root TEXT NOT NULL,
                cursor_key TEXT,
                scan_cycle INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY(project_name, client, source_root)
            );

            CREATE TABLE IF NOT EXISTS transcript_deletion_audit (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transcript_deletion_audit_project
                ON transcript_deletion_audit(project_name, deleted_at DESC);
            """
        )

    def _migrate_legacy_v1_locked(self) -> None:
        self._conn.execute("ALTER TABLE transcript_sources RENAME TO transcript_sources_v1")
        self._conn.execute("ALTER TABLE transcript_chunks RENAME TO transcript_chunks_v1")
        self._create_schema_locked()
        source_rows = self._conn.execute(
            "SELECT data FROM transcript_sources_v1"
        ).fetchall()
        for row in source_rows:
            payload = json.loads(row["data"])
            source_id = str(payload["id"])
            revision_id = str(payload["source_revision"])
            chunk_rows = self._conn.execute(
                """
                SELECT data FROM transcript_chunks_v1
                WHERE source_id = ? AND source_revision = ? ORDER BY chunk_index
                """,
                (source_id, revision_id),
            ).fetchall()
            chunks = [TranscriptChunk.from_dict(json.loads(item["data"])) for item in chunk_rows]
            normalized = "".join(chunk.raw_content for chunk in chunks)
            native_bytes = normalized.encode("utf-8")
            payload.pop("content_sha256", None)
            payload.pop("size_bytes", None)
            payload.update(
                {
                    "source_revision": f"sha256:{sha256_bytes(native_bytes)}",
                    "raw_sha256": sha256_bytes(native_bytes),
                    "normalized_sha256": sha256_text(normalized),
                    "raw_size_bytes": len(native_bytes),
                    "normalized_size_bytes": len(native_bytes),
                    "coverage": "complete",
                    "metadata": {
                        **dict(payload.get("metadata") or {}),
                        "migrated_from_ledger_v1": True,
                    },
                }
            )
            source = TranscriptSource.from_dict(payload)
            migrated_chunks = [
                chunk.model_copy(update={"source_revision": source.source_revision})
                for chunk in chunks
            ]
            self._upsert_source_locked(source)
            revision = TranscriptSourceRevision(
                source_id=source.id,
                source_revision=source.source_revision,
                project_name=source.project_name,
                project_root=source.project_root,
                client=source.client,
                session_id=source.session_id,
                source_kind=source.source_kind,
                source_uri=source.source_uri,
                raw_sha256=source.raw_sha256,
                normalized_sha256=source.normalized_sha256,
                raw_size_bytes=source.raw_size_bytes,
                normalized_size_bytes=source.normalized_size_bytes,
                mtime_ns=source.mtime_ns,
                parser_version=source.parser_version,
                chunk_count=len(migrated_chunks),
                sequence_count=source.sequence_count,
                metadata=dict(source.metadata),
            )
            self._conn.execute(
                """
                INSERT INTO transcript_source_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.id,
                    source.source_revision,
                    source.raw_sha256,
                    source.normalized_sha256,
                    source.raw_size_bytes,
                    source.normalized_size_bytes,
                    sqlite3.Binary(native_bytes),
                    revision.captured_at.isoformat(),
                    json.dumps(revision.to_dict(), ensure_ascii=False),
                ),
            )
            for chunk in migrated_chunks:
                self._insert_chunk_locked(chunk)
        self._conn.execute("DROP TABLE transcript_chunks_v1")
        self._conn.execute("DROP TABLE transcript_sources_v1")

    def _upsert_source_locked(self, source: TranscriptSource) -> None:
        payload = json.dumps(source.to_dict(), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO transcript_sources (
                id, project_name, client, session_id, source_uri,
                source_revision, status, updated_at, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_name=excluded.project_name,
                client=excluded.client,
                session_id=excluded.session_id,
                source_uri=excluded.source_uri,
                source_revision=excluded.source_revision,
                status=excluded.status,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                source.id,
                source.project_name,
                source.client,
                source.session_id,
                source.source_uri,
                source.source_revision,
                source.status,
                source.updated_at.isoformat(),
                payload,
            ),
        )

    def _insert_chunk_locked(self, chunk: TranscriptChunk) -> None:
        self._conn.execute(
            """
            INSERT INTO transcript_chunks (
                id, source_id, source_revision, chunk_index,
                content_sha256, size_bytes, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.id,
                chunk.source_id,
                chunk.source_revision,
                chunk.chunk_index,
                chunk.content_sha256,
                chunk.size_bytes,
                json.dumps(chunk.to_dict(), ensure_ascii=False),
            ),
        )

    def _assert_compatible_revision_locked(
        self,
        revision: TranscriptSourceRevision,
        normalized_text: str,
    ) -> None:
        row = self._conn.execute(
            """
            SELECT raw_sha256, normalized_sha256 FROM transcript_source_revisions
            WHERE source_id = ? AND source_revision = ?
            """,
            (revision.source_id, revision.source_revision),
        ).fetchone()
        if row is None:
            return
        if row["raw_sha256"] != revision.raw_sha256:
            raise ValueError("immutable transcript revision raw hash changed")
        if row["normalized_sha256"] != sha256_text(normalized_text):
            raise ValueError("immutable transcript revision normalized hash changed")

    @staticmethod
    def _validate_snapshot(
        source: TranscriptSource,
        chunks: list[TranscriptChunk],
        native_bytes: bytes,
    ) -> str:
        normalized = "" if not chunks else reconstruct_transcript(
            chunks,
            expected_sha256=source.normalized_sha256,
        )
        if source.raw_sha256 != sha256_bytes(native_bytes):
            raise ValueError("source raw hash does not match native bytes")
        if not source.source_revision.startswith(f"sha256:{source.raw_sha256}"):
            raise ValueError("source revision does not match native bytes")
        if source.normalized_sha256 != sha256_text(normalized):
            raise ValueError("source normalized hash does not match transcript chunks")
        if source.raw_size_bytes != len(native_bytes):
            raise ValueError("source raw size does not match native bytes")
        if source.normalized_size_bytes != len(normalized.encode("utf-8")):
            raise ValueError("source normalized size does not match transcript chunks")
        for chunk in chunks:
            if chunk.source_id != source.id:
                raise ValueError("chunk source id does not match transcript source")
            if chunk.source_revision != source.source_revision:
                raise ValueError("chunk revision does not match transcript source")
        return normalized

    @staticmethod
    def _source_from_row(row: sqlite3.Row | None) -> TranscriptSource | None:
        if row is None:
            return None
        return TranscriptSource.from_dict(json.loads(row["data"]))

    def _table_exists_locked(self, table: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _column_exists_locked(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)


__all__ = ["TRANSCRIPT_LEDGER_SCHEMA_VERSION", "TranscriptStore"]
