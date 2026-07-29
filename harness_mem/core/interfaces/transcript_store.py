"""Lossless transcript ledger interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.transcript import (
    TranscriptChunk,
    TranscriptScanFrontier,
    TranscriptSource,
    TranscriptSourceRevision,
)
from harness_mem.core.schemas.session_distill import (
    DistillChunkCheckpoint,
    SessionDistillJob,
)


@runtime_checkable
class TranscriptStore(Protocol):
    """Project-scoped native transcript source and revision persistence."""

    def save_source(self, source: TranscriptSource) -> None: ...

    def save_snapshot(
        self,
        source: TranscriptSource,
        chunks: list[TranscriptChunk],
        *,
        raw_bytes: bytes | None = None,
    ) -> None: ...

    def get_source(self, source_id: str) -> TranscriptSource | None: ...

    def find_source(
        self,
        *,
        project_name: str,
        client: str,
        session_id: str,
        source_uri: str | None = None,
    ) -> TranscriptSource | None: ...

    def list_sources_for_session(
        self,
        *,
        project_name: str,
        client: str,
        session_id: str,
    ) -> list[TranscriptSource]: ...

    def list_sources(
        self,
        *,
        project_name: str | None = None,
        client: str | None = None,
        limit: int = 100,
    ) -> list[TranscriptSource]: ...

    def get_revision(
        self,
        source_id: str,
        source_revision: str,
    ) -> TranscriptSourceRevision | None: ...

    def list_chunks(
        self,
        source_id: str,
        *,
        source_revision: str | None = None,
    ) -> list[TranscriptChunk]: ...

    def reconstruct(
        self,
        source_id: str,
        *,
        source_revision: str | None = None,
    ) -> str: ...

    def reconstruct_raw(
        self,
        source_id: str,
        *,
        source_revision: str | None = None,
    ) -> bytes: ...

    def get_scan_frontier(
        self,
        *,
        project_name: str,
        client: str,
        source_root: str,
    ) -> TranscriptScanFrontier | None: ...

    def save_scan_frontier(self, frontier: TranscriptScanFrontier) -> None: ...

    def list_scan_frontiers(
        self,
        *,
        project_name: str | None = None,
        client: str | None = None,
    ) -> list[TranscriptScanFrontier]: ...

    def reset_scan_frontier(
        self,
        *,
        project_name: str,
        client: str,
        source_root: str,
    ) -> None: ...

    def mark_sources_missing_from_inventory(
        self,
        *,
        project_name: str,
        client: str,
        observed_session_ids: set[str],
    ) -> list[TranscriptSource]: ...

    def enqueue_distill_job(
        self,
        source_id: str,
        *,
        pipeline_version: str = "lossless-distill-v1",
        active_limit: int | None = None,
        recent_first: bool = True,
    ) -> SessionDistillJob: ...

    def get_distill_job(self, job_id: str) -> SessionDistillJob | None: ...

    def list_distill_jobs(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SessionDistillJob]: ...

    def claim_distill_chunks(
        self,
        job_id: str,
        *,
        lease_owner: str,
        limit: int = 1,
        lease_seconds: int = 300,
    ) -> list[tuple[TranscriptChunk, DistillChunkCheckpoint]]: ...

    def checkpoint_distill_chunk(
        self,
        job_id: str,
        chunk_id: str,
        *,
        lease_owner: str,
        result: dict,
    ) -> SessionDistillJob: ...

    def finalize_distill_job(
        self,
        job_id: str,
        *,
        semantic_review: dict,
        output_candidate_ids: list[str] | None = None,
    ) -> SessionDistillJob: ...

    def record_distill_completion_outcome(
        self,
        job_id: str,
        *,
        disposition: str | None,
        reason_codes: list[str],
        promotion_summary: dict,
        source_cleanup_status: str,
        source_cleanup_receipt_id: str | None = None,
    ) -> SessionDistillJob: ...

    def prune_completed_distill_evidence(
        self,
        job_id: str,
        *,
        receipt_id: str,
    ) -> dict[str, int]: ...

    def verify_completed_distill_evidence_pruned(
        self,
        job_id: str,
    ) -> dict[str, int]: ...

    def flush_sensitive_deletes(self) -> None: ...


__all__ = ["TranscriptStore"]
