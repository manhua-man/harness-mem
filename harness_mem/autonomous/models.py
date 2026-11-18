"""Strict provider response models for autonomous distillation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator, model_serializer

from harness_mem.core.schemas.knowledge import ClaimKind
from harness_mem.core.schemas.evidence import EvidenceBasis, EvidenceRefKind
from harness_mem.core.schemas.source_report import (
    ReportOmission,
    ReportOutputProposal,
    ReportTopicJudgment,
    SourceReport,
    report_output_scope_text,
    report_preservation_digest,
    validate_report_preservation_inventory,
)
from harness_mem.knowledge_validation import validate_atomic_knowledge_statement


SourceUse = Literal[
    "standing_decision",
    "reusable_knowledge",
    "explicit_undecided",
    "task_context",
    "unclear",
]
DURABLE_SOURCE_USES = frozenset({
    "standing_decision",
    "reusable_knowledge",
    "explicit_undecided",
})


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

    @model_serializer(mode="wrap")
    def retain_older_optional_bytes(self, handler):
        payload = handler(self)
        for key in ("report_preservation", "report_original_classification", "report_preservation_inventory",
                    "report_topic_judgments"):
            if key in payload and payload[key] is None:
                payload.pop(key)
        return payload


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


class ReportRetainedSpan(_StrictModel):
    successor_index: int = Field(ge=0, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)
    text_sha256: str = Field(min_length=64, max_length=64)


class ReportUnitPreservation(_StrictModel):
    unit_index: int = Field(ge=0, strict=True)
    unit_sha256: str = Field(min_length=64, max_length=64)
    verdict: Literal["preserved", "disposable", "lost", "unclear"]
    successor_spans: list[ReportRetainedSpan]


class ReportOmissionPreservation(_StrictModel):
    omission_index: int = Field(ge=0, strict=True)
    omission_sha256: str = Field(min_length=64, max_length=64)
    affected_units: list[int]
    claim: Literal["preserved", "not_applicable", "lost", "unclear"]
    evidence: Literal["preserved", "not_applicable", "lost", "unclear"]
    causality: Literal["preserved", "not_applicable", "lost", "unclear"]
    boundary: Literal["preserved", "not_applicable", "lost", "unclear"]
    permission: Literal["preserved", "not_applicable", "lost", "unclear"]
    scope: Literal["preserved", "not_applicable", "lost", "unclear"]


class ReportPreservationJudgment(_StrictModel):
    owner_candidate_id: str
    inventory_sha256: str = Field(min_length=64, max_length=64)
    inventory_complete: bool = Field(strict=True)
    units: list[ReportUnitPreservation]
    omissions: list[ReportOmissionPreservation]


class UpdateMeaningJudgment(_StrictModel):
    """Whether one whole refine or replace keeps still-applicable meaning.

    The selected host executor or the current Agent supplies this judgment.
    Runtime code checks that ``successor_statements`` are exactly the output
    statements of the whole point, in order, that ``predecessor_statements``
    and ``predecessor_versions`` name the exact replaced rows, and that every
    named condition and undecided state occurs in those successor statements.
    A hash only freezes those bytes. It does not judge preservation, and
    neither does keyword overlap or support for each new sentence by itself.
    Omitting the judgment is not a claim that no condition applied.
    """

    relationship: Literal[
        "preserves_applicable_meaning",
        "drops_applicable_meaning",
        "unclear",
    ]
    predecessor_conditions: list[str] = Field(default_factory=list)
    predecessor_statements: list[str] = Field(default_factory=list)
    predecessor_versions: list[str] = Field(default_factory=list)
    undecided_state: str | None = None
    successor_statements: list[str] = Field(min_length=1)
    basis: str = Field(min_length=8, max_length=1000)
    report_preservation: ReportPreservationJudgment | None = None

    @field_validator("basis")
    @classmethod
    def single_line_basis(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("update meaning basis must be a nonempty single line")
        return value.strip()

    @field_validator("undecided_state")
    @classmethod
    def single_line_undecided(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("undecided state must be a nonempty single line")
        return value.strip()

    @field_validator("predecessor_conditions", "predecessor_statements", "predecessor_versions")
    @classmethod
    def single_line_items(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text or "\n" in text or "\r" in text:
                raise ValueError("update-meaning lines must be nonempty single lines")
            cleaned.append(text)
        return cleaned

    @field_validator("successor_statements")
    @classmethod
    def nonempty_statements(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value]
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("successor statements must be nonempty")
        return cleaned

    def agrees_with(self, other: "UpdateMeaningJudgment") -> bool:
        """Compare the complete verdict and bindings, retaining each rationale.

        Independent outputs may explain the same whole-update judgment in
        different words. Their relationship, ordered inventories, undecided
        state and exact predecessor/successor bindings must still all agree.
        This comparison does not establish either judgment's coverage.
        """
        return isinstance(other, UpdateMeaningJudgment) and (
            self.model_dump(exclude={"basis"}) == other.model_dump(exclude={"basis"})
        )

    def covers(self, statements: Sequence[str]) -> bool:
        cleaned = [str(item).strip() for item in statements]
        if self.relationship != "preserves_applicable_meaning":
            return False
        if list(self.successor_statements) != cleaned:
            return False
        combined = "\n".join(cleaned)
        if any(condition not in combined for condition in self.predecessor_conditions):
            return False
        if self.undecided_state and self.undecided_state not in combined:
            return False
        return True

    def binds_predecessors(self, predecessors: Sequence[Mapping[str, Any]]) -> bool:
        """Require the exact replaced statements and their current versions."""

        if not predecessors:
            return False
        statements: list[str] = []
        versions: list[str] = []
        for item in predecessors:
            if not isinstance(item, Mapping):
                return False
            statement = str(item.get("statement") or "").strip()
            version = str(item.get("version") or "").strip()
            if not statement or not version:
                return False
            statements.append(statement)
            versions.append(version)
        return (
            list(self.predecessor_statements) == statements
            and list(self.predecessor_versions) == versions
        )


class AssimilationPoint(_StrictModel):
    """One post-verification outcome for one persisted candidate."""

    candidate_id: str = Field(min_length=1, max_length=128)
    disposition: ProviderAssimilationDisposition
    matched_truth_handles: list[str] = Field(default_factory=list)
    canonical_title: str | None = Field(default=None)
    canonical_statement: str | None = Field(default=None)
    topic_path: list[str] = Field(default_factory=list)
    knowledge_items: list[CanonicalKnowledgeItem] = Field(default_factory=list)
    report_topic_judgment: ReportTopicJudgment | None = None
    report_topic_judgments: list[ReportTopicJudgment] | None = None
    report_outputs: list[ReportOutputProposal] = Field(default_factory=list)
    report_omissions: list[ReportOmission] = Field(default_factory=list)
    report_original_classification: SourceClassificationPoint | None = None
    retained_conditions: list[str] = Field(default_factory=list)
    undecided_state: str | None = Field(default=None, max_length=500)
    update_meaning_judgment: UpdateMeaningJudgment | None = None
    reason: str = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def require_atomic_canonical_statement(self) -> "AssimilationPoint":
        target_count = len(self.matched_truth_handles)
        if self.report_omissions and not self.report_outputs:
            raise ValueError("report omissions require retained report outputs")
        if self.report_outputs and self.disposition not in {"refine", "replace"}:
            raise ValueError("report outputs require a targeted refine or replace")
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


DREAM_LITERAL_EDIT_CONTRACT = "dream-existing-literal-edit-v1"
DREAM_LITERAL_RECHECK_CONTRACT = "dream-source-recheck-v7"
DREAM_SOURCE_RECHECK_CONTRACT = "dream-source-recheck-v16"


class CandidateScopeSegment(_StrictModel):
    """One verbatim claim segment and its independently judged future use."""

    text: str = Field(min_length=1)
    source_use: SourceUse
    future_scope: Literal["durable", "session_only", "unclear"]
    standalone: bool = False
    content_role: Literal["claim", "qualifier", "temporary_context", "unclear"] = "unclear"
    source_support: Literal["supported", "unsupported", "contradicted", "unclear"] = "unclear"


class SourceClaimUnit(_StrictModel):
    """Classify a substantive original range without proposing retained prose."""
    first_segment: int = Field(ge=0)
    end_segment_exclusive: int = Field(ge=1)
    standalone: bool = False
    source_support: Literal["supported", "unsupported", "contradicted", "unclear"] = "unclear"
    source_use: SourceUse = "unclear"
    future_scope: Literal["durable", "session_only", "unclear"] = "unclear"

    @model_validator(mode="after")
    def require_nonempty_source_range(self) -> "SourceClaimUnit":
        if self.end_segment_exclusive <= self.first_segment:
            raise ValueError("claim unit must select a nonempty contiguous segment range")
        return self


class CandidateClaimUnit(SourceClaimUnit):
    """Joint proof for an original range and its explicit literal projection.

    Segment indexes select an existing half-open range. Only the existing-edit
    contract permits checked exclusions. A unit never upgrades its segments.
    """

    excluded_segments: list[int] = Field(default_factory=list)
    retained_text: str = ""
    selected_for_retention: bool = False
    title_start: int | None = Field(default=None, ge=0)
    title_end: int | None = Field(default=None, ge=1)
    title_and_text_support: Literal[
        "supported", "unsupported", "contradicted", "unclear"
    ] = "unclear"

    @model_validator(mode="after")
    def require_nonempty_range(self) -> "CandidateClaimUnit":
        if (len(set(self.excluded_segments)) != len(self.excluded_segments)
                or any(index < self.first_segment or index >= self.end_segment_exclusive
                       for index in self.excluded_segments)):
            raise ValueError("excluded segment indexes must be unique and inside the unit range")
        if (self.title_start is None) != (self.title_end is None):
            raise ValueError("title substring requires both offsets or neither")
        if self.title_start is not None and self.title_end is not None:
            if not (self.title_start < self.title_end <= len(self.retained_text)):
                raise ValueError("title offsets must select a nonempty retained-text substring")
            title = self.retained_text[self.title_start:self.title_end]
            if not title or title != title.strip():
                raise ValueError("title substring must not contain leading or trailing whitespace")
        return self


class SourceClassificationPoint(_StrictModel):
    """Source support and complete claim inventory, with no edit-proof fields."""

    candidate_index: int = Field(ge=0)
    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    source_use: SourceUse = "unclear"
    reason: str = Field(min_length=8, max_length=1000)
    scope_segments: list[CandidateScopeSegment] = Field(default_factory=list)
    claim_units: list[SourceClaimUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def bind_inventory_ranges(self) -> "SourceClassificationPoint":
        if any(unit.end_segment_exclusive > len(self.scope_segments) for unit in self.claim_units):
            raise ValueError("claim unit extends beyond the supplied scope segments")
        return self


class SourceClassificationDecision(_StrictModel):
    """Native classification transport; it cannot express a proposed mutation."""

    points: list[SourceClassificationPoint] = Field(default_factory=list)

    def as_verification(self) -> "CandidateVerificationDecision":
        return CandidateVerificationDecision(points=[
            CandidateVerificationPoint.model_validate(point.model_dump(mode="json"))
            for point in self.points
        ])


class OutputVerification(_StrictModel):
    """Final title and body judgment for one written output.

    Dream copies this onto the shared final-scope contract. It is not a v7
    literal proof and it does not by itself admit a write.
    """

    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    source_use: SourceUse = "unclear"
    reason: str = Field(min_length=8, max_length=1000)
    scope_segments: list[CandidateScopeSegment] = Field(min_length=1)
    update_meaning_judgment: UpdateMeaningJudgment | None = None


class CandidateVerificationPoint(_StrictModel):
    """Semantic source-support and future-scope result for one extracted point."""

    candidate_index: int = Field(ge=0)
    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    source_use: SourceUse = "unclear"
    reason: str = Field(min_length=8, max_length=1000)
    scope_segments: list[CandidateScopeSegment] = Field(default_factory=list)
    claim_units: list[CandidateClaimUnit] = Field(default_factory=list)
    literal_edit_contract: Literal["dream-existing-literal-edit-v1"] | None = None
    update_meaning_judgment: UpdateMeaningJudgment | None = None
    report_outputs: list[ReportOutputProposal] = Field(default_factory=list)
    report_omissions: list[ReportOmission] = Field(default_factory=list)
    report_preservation_inventory: dict[str, Any] | None = None
    report_topic_judgments: list[ReportTopicJudgment] | None = None
    output_verifications: list[OutputVerification] = Field(default_factory=list)
    replacement_items: list[CanonicalKnowledgeItem] = Field(default_factory=list)
    replacement_target_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bind_future_scope_to_source_use(self) -> "CandidateVerificationPoint":
        """Retain point-level authority and bind units to the original partition."""
        if self.literal_edit_contract is not None and self.report_outputs:
            raise ValueError("v7 literal proofs cannot carry ordinary report outputs")
        if self.literal_edit_contract is not None and self.replacement_items:
            raise ValueError("v7 literal proofs cannot carry ordinary replacement outputs")
        for unit in self.claim_units:
            if unit.end_segment_exclusive > len(self.scope_segments):
                raise ValueError("claim unit extends beyond the supplied scope segments")
            if (unit.excluded_segments or unit.title_start is not None) and (
                    self.literal_edit_contract != DREAM_LITERAL_EDIT_CONTRACT):
                raise ValueError("literal exclusions and title edits require the existing-edit contract")
            selected = self.scope_segments[unit.first_segment:unit.end_segment_exclusive]
            projected = "".join(segment.text for index, segment in enumerate(
                selected, start=unit.first_segment) if index not in unit.excluded_segments).strip()
            if self.literal_edit_contract == DREAM_LITERAL_EDIT_CONTRACT or unit.retained_text:
                if not projected or unit.retained_text != projected:
                    raise ValueError("retained_text must exactly project the original selected segments")
            for index in unit.excluded_segments:
                segment = self.scope_segments[index]
                temporary = (segment.content_role == "temporary_context"
                    and segment.source_use == "task_context"
                    and segment.future_scope == "session_only"
                    and segment.source_support == "supported")
                unsupported = (self.semantic_support == "partial"
                    and segment.source_support in {"unsupported", "contradicted"}
                    and segment.content_role in {"claim", "qualifier"})
                if not temporary and not unsupported:
                    raise ValueError("literal exclusion requires proved temporary or unsupported text")
            if (unit.selected_for_retention or self.literal_edit_contract is not None) and any(
                    segment.content_role == "temporary_context" for index, segment in
                    enumerate(selected, start=unit.first_segment)
                    if index not in unit.excluded_segments):
                raise ValueError("claim unit cannot bridge a temporary-context segment")
        if self.source_use == "task_context":
            self.future_scope = "session_only"
        elif self.source_use == "unclear":
            self.future_scope = "unclear"
        return self


class CandidateVerificationDecision(_StrictModel):
    """Complete per-point verification over bounded, content-addressed sources."""

    points: list[CandidateVerificationPoint] = Field(default_factory=list)
    _source_coverage_audit: dict[str, Any] | None = PrivateAttr(default=None)


class NativeFinalStatementSpan(_StrictModel):
    """A half-open Unicode-character range in one owner's final statement."""

    successor_index: int = Field(ge=0, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def nonempty_range(self) -> "NativeFinalStatementSpan":
        if self.char_end <= self.char_start:
            raise ValueError("final condition range must be nonempty and ordered")
        return self


class NativeReportUnitPreservation(_StrictModel):
    unit_index: int = Field(ge=0, strict=True)
    verdict: Literal["preserved", "disposable", "lost", "unclear"]
    successor_spans: list[NativeFinalStatementSpan]


class NativeReportOmissionPreservation(_StrictModel):
    omission_index: int = Field(ge=0, strict=True)
    claim: Literal["preserved", "not_applicable", "lost", "unclear"]
    evidence: Literal["preserved", "not_applicable", "lost", "unclear"]
    causality: Literal["preserved", "not_applicable", "lost", "unclear"]
    boundary: Literal["preserved", "not_applicable", "lost", "unclear"]
    permission: Literal["preserved", "not_applicable", "lost", "unclear"]
    scope: Literal["preserved", "not_applicable", "lost", "unclear"]


class NativeReportPreservation(_StrictModel):
    inventory_complete: bool = Field(strict=True)
    units: list[NativeReportUnitPreservation]
    omissions: list[NativeReportOmissionPreservation]


class NativeFinalUpdateMeaning(_StrictModel):
    """Independent meaning vote; endpoint text is owned by the request."""

    relationship: Literal["preserves_applicable_meaning", "drops_applicable_meaning", "unclear"]
    inventory_complete: bool = Field(strict=True)
    condition_spans: list[NativeFinalStatementSpan]
    undecided_span: NativeFinalStatementSpan | None
    basis: str = Field(min_length=8, max_length=1000)
    report_preservation: NativeReportPreservation | None = None

    @field_validator("basis")
    @classmethod
    def single_line_basis(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("native meaning basis must be a nonempty single line")
        return value.strip()


class NativeFinalScopePoint(_StrictModel):
    """Native final-only verdict, without free-text proof or mutation fields."""

    candidate_index: int = Field(ge=0, strict=True)
    semantic_support: Literal["supported", "partial", "contradicted"]
    future_scope: Literal["durable", "session_only", "unclear"]
    source_use: SourceUse
    reason: str = Field(min_length=8, max_length=1000)
    scope_segments: list[CandidateScopeSegment] = Field(min_length=1)
    update_meaning_judgment: NativeFinalUpdateMeaning | None
    report_topic_judgments: list[ReportTopicJudgment] | None = None


class NativeFinalScopeDecision(_StrictModel):
    """Native final transport expanded only against its exact bound request.

    Projection supplies no semantic verdict: each output's independent model
    inventory and vote remain subject to the existing complete shared gates.
    """

    points: list[NativeFinalScopePoint]

    def as_verification(self, manifest: Mapping[str, Any], *,
                        isolate_invalid_points: bool = False) -> CandidateVerificationDecision:
        """Bind exact proofs; optionally reject malformed proof points locally.

        Candidate identity, bound output headers and update ownership remain
        strict for the whole response. The explicit adapter mode can preserve
        an independent valid point, but cannot salvage any part of a bad proof.
        """
        if manifest.get("contract_version") != "final-knowledge-scope-v1":
            raise ValueError("native final proof requires the exact final-scope contract")
        candidates = manifest.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("native final proof requires bound candidate rows")
        by_index: dict[int, Mapping[str, Any]] = {}
        by_owner: dict[str, list[Mapping[str, Any]]] = {}
        for row in candidates:
            if not isinstance(row, Mapping):
                raise ValueError("native final proof has an invalid bound row")
            index = row.get("candidate_index")
            owner = row.get("owner_candidate_id")
            if type(index) is not int or index < 0 or index in by_index:
                raise ValueError("native final proof has invalid or duplicate bound indexes")
            if not isinstance(owner, str) or not owner.strip():
                raise ValueError("native final proof requires a bound owner")
            title, statement = row.get("title"), row.get("statement")
            if not isinstance(title, str) or not isinstance(statement, str) or not statement.strip():
                raise ValueError("native final proof requires exact title and statement strings")
            report = row.get("source_report")
            if report is not None:
                parsed = SourceReport.model_validate(report)
                if title != parsed.render_title() or statement != parsed.render_statement():
                    raise ValueError("native final report row does not match its typed authority")
                scope = report_output_scope_text(parsed)
            else:
                scope = title + "\n" + statement
            if row.get("scope_text") != scope:
                raise ValueError("native final scope does not match its bound output")
            by_index[index] = row
            by_owner.setdefault(owner, []).append(row)
        indexes = [point.candidate_index for point in self.points]
        if len(indexes) != len(set(indexes)) or set(indexes) != set(by_index):
            raise ValueError("native final proof must cover each bound output exactly once")

        contexts: dict[str, Mapping[str, Any] | None] = {}
        for owner, rows in by_owner.items():
            context = rows[0].get("update_context")
            if any(row.get("update_context") != context for row in rows[1:]):
                raise ValueError("native final owner has inconsistent whole-update contexts")
            if context is None:
                contexts[owner] = None
                continue
            if (not isinstance(context, Mapping) or context.get("owner_candidate_id") != owner
                    or context.get("disposition") not in {"refine", "replace", "add"}):
                raise ValueError("native final proof has invalid whole-update ownership")
            predecessors, successors = context.get("predecessors"), context.get("successors")
            adding = context["disposition"] == "add"
            if (not isinstance(predecessors, list) or (bool(predecessors) if adding else not predecessors)
                    or not isinstance(successors, list) or len(successors) != len(rows)):
                raise ValueError("native final proof requires complete predecessor and successor inventories")
            if adding:
                retained = context.get("retained_conditions")
                undecided = context.get("undecided_state")
                if (not isinstance(retained, list)
                        or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                               or "\n" in item or "\r" in item for item in retained)
                        or (undecided is not None and (
                            not isinstance(undecided, str) or not undecided.strip()
                            or undecided != undecided.strip() or "\n" in undecided or "\r" in undecided))):
                    raise ValueError("native final add requires exact declared condition obligations")
            predecessor_ids = []
            for target in predecessors:
                if not isinstance(target, Mapping) or any(
                    not isinstance(target.get(key), str) or not target[key].strip()
                    for key in ("id", "statement", "version")
                ):
                    raise ValueError("native final proof has incomplete predecessor identity")
                predecessor_ids.append(target["id"])
            if len(predecessor_ids) != len(set(predecessor_ids)):
                raise ValueError("native final proof has duplicate predecessor identity")
            for row, output in zip(rows, successors):
                if not isinstance(output, Mapping) or any(
                    row.get(key) != output.get(key) for key in ("title", "statement", "source_report")
                ):
                    raise ValueError("native final output does not match the ordered whole-update successors")
            contexts[owner] = context

        def literal(span: NativeFinalStatementSpan, statements: list[str]) -> str:
            if span.successor_index >= len(statements):
                raise ValueError("native final span references an unavailable successor")
            text = statements[span.successor_index]
            if span.char_end > len(text):
                raise ValueError("native final span extends beyond its exact successor statement")
            value = text[span.char_start:span.char_end]
            if not value or value != value.strip() or "\n" in value or "\r" in value:
                raise ValueError("native final span is not an exact canonical single-line condition")
            return value

        def expand(point: NativeFinalScopePoint) -> CandidateVerificationPoint:
            row = by_index[point.candidate_index]
            context = contexts[row["owner_candidate_id"]]
            native = point.update_meaning_judgment
            judgment = None
            if native is not None:
                if context is None:
                    raise ValueError("native final meaning proof has no bound update context")
                statements = [item["statement"] for item in context["successors"]]
                # Validate every submitted range, even for incomplete or negative
                # votes. Never ignore a malformed range to salvage acceptance.
                conditions = [literal(span, statements) for span in native.condition_spans]
                undecided = literal(native.undecided_span, statements) if native.undecided_span is not None else None
                if native.inventory_complete:
                    if context["disposition"] == "add" and (
                        (context["retained_conditions"] and conditions != context["retained_conditions"])
                        or (context["undecided_state"] is not None and undecided != context["undecided_state"])
                    ):
                        raise ValueError("native final add proof omits or changes declared condition obligations")
                    preservation = None
                    original = context.get("report_preservation_inventory")
                    if original is not None:
                        validate_report_preservation_inventory(original, owner=row["owner_candidate_id"],
                            targets=context["predecessors"], items=context["successors"])
                        vote = native.report_preservation
                        if vote is not None:
                            if ([item.unit_index for item in vote.units] != list(range(len(original["units"])))
                                    or [item.omission_index for item in vote.omissions] != list(range(len(original["omissions"])))):
                                raise ValueError("native final report preservation must cover the complete original inventory")
                            unit_votes = []
                            for item, bound in zip(vote.units, original["units"]):
                                spans = []
                                for span in item.successor_spans:
                                    bodies = [SourceReport.model_validate(output["source_report"]).text
                                              for output in context["successors"]]
                                    value = literal(span, bodies)
                                    import hashlib
                                    spans.append({**span.model_dump(mode="json"),
                                        "text_sha256": hashlib.sha256(value.encode()).hexdigest()})
                                unit_votes.append({"unit_index": item.unit_index,
                                    "unit_sha256": report_preservation_digest(bound), "verdict": item.verdict,
                                    "successor_spans": spans})
                            preservation = ReportPreservationJudgment(
                                owner_candidate_id=row["owner_candidate_id"],
                                inventory_sha256=report_preservation_digest(original),
                                inventory_complete=vote.inventory_complete, units=unit_votes,
                                omissions=[{**item.model_dump(mode="json"),
                                    "omission_sha256": report_preservation_digest(bound),
                                    "affected_units": list(bound["affected_units"])}
                                    for item, bound in zip(vote.omissions, original["omissions"])])
                    elif native.report_preservation is not None:
                        raise ValueError("native final report preservation has no bound original inventory")
                    judgment = UpdateMeaningJudgment(
                        relationship=native.relationship, predecessor_conditions=conditions,
                        predecessor_statements=[item["statement"] for item in context["predecessors"]],
                        predecessor_versions=[item["version"] for item in context["predecessors"]],
                        successor_statements=statements, undecided_state=undecided, basis=native.basis,
                        report_preservation=preservation,
                    )
            return CandidateVerificationPoint(
                candidate_index=point.candidate_index, semantic_support=point.semantic_support,
                future_scope=point.future_scope, source_use=point.source_use, reason=point.reason,
                scope_segments=[segment.model_copy(deep=True) for segment in point.scope_segments],
                update_meaning_judgment=judgment,
                report_topic_judgments=point.report_topic_judgments,
            )

        points = []
        for point in self.points:
            try:
                verified = expand(point)
            except ValueError:
                if not isolate_invalid_points:
                    raise
                # This rejects only the submitted proof. It makes no claim
                # that the original source contradicts the proposed content.
                # Keep no positive scope or meaning from a malformed point.
                verified = CandidateVerificationPoint(
                    candidate_index=point.candidate_index, semantic_support="partial",
                    future_scope="unclear", source_use="unclear",
                    reason="native_final_point_proof_invalid: submitted proof does not bind the exact final output.",
                    scope_segments=[], update_meaning_judgment=None,
                )
            points.append(verified)
        return CandidateVerificationDecision(points=points)


def verification_scope_status(point: CandidateVerificationPoint, statement: str) -> str:
    """Require every character and every classified claim to share durable use."""
    parts = point.scope_segments
    if not parts:
        return "source_scope_partition_missing"
    if "".join(part.text for part in parts) != statement:
        return "source_scope_partition_mismatch"
    if (point.literal_edit_contract is not None
            or any(unit.excluded_segments or unit.title_start is not None
                   for unit in point.claim_units)):
        # Only the source-bound existing-entry maintenance owner may interpret
        # this proof. Normal initial/final verification must not admit edits.
        return "source_scope_existing_edit_only"
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
    _source_coverage_inventory: dict[str, Any] | None = PrivateAttr(default=None)

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


SOURCE_COVERAGE_INVENTORY_CONTRACT = "dream-applied-source-coverage-v5"


class SourceCoverageRange(_StrictModel):
    """Half-open Unicode-character offsets in an exact authored-user window."""

    w: int = Field(ge=0, strict=True)
    s: int = Field(ge=0, strict=True)
    e: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def ordered_range(self) -> "SourceCoverageRange":
        if self.e <= self.s:
            raise ValueError("source coverage range must be nonempty")
        return self


class SourceCoverageCorrectionRange(_StrictModel):
    """A later independently reopened authored-user source, outside old windows."""

    context_sha256: str = Field(min_length=64, max_length=64)
    exchange_index: int = Field(ge=1, strict=True)
    message_index: int = Field(ge=0, strict=True)
    content_sha256: str = Field(min_length=64, max_length=64)
    s: int = Field(ge=0, strict=True)
    e: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def ordered_range(self) -> "SourceCoverageCorrectionRange":
        if self.e <= self.s:
            raise ValueError("source correction range must be nonempty")
        return self


class SourceCoverageSpan(_StrictModel):
    """A disposition and indexed links; no source prose or mutation handles."""

    s: int = Field(ge=0, strict=True)
    e: int = Field(ge=1, strict=True)
    d: Literal["extract", "covered", "superseded", "temporary", "out_of_task", "unclear"]
    p: list[int] = Field(default_factory=list)
    c: list[int] = Field(default_factory=list)
    r: list[SourceCoverageRange | SourceCoverageCorrectionRange] = Field(default_factory=list)

    @field_validator("p", "c", mode="before")
    @classmethod
    def exact_indexes(cls, value: Any) -> Any:
        if not isinstance(value, list) or any(type(item) is not int or item < 0 for item in value):
            raise ValueError("source coverage indexes must be strict nonnegative integers")
        if len(set(value)) != len(value):
            raise ValueError("source coverage indexes must be unique")
        return value


class SourceCoverageWindow(_StrictModel):
    w: int = Field(ge=0, strict=True)
    spans: list[SourceCoverageSpan]


class NativeSourceCoverageExtractionPoint(AgentExtractionPoint):
    """V5 discovers only authored user statements, never attributed reports."""

    evidence_basis: Literal["user_statement"]
    report_role: None = None
    repository_locator: None = None
    repository_sha256: None = None


class NativeSourceCoverageCandidateReview(AgentExtractionReview):
    no_candidate_reason: None = None
    not_durable_signals: list[MemorySignal] = Field(default_factory=list, max_length=0)


class NativeSourceCoverageEmptyReview(AgentExtractionReview):
    no_candidate_reason: str = Field(min_length=24, max_length=4000)


class NativeSourceCoverageCandidateExtraction(AgentExtractionDecision):
    review: NativeSourceCoverageCandidateReview
    points: list[NativeSourceCoverageExtractionPoint] = Field(min_length=1)


class NativeSourceCoverageEmptyExtraction(AgentExtractionDecision):
    review: NativeSourceCoverageEmptyReview
    points: list[NativeSourceCoverageExtractionPoint] = Field(default_factory=list, max_length=0)


class NativeSourceCoverageExtractionDecision(_StrictModel):
    """V5 wire envelope makes candidate and no-candidate shapes exclusive."""

    extraction: NativeSourceCoverageCandidateExtraction | NativeSourceCoverageEmptyExtraction
    inventory: list[SourceCoverageWindow]

    @model_validator(mode="before")
    @classmethod
    def wrap_legacy_private_shape(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "extraction" not in value and (
                "review" in value or "points" in value):
            wrapped = dict(value)
            wrapped["extraction"] = {key: wrapped.pop(key) for key in ("review", "points") if key in wrapped}
            return wrapped
        return value

    @property
    def review(self) -> AgentExtractionReview:
        return self.extraction.review

    @property
    def points(self) -> list[NativeSourceCoverageExtractionPoint]:
        return self.extraction.points


class SourceCoverageSpanPatch(_StrictModel):
    """Replace one unresolved original span without rewriting retained audits."""

    w: int = Field(ge=0, strict=True)
    span_index: int = Field(ge=0, strict=True)
    spans: list[SourceCoverageSpan] = Field(min_length=1)


class NativeResidualSourceCoverageExtractionDecision(_StrictModel):
    extraction: NativeSourceCoverageCandidateExtraction | NativeSourceCoverageEmptyExtraction
    patches: list[SourceCoverageSpanPatch]

    @property
    def review(self) -> AgentExtractionReview:
        return self.extraction.review

    @property
    def points(self) -> list[NativeSourceCoverageExtractionPoint]:
        return self.extraction.points


class SourceCoverageAuditPoint(_StrictModel):
    w: int = Field(ge=0, strict=True)
    span_index: int = Field(ge=0, strict=True)
    verdict: Literal["supported", "unclear", "contradicted"]


class SourceCoverageVerificationPoint(SourceClassificationPoint):
    candidate_index: int = Field(ge=0, strict=True)


class NativeSourceCoverageVerificationDecision(_StrictModel):
    """The existing candidate verification also audits every extraction span."""

    points: list[SourceCoverageVerificationPoint]
    audit: list[SourceCoverageAuditPoint]


AssimilationPoint.model_rebuild()
AssimilationDecision.model_rebuild()


__all__ = [
    "SOURCE_COVERAGE_INVENTORY_CONTRACT",
    "NativeSourceCoverageExtractionPoint",
    "NativeSourceCoverageExtractionDecision",
    "NativeResidualSourceCoverageExtractionDecision",
    "NativeSourceCoverageVerificationDecision",
    "SourceCoverageWindow",
    "DREAM_LITERAL_EDIT_CONTRACT",
    "DREAM_LITERAL_RECHECK_CONTRACT",
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
