"""Strict provider response models for autonomous distillation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_mem.core.schemas.assimilation import AssimilationDisposition


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationRef(_StrictModel):
    kind: Literal["user_statement", "transcript", "repository"]
    content_sha256: str = Field(min_length=64, max_length=64)
    exchange_index: int | None = Field(default=None, ge=1)
    role: Literal["user", "assistant"] | None = None
    chunk_index: int | None = Field(default=None, ge=0)
    locator: str | None = Field(default=None, max_length=4096)


class _CandidateBase(_StrictModel):
    evidence_basis: Literal["user_statement", "transcript", "repository"]
    verification_outcome: Literal["verified", "unverified", "contradicted"]
    verification_refs: list[VerificationRef] = Field(default_factory=list, max_length=8)
    verification_reason_codes: list[str] = Field(default_factory=list, max_length=8)


class DistillCandidate(_CandidateBase):
    """Flat schema avoids unsupported oneOf in strict Structured Outputs."""

    kind: Literal["memory", "rule", "relation"]
    category: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, max_length=4000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = Field(default=None, max_length=12)
    pattern: str | None = Field(default=None, max_length=2000)
    trigger: str | None = Field(default=None, max_length=1000)
    examples: list[str] | None = Field(default=None, max_length=8)
    source_entity: str | None = Field(default=None, max_length=200)
    target_entity: str | None = Field(default=None, max_length=200)
    relation_type: str | None = Field(default=None, max_length=100)
    evidence: str | None = Field(default=None, max_length=2000)
    # This is a proposed long-term utility decision, not evidence verification.
    # The trusted runtime still validates evidence and enforces the disposition.
    assimilation_disposition: AssimilationDisposition = "add"
    assimilation_reason: str = Field(default="", max_length=1000)
    canonical_title: str | None = Field(default=None, max_length=160)
    topic_path: list[str] = Field(default_factory=list, max_length=8)


class AssimilationPoint(_StrictModel):
    """One post-verification outcome for one persisted candidate."""

    candidate_id: str = Field(min_length=1, max_length=128)
    disposition: AssimilationDisposition
    matched_truth_handles: list[str] = Field(default_factory=list, max_length=8)
    canonical_title: str | None = Field(default=None, max_length=160)
    canonical_statement: str | None = Field(default=None, max_length=4000)
    topic_path: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(min_length=8, max_length=1000)


class AssimilationDecision(_StrictModel):
    """Strict, tool-free semantic decision over verified points and truth handles."""

    points: list[AssimilationPoint] = Field(default_factory=list, max_length=12)

ChallengeChecks = Literal["absent", "not_durable", "candidate_required"]


class ZeroCandidateChecks(_StrictModel):
    user_correction: ChallengeChecks
    explicit_decision: ChallengeChecks
    successful_solution: ChallengeChecks
    repeated_failure: ChallengeChecks
    rule_or_preference: ChallengeChecks
    reusable_workflow_or_fact: ChallengeChecks
    version_or_migration: ChallengeChecks
    unfinished_handoff: ChallengeChecks


class InspectedExchangeRef(_StrictModel):
    exchange_index: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)


class ZeroCandidateChallenge(_StrictModel):
    version: Literal["v1"]
    source_revision: str = Field(min_length=8, max_length=160)
    evidence_fidelity: Literal["complete", "partial", "contradicted"]
    future_utility: Literal["none", "session_only", "durable"]
    checks: ZeroCandidateChecks
    inspected_exchange_refs: list[InspectedExchangeRef] = Field(min_length=1)
    conclusion: Literal["no_durable_candidate", "candidate_required"]
    rationale: str = Field(min_length=24, max_length=4000)


class SemanticReview(_StrictModel):
    session_summary: str = Field(min_length=12, max_length=4000)
    final_user_request: str = Field(min_length=1, max_length=4000)
    final_outcome: str = Field(min_length=1, max_length=4000)
    last_turn_status: Literal["answered", "unfinished", "unknown"]
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    unfinished_work: list[str] = Field(default_factory=list, max_length=20)
    evidence_status: Literal["answered", "partial", "contradicted", "not_applicable"]
    promotion_decision: Literal["promote", "partial", "no_promotion", "blocked"]
    zero_candidate_challenge: ZeroCandidateChallenge | None = None


class AutonomousDecision(_StrictModel):
    semantic_review: SemanticReview
    candidates: list[DistillCandidate] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def require_zero_candidate_review(self) -> "AutonomousDecision":
        challenge = self.semantic_review.zero_candidate_challenge
        if not self.candidates and challenge is None:
            raise ValueError("zero_candidate_challenge is required when candidates is empty")
        if self.candidates and challenge is not None:
            raise ValueError("zero_candidate_challenge must be null when candidates exist")
        return self


__all__ = [
    "AssimilationDecision",
    "AssimilationPoint",
    "AutonomousDecision",
    "DistillCandidate",
    "SemanticReview",
    "VerificationRef",
    "ZeroCandidateChallenge",
]
