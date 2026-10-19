"""Strict provider response models for autonomous distillation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness_mem.core.schemas.knowledge import ClaimKind
from harness_mem.core.schemas.evidence import EvidenceBasis, EvidenceRefKind
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement


ProviderAssimilationDisposition = Literal[
    "add",
    "refine",
    "confirm",
    "replace",
    "no_write",
    "handoff",
    "defer",
    "conflict",
    "reject",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationRef(_StrictModel):
    kind: EvidenceRefKind
    content_sha256: str = Field(min_length=64, max_length=64)
    exchange_index: int | None = Field(default=None, ge=1)
    role: Literal["user", "assistant"] | None = None
    chunk_index: int | None = Field(default=None, ge=0)
    locator: str | None = Field(default=None, max_length=4096)


class _CandidateBase(_StrictModel):
    evidence_basis: EvidenceBasis
    # Extraction proposes a claim; the trusted second pass decides whether it
    # is verified. Keep the field only as an input-compatibility default.
    verification_outcome: Literal["verified", "unverified", "contradicted"] = (
        "unverified"
    )
    verification_refs: list[VerificationRef] = Field(default_factory=list)
    verification_reason_codes: list[str] = Field(default_factory=list)


def _assert_atomic_title(value: str) -> str:
    """Normalize titles; punctuation cannot establish semantic atomicity."""

    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("knowledge title must not be empty")
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
    content: str | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = Field(default=None)
    pattern: str | None = Field(default=None, max_length=2000)
    trigger: str | None = Field(default=None, max_length=1000)
    examples: list[str] | None = Field(default=None)
    source_entity: str | None = Field(default=None, max_length=200)
    target_entity: str | None = Field(default=None, max_length=200)
    relation_type: str | None = Field(default=None, max_length=100)
    evidence: str | None = Field(default=None, max_length=2000)


class CanonicalKnowledgeItem(_StrictModel):
    """One proposed knowledge item created by a single point disposition.

    The provider schema validates shape only. The Agent judges semantic scope
    and specificity against the verified candidate; runtime checks source
    integrity and the resulting write, not words or punctuation quotas.
    """

    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    topic_path: list[str] = Field(min_length=1)
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
    disposition: ProviderAssimilationDisposition
    matched_truth_handles: list[str] = Field(default_factory=list)
    canonical_title: str | None = Field(default=None)
    canonical_statement: str | None = Field(default=None)
    topic_path: list[str] = Field(default_factory=list)
    knowledge_items: list[CanonicalKnowledgeItem] = Field(default_factory=list)
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
        if self.disposition == "confirm" and target_count != 1:
            raise ValueError(
                "confirm requires exactly one current truth handle"
            )
        if self.disposition in {"refine", "replace"} and target_count < 1:
            raise ValueError(
                f"{self.disposition} requires at least one current truth handle"
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
    """Strict semantic decision over verified points and truth handles."""

    points: list[AssimilationPoint] = Field(default_factory=list)


class CandidateScopeSegment(_StrictModel):
    """One verbatim claim segment and its independently judged future use."""

    text: str = Field(min_length=1)
    source_use: Literal["standing_decision", "reusable_knowledge", "task_context", "unclear"]
    future_scope: Literal["durable", "session_only", "unclear"]
    standalone: bool = False
    content_role: Literal["claim", "qualifier", "temporary_context", "unclear"] = "unclear"
    source_support: Literal["supported", "unsupported", "contradicted", "unclear"] = "unclear"


class CandidateClaimUnit(_StrictModel):
    """Joint proof for one original contiguous claim including necessary qualifiers.

    Segment indexes select an existing half-open range. A unit does not upgrade
    any individual segment's standalone, support, source use or future scope.
    """

    first_segment: int = Field(ge=0)
    end_segment_exclusive: int = Field(ge=1)
    standalone: bool = False
    source_support: Literal["supported", "unsupported", "contradicted", "unclear"] = "unclear"
    source_use: Literal[
        "standing_decision", "reusable_knowledge", "task_context", "unclear"
    ] = "unclear"
    future_scope: Literal["durable", "session_only", "unclear"] = "unclear"

    @model_validator(mode="after")
    def require_nonempty_range(self) -> "CandidateClaimUnit":
        if self.end_segment_exclusive <= self.first_segment:
            raise ValueError("claim unit must select a nonempty contiguous segment range")
        return self


class CandidateVerificationPoint(_StrictModel):
    """Semantic source-support and future-scope result for one extracted point."""

    candidate_index: int = Field(ge=0)
    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    source_use: Literal[
        "standing_decision", "reusable_knowledge", "task_context", "unclear"
    ] = "unclear"
    reason: str = Field(min_length=8, max_length=1000)
    scope_segments: list[CandidateScopeSegment] = Field(default_factory=list)
    claim_units: list[CandidateClaimUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def bind_future_scope_to_source_use(self) -> "CandidateVerificationPoint":
        """Retain point-level authority and bind units to the original partition."""
        for unit in self.claim_units:
            if unit.end_segment_exclusive > len(self.scope_segments):
                raise ValueError("claim unit extends beyond the supplied scope segments")
            if any(segment.content_role == "temporary_context" for segment in
                    self.scope_segments[unit.first_segment:unit.end_segment_exclusive]):
                raise ValueError("claim unit cannot bridge a temporary-context segment")
        if self.source_use == "task_context":
            self.future_scope = "session_only"
        elif self.source_use == "unclear":
            self.future_scope = "unclear"
        return self


class CandidateVerificationDecision(_StrictModel):
    """Complete per-point verification over bounded, content-addressed sources."""

    points: list[CandidateVerificationPoint] = Field(default_factory=list)


def verification_scope_status(point: CandidateVerificationPoint, statement: str) -> str:
    """Require every character and every classified claim to share durable use."""
    parts = point.scope_segments
    if not parts:
        return "source_scope_partition_missing"
    if "".join(part.text for part in parts) != statement:
        return "source_scope_partition_mismatch"
    if point.semantic_support == "supported" and (
        any(part.text.strip() and part.source_support != "supported" for part in parts)
        or any(unit.source_support != "supported" for unit in point.claim_units)
    ):
        # The whole-point vote cannot overrule an unknown or unsupported clause.
        # This shared gate covers initial admission, final-plan verification and
        # Dream confirmation without upgrading any partial point.
        return "source_scope_support_inconsistent"
    scopes: set[str] = set()
    for part in parts:
        if part.content_role == "unclear":
            scopes.add("unclear")
        elif (part.content_role == "temporary_context"
              or part.source_use == "task_context" or part.future_scope == "session_only"):
            scopes.add("session_only")
        elif part.source_use == "unclear" or part.future_scope == "unclear":
            scopes.add("unclear")
        else:
            scopes.add("durable")
    for unit in point.claim_units:
        if unit.source_use == "unclear" or unit.future_scope == "unclear":
            scopes.add("unclear")
        elif unit.source_use == "task_context" or unit.future_scope == "session_only":
            scopes.add("session_only")
        else:
            scopes.add("durable")
    if "unclear" in scopes:
        return "source_scope_unclear"
    if len(scopes) != 1:
        return "source_scope_mixed"
    return "source_scope_" + next(iter(scopes))


ChallengeChecks = Literal["absent", "not_durable", "candidate_required"]
MemorySignal = Literal[
    "user_correction",
    "explicit_decision",
    "successful_solution",
    "repeated_failure",
    "rule_or_preference",
    "reusable_workflow_or_fact",
    "version_or_migration",
    "unfinished_handoff",
]


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
    contradictions: list[str] = Field(default_factory=list)
    unfinished_work: list[str] = Field(default_factory=list)
    evidence_status: Literal["answered", "partial", "contradicted", "not_applicable"]
    promotion_decision: Literal["promote", "partial", "no_promotion", "blocked"]
    zero_candidate_challenge: ZeroCandidateChallenge | None = None


class AutonomousDecision(_StrictModel):
    semantic_review: SemanticReview
    candidates: list[DistillCandidate] = Field(default_factory=list)

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


class AgentExtractionReview(_StrictModel):
    """Small semantic review returned by a host Agent.

    Status fields and zero-candidate proof are derived by the trusted runtime
    from this review and the prepared manifest. The Agent does not echo them.
    """

    summary: str = Field(min_length=12, max_length=4000)
    final_request: str = Field(min_length=1, max_length=4000)
    actual_result: str = Field(min_length=1, max_length=4000)
    contradictions: list[str] = Field(default_factory=list)
    unfinished: list[str] = Field(default_factory=list)
    no_candidate_reason: str | None = Field(default=None, min_length=24, max_length=4000)
    not_durable_signals: list[MemorySignal] = Field(default_factory=list)

    @field_validator("contradictions", "unfinished", mode="before")
    @classmethod
    def wrap_single_text_item(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return [normalized] if normalized else []
        return value


class AgentExtractionPoint(_StrictModel):
    """One compact discovery point plus a source location.

    Category, confidence, tags, verification state, and content hashes are
    runtime-owned or derived from the prepared source. They are deliberately
    absent from the Agent response.
    """

    kind: Literal["memory", "rule", "relation"]
    statement: str = Field(min_length=1)
    condition: str | None = Field(default=None, max_length=1000)
    source_entity: str | None = Field(default=None, max_length=200)
    target_entity: str | None = Field(default=None, max_length=200)
    relation_type: str | None = Field(default=None, max_length=100)
    evidence_basis: EvidenceBasis
    report_role: Literal["user", "assistant"] | None = None
    exchange_indexes: list[int] = Field(default_factory=list)
    repository_locator: str | None = Field(default=None, max_length=4096)
    repository_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def require_kind_and_source_fields(self) -> "AgentExtractionPoint":
        if self.evidence_basis == "source_report":
            if self.report_role is None or self.kind != "memory":
                raise ValueError("source_report requires a speaker role and kind=memory")
        elif self.report_role is not None:
            raise ValueError("report_role belongs only to a source_report")
        if self.kind == "rule" and not str(self.condition or "").strip():
            raise ValueError("rule point requires condition")
        if self.kind == "relation" and not all(
            str(value or "").strip()
            for value in (self.source_entity, self.target_entity, self.relation_type)
        ):
            raise ValueError(
                "relation point requires source_entity, target_entity, and relation_type"
            )
        if self.evidence_basis in {"user_statement", "transcript", "source_report"}:
            if not self.exchange_indexes or any(index < 1 for index in self.exchange_indexes):
                raise ValueError("session evidence requires one-based exchange_indexes")
        elif not self.repository_locator or not self.repository_sha256:
            raise ValueError("repository evidence requires locator and sha256")
        return self


class AgentExtractionDecision(_StrictModel):
    """Minimal host-Agent output expanded into ``AutonomousDecision`` locally."""

    review: AgentExtractionReview
    points: list[AgentExtractionPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_no_candidate_reason(self) -> "AgentExtractionDecision":
        if self.points and self.review.no_candidate_reason is not None:
            raise ValueError("no_candidate_reason must be null when points exist")
        if not self.points and self.review.no_candidate_reason is None:
            raise ValueError("no_candidate_reason is required when points is empty")
        if self.points and self.review.not_durable_signals:
            raise ValueError("not_durable_signals must be empty when points exist")
        return self


__all__ = [
    "AgentExtractionDecision",
    "AgentExtractionPoint",
    "AgentExtractionReview",
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
