"""Schemas for current knowledge and its bounded supporting records.

``KnowledgeEntry`` is the small, durable row used by normal retrieval. Source
revalidation and undo snapshots are separate records so processing metadata
never leaks into the knowledge body or its embedding text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.core.schemas.evidence import EvidenceBasis, EvidenceRef, VerificationOutcome


KnowledgeCandidateStatus = Literal[
    "pending", "deferred", "conflict", "rejected", "assimilated"
]
KnowledgeCandidateType = Literal["memory", "rule", "relation"]
ClaimKind = Literal[
    "design_requirement",
    "implementation_fact",
    "durable_preference",
    "procedure",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _deserialize_datetimes(data: dict, *names: str) -> dict:
    normalized = dict(data)
    for name in names:
        value = normalized.get(name)
        if isinstance(value, str):
            normalized[name] = datetime.fromisoformat(value)
    return normalized


def _single_line(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError(f"{field_name} must be a single line")
    return normalized


class KnowledgeEntry(BaseModel):
    """One current, independently retrievable project-knowledge statement."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str = Field(min_length=1)
    module_path: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    verified_at: datetime | None = None
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    @field_validator("project_name", "title", "statement")
    @classmethod
    def normalize_single_line(cls, value: str, info) -> str:
        return _single_line(value, field_name=info.field_name)

    @field_validator("module_path")
    @classmethod
    def normalize_module_path(cls, value: list[str]) -> list[str]:
        return [_single_line(part, field_name="module_path") for part in value]

    def to_dict(self) -> dict:
        """Return the complete persistence payload, including hidden controls."""

        return {
            "id": self.id,
            "project_name": self.project_name,
            "module_path": list(self.module_path),
            "title": self.title,
            "statement": self.statement,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "revision": self.revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEntry":
        normalized = _deserialize_datetimes(
            data, "verified_at", "created_at", "updated_at"
        )
        # Read rows from the abandoned Markdown-authority worktree long enough
        # to rewrite them in the clean shape. New writes never emit these keys.
        if "module_path" not in normalized and "topic_path" in normalized:
            normalized["module_path"] = normalized.pop("topic_path")
        for obsolete in ("source_refs", "claim_kind", "validity"):
            normalized.pop(obsolete, None)
        normalized.setdefault("revision", 1)
        return cls(**normalized)


class KnowledgeSource(BaseModel):
    """Minimal locator used to revalidate one current knowledge statement."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    knowledge_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    content_sha256: str | None = None
    verified_at: datetime

    model_config = {"extra": "forbid"}

    @field_validator("knowledge_id", "project_name", "source_kind", "locator")
    @classmethod
    def normalize_single_line(cls, value: str, info) -> str:
        return _single_line(value, field_name=info.field_name)

    @field_validator("content_sha256")
    @classmethod
    def normalize_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("content_sha256 must be 64 hexadecimal characters")
        return normalized

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "knowledge_id": self.knowledge_id,
            "project_name": self.project_name,
            "source_kind": self.source_kind,
            "locator": self.locator,
            "content_sha256": self.content_sha256,
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeSource":
        return cls(**_deserialize_datetimes(data, "verified_at"))


class KnowledgeVersion(BaseModel):
    """Bounded snapshot of a previous knowledge revision for Review undo."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    knowledge_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    revision: int = Field(ge=1)
    module_path: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    verified_at: datetime | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    @field_validator("knowledge_id", "project_name", "title", "statement")
    @classmethod
    def normalize_single_line(cls, value: str, info) -> str:
        return _single_line(value, field_name=info.field_name)

    @field_validator("module_path")
    @classmethod
    def normalize_module_path(cls, value: list[str]) -> list[str]:
        return [_single_line(part, field_name="module_path") for part in value]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "knowledge_id": self.knowledge_id,
            "project_name": self.project_name,
            "revision": self.revision,
            "module_path": list(self.module_path),
            "title": self.title,
            "statement": self.statement,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "sources": [source.to_dict() for source in self.sources],
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeVersion":
        normalized = _deserialize_datetimes(data, "verified_at", "recorded_at")
        normalized["sources"] = [
            source
            if isinstance(source, KnowledgeSource)
            else KnowledgeSource.from_dict(source)
            for source in normalized.get("sources") or []
        ]
        return cls(**normalized)


class KnowledgeMutation(BaseModel):
    """Minimal durable lineage required to validate and reverse one mutation."""

    id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    disposition: Literal["add", "refine", "supersede"]
    current_knowledge_ids: list[str] = Field(default_factory=list)
    predecessor_version_ids: list[str] = Field(default_factory=list)
    reverses_mutation_id: str | None = None
    recorded_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    @field_validator("id", "project_name")
    @classmethod
    def normalize_required_line(cls, value: str, info) -> str:
        return _single_line(value, field_name=info.field_name)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "disposition": self.disposition,
            "current_knowledge_ids": list(self.current_knowledge_ids),
            "predecessor_version_ids": list(self.predecessor_version_ids),
            "reverses_mutation_id": self.reverses_mutation_id,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeMutation":
        return cls(**_deserialize_datetimes(data, "recorded_at"))


class KnowledgeCandidate(BaseModel):
    """A proposed point that has not become current project knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    candidate_type: KnowledgeCandidateType
    statement: str = Field(min_length=1)
    status: KnowledgeCandidateStatus = "pending"
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "candidate_type": self.candidate_type,
            "statement": self.statement,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeCandidate":
        return cls(**_deserialize_datetimes(data, "created_at", "updated_at"))


class KnowledgeEvidence(BaseModel):
    """Job-scoped verification material for one proposed knowledge point."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    candidate_id: str
    distill_job_id: str | None = None
    evidence_basis: EvidenceBasis
    verification_outcome: VerificationOutcome
    verification_refs: list[EvidenceRef] = Field(default_factory=list)
    verification_reason_codes: list[str] = Field(default_factory=list)
    verified_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "candidate_id": self.candidate_id,
            "distill_job_id": self.distill_job_id,
            "evidence_basis": self.evidence_basis,
            "verification_outcome": self.verification_outcome,
            "verification_refs": [item.to_dict() for item in self.verification_refs],
            "verification_reason_codes": list(self.verification_reason_codes),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEvidence":
        normalized = _deserialize_datetimes(data, "verified_at", "created_at")
        normalized["verification_refs"] = [
            item if isinstance(item, EvidenceRef) else EvidenceRef.from_dict(item)
            for item in normalized.get("verification_refs") or []
        ]
        return cls(**normalized)


class AssimilationDecision(BaseModel):
    """Job-scoped assimilation result kept only for its processing lifetime."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    candidate_id: str
    disposition: AssimilationDisposition
    canonical_truth_ids: list[str] = Field(default_factory=list)
    predecessor_truth_ids: list[str] = Field(default_factory=list)
    predecessor_entries: list[KnowledgeEntry] = Field(default_factory=list)
    reverses_decision_id: str | None = None
    reason: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=_utc_now)

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "candidate_id": self.candidate_id,
            "disposition": self.disposition,
            "canonical_truth_ids": list(self.canonical_truth_ids),
            "predecessor_truth_ids": list(self.predecessor_truth_ids),
            "predecessor_entries": [item.to_dict() for item in self.predecessor_entries],
            "reverses_decision_id": self.reverses_decision_id,
            "reason": self.reason,
            "decided_at": self.decided_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssimilationDecision":
        normalized = _deserialize_datetimes(data, "decided_at")
        normalized["predecessor_entries"] = [
            item if isinstance(item, KnowledgeEntry) else KnowledgeEntry.from_dict(item)
            for item in normalized.get("predecessor_entries") or []
        ]
        return cls(**normalized)


__all__ = [
    "AssimilationDecision",
    "ClaimKind",
    "KnowledgeCandidate",
    "KnowledgeCandidateStatus",
    "KnowledgeCandidateType",
    "KnowledgeEntry",
    "KnowledgeEvidence",
    "KnowledgeMutation",
    "KnowledgeSource",
    "KnowledgeVersion",
]
