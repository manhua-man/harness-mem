"""Strict provider response models for autonomous distillation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.core.schemas.knowledge import ClaimKind
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement


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


def _assert_atomic_title(value: str) -> str:
    """Reject enumerative titles without banning a single relational principle."""

    normalized = " ".join(value.split())
    lowered = normalized.casefold()
    if (
        normalized.count("、") >= 2
        or normalized.count(",") >= 2
        or normalized.count("/") >= 2
        or lowered.count(" and ") >= 2
    ):
        raise ValueError(
            "knowledge title enumerates multiple facts; split it into atomic items"
        )
    return normalized


class DistillCandidate(_CandidateBase):
    """One extracted promotion point plus its evidence locator.

    Extraction deliberately does not choose an assimilation disposition,
    canonical title, or project module. Those are module-3 decisions made
    only after the trusted evidence gate has re-read the cited source. A
    discovery candidate may still be broad: module 3 owns semantic splitting
    into independently retrievable knowledge items.
    """

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


class CanonicalKnowledgeItem(_StrictModel):
    """One proposed knowledge item created by a single point disposition.

    The provider schema validates shape only. Atomicity and specificity depend
    on the verified candidate and are enforced by the trusted assimilation
    runtime, where invalid proposals can receive bounded correction or the
    source-clause fallback.
    """

    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=4000)
    topic_path: list[str] = Field(min_length=1, max_length=8)
    claim_kind: ClaimKind

    @model_validator(mode="after")
    def normalize_proposed_item(self) -> "CanonicalKnowledgeItem":
        self.title = " ".join(self.title.split())
        self.statement = " ".join(self.statement.split())
        self.topic_path = [" ".join(part.split()) for part in self.topic_path]
        return self


class AssimilationPoint(_StrictModel):
    """One post-verification outcome for one persisted candidate."""

    candidate_id: str = Field(min_length=1, max_length=128)
    disposition: AssimilationDisposition
    matched_truth_handles: list[str] = Field(default_factory=list, max_length=8)
    canonical_title: str | None = Field(default=None, max_length=160)
    canonical_statement: str | None = Field(default=None, max_length=4000)
    topic_path: list[str] = Field(default_factory=list, max_length=8)
    knowledge_items: list[CanonicalKnowledgeItem] = Field(
        default_factory=list, max_length=3
    )
    reason: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def require_atomic_canonical_statement(self) -> "AssimilationPoint":
        target_count = len(self.matched_truth_handles)
        if self.knowledge_items:
            # Every item already carries the complete canonical shape. The
            # point-level fields are a redundant legacy projection, so dropping
            # them changes no knowledge semantics and keeps one write form.
            self.canonical_title = None
            self.canonical_statement = None
            self.topic_path = []
        if self.disposition == "add" and target_count:
            raise ValueError("add must not target current truth")
        if self.disposition in {"confirm", "refine", "supersede"} and target_count != 1:
            raise ValueError(
                f"{self.disposition} requires exactly one current truth handle"
            )
        if self.disposition == "conflict" and target_count > 1:
            raise ValueError("conflict may reference at most one current truth handle")
        if self.canonical_title:
            self.canonical_title = _assert_atomic_title(self.canonical_title)
        if self.canonical_statement:
            self.canonical_statement = validate_atomic_knowledge_statement(
                self.canonical_statement
            )
        return self


class AssimilationDecision(_StrictModel):
    """Strict, tool-free semantic decision over verified points and truth handles."""

    points: list[AssimilationPoint] = Field(default_factory=list, max_length=12)


class CandidateVerificationPoint(_StrictModel):
    """Semantic source-support and future-scope result for one extracted point."""

    candidate_index: int = Field(ge=0, le=11)
    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    reason: str = Field(min_length=8, max_length=1000)


class CandidateVerificationDecision(_StrictModel):
    """Complete per-point verification over bounded, content-addressed sources."""

    points: list[CandidateVerificationPoint] = Field(default_factory=list, max_length=12)


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
            raise ValueError(
                "zero_candidate_challenge is required when candidates is empty"
            )
        if self.candidates and challenge is not None:
            raise ValueError(
                "zero_candidate_challenge must be null when candidates exist"
            )
        return self


__all__ = [
    "AssimilationDecision",
    "CandidateVerificationDecision",
    "CandidateVerificationPoint",
    "AssimilationPoint",
    "CanonicalKnowledgeItem",
    "AutonomousDecision",
    "DistillCandidate",
    "SemanticReview",
    "VerificationRef",
    "ZeroCandidateChallenge",
]
