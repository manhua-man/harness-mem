"""Resumable lossless session-distillation job schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


DistillJobStatus = Literal[
    "queued",
    "processing",
    "reviewing",
    "completed",
    "retryable",
    "parked",
    "failed",
    "stale",
]
DistillJobPhase = Literal["chunks", "review", "promotion", "done"]
DistillChunkStatus = Literal["pending", "processing", "completed", "retryable", "failed"]
CompletionDisposition = Literal["promoted", "no_candidate"]
SourceCleanupStatus = Literal[
    "retained",
    "deleted",
    "partial_failure",
    "unsupported",
]


class SessionSemanticReview(BaseModel):
    """Required end-of-session judgment before candidate promotion completes."""

    final_user_request: str
    final_outcome: str
    last_turn_status: Literal["answered", "unfinished", "unknown"]
    contradictions: list[str]
    unfinished_work: list[str]
    evidence_status: Literal[
        "answered",
        "partial",
        "contradicted",
        "not_applicable",
    ]
    promotion_decision: Literal[
        "promote",
        "partial",
        "no_promotion",
        "blocked",
    ]

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class SessionDistillJob(BaseModel):
    """One fixed source revision processed through ordered transcript chunks."""

    id: str
    idempotency_key: str
    project_name: str
    project_root: str
    client: str
    session_id: str
    source_id: str
    source_revision: str
    pipeline_version: str = "lossless-distill-v1"
    status: DistillJobStatus = "queued"
    phase: DistillJobPhase = "chunks"
    expected_chunk_count: int = 0
    completed_chunk_count: int = 0
    output_candidate_ids: list[str] = Field(default_factory=list)
    structural_audit: dict = Field(default_factory=dict)
    semantic_review: dict = Field(default_factory=dict)
    completion_disposition: CompletionDisposition | None = None
    completion_reason_codes: list[str] = Field(default_factory=list)
    promotion_summary: dict = Field(default_factory=dict)
    source_cleanup_status: SourceCleanupStatus | None = None
    source_cleanup_receipt_id: str | None = None
    error: str | None = None
    attempt_count: int = 0
    retry_after: datetime | None = None
    drainer_lane: Literal["recent", "oldest"] | None = None
    drainer_selected_at: datetime | None = None
    agent_offer_day: str | None = None
    agent_offer_count: int = 0
    last_agent_offered_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> "SessionDistillJob":
        return cls(**payload)


class DistillChunkCheckpoint(BaseModel):
    """Durable processing state for one fixed transcript chunk."""

    job_id: str
    chunk_id: str
    chunk_index: int
    status: DistillChunkStatus = "pending"
    attempt_count: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    result: dict = Field(default_factory=dict)
    error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> "DistillChunkCheckpoint":
        return cls(**payload)


__all__ = [
    "DistillChunkCheckpoint",
    "DistillChunkStatus",
    "DistillJobPhase",
    "DistillJobStatus",
    "CompletionDisposition",
    "SessionDistillJob",
    "SessionSemanticReview",
    "SourceCleanupStatus",
]
