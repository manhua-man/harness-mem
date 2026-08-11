"""Resumable lossless session distillation job schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
ZeroCandidateFinding = Literal["absent", "not_durable", "candidate_required"]


class ZeroCandidateExchangeRef(BaseModel):
    """Content-addressed proof that one required exchange was inspected."""

    exchange_index: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    model_config = {"extra": "forbid"}


class ZeroCandidateChecks(BaseModel):
    """Exhaustive memory-value checks for a zero-candidate conclusion."""

    user_correction: ZeroCandidateFinding
    explicit_decision: ZeroCandidateFinding
    successful_solution: ZeroCandidateFinding
    repeated_failure: ZeroCandidateFinding
    rule_or_preference: ZeroCandidateFinding
    reusable_workflow_or_fact: ZeroCandidateFinding
    version_or_migration: ZeroCandidateFinding
    unfinished_handoff: ZeroCandidateFinding

    model_config = {"extra": "forbid"}


class ZeroCandidateChallenge(BaseModel):
    """Machine-checkable pressure test before a zero-candidate completion."""

    version: Literal["v1"]
    source_revision: str = Field(min_length=1)
    evidence_fidelity: Literal["complete", "partial", "contradicted"]
    future_utility: Literal["none", "session_only", "durable"]
    checks: ZeroCandidateChecks
    inspected_exchange_refs: list[ZeroCandidateExchangeRef] = Field(
        default_factory=list,
        max_length=8,
    )
    conclusion: Literal["no_durable_candidate", "candidate_required"]
    rationale: str = Field(min_length=12, max_length=2000)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_conclusion(self) -> "ZeroCandidateChallenge":
        findings = self.checks.model_dump().values()
        if "candidate_required" in findings or self.future_utility == "durable":
            if self.conclusion != "candidate_required":
                raise ValueError("durable utility requires candidate_required")
        if (
            self.conclusion == "no_durable_candidate"
            and self.evidence_fidelity != "complete"
        ):
            raise ValueError("no_durable_candidate requires complete evidence fidelity")
        indexes = [item.exchange_index for item in self.inspected_exchange_refs]
        if len(indexes) != len(set(indexes)):
            raise ValueError("inspected exchange references must be unique")
        return self


class SessionSemanticReview(BaseModel):
    """Required end-of-session judgment before candidate promotion completes."""

    session_summary: str | None = Field(default=None, min_length=12, max_length=2000)
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
    zero_candidate_challenge: ZeroCandidateChallenge | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


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
    zero_candidate_challenge_version: Literal["v1"] | None = None
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
    # One semantic reviewer owns a reviewing job at a time. Chunk leases cover
    # structural reading only; these fields protect the model/finalize phase.
    review_lease_owner: str | None = None
    review_lease_until: datetime | None = None
    review_attempt_count: int = 0
    review_execution_source: str | None = None
    last_review_heartbeat_at: datetime | None = None
    # Job-level recovery state is separate from per-chunk attempt_count. It
    # records reconciliation events after restart/lease expiry and bounds
    # repeated recovery without inventing a background semantic worker.
    recovery_count: int = 0
    recovery_budget: int = 3
    recovery_reason_codes: list[str] = Field(default_factory=list)
    last_recovery_at: datetime | None = None
    last_progress_at: datetime | None = None
    recovery_exhausted_at: datetime | None = None
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
    "ZeroCandidateChallenge",
    "ZeroCandidateChecks",
    "ZeroCandidateExchangeRef",
    "ZeroCandidateFinding",
]
