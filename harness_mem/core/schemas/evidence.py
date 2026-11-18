"""Content-minimized evidence metadata for automatic candidate admission."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

EvidenceBasis = Literal["repository", "user_statement", "transcript", "source_report"]
VerificationOutcome = Literal[
    "verified",
    "unverified",
    "contradicted",
    "not_applicable",
]
EvidenceRefKind = Literal["repository", "user_statement", "transcript", "source_report"]


class EvidenceBinding(BaseModel):
    """A checked span and its destination in one submitted knowledge body."""

    target: Literal["claim", "condition", "undecided_state", "operation"]
    target_sha256: str
    quote_sha256: str
    message_index: int | None = None
    start: int
    end: int
    native_trace: dict | None = None

    model_config = {"extra": "forbid", "frozen": True}

    def to_dict(self) -> dict:
        return self.model_dump(exclude={"native_trace"} if self.native_trace is None else None)


class EvidenceRef(BaseModel):
    """Integrity reference used by Dream admission, never evidence content."""

    kind: EvidenceRefKind
    locator: str | None = Field(
        default=None,
        description=(
            "Transient project-relative path, or absolute path under a user-configured "
            "evidence.repository_roots entry. Source/session refs use "
            "the owning distill job instead of storing a raw locator."
        ),
    )
    locator_sha256: str | None = None
    content_sha256: str | None = None
    exchange_index: int | None = Field(default=None, ge=1)
    chunk_index: int | None = Field(default=None, ge=0)
    role: Literal["user", "assistant", "tool"] | None = None
    bindings: SkipJsonSchema[list[EvidenceBinding]] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    def model_post_init(self, __context: object) -> None:
        if self.locator and not self.locator_sha256:
            self.locator_sha256 = sha256(self.locator.encode("utf-8")).hexdigest()

    def sanitized(self) -> "EvidenceRef":
        """Remove the transient locator while preserving its one-way digest."""

        return self.model_copy(update={"locator": None})

    def to_dict(self) -> dict:
        result: dict = {
            "kind": self.kind,
            "locator": self.locator,
            "locator_sha256": self.locator_sha256,
            "content_sha256": self.content_sha256,
            "exchange_index": self.exchange_index,
            "chunk_index": self.chunk_index,
            "role": self.role,
        }
        if self.bindings:
            result["bindings"] = [binding.to_dict() for binding in self.bindings]
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceRef":
        return cls(**dict(data))


class EvidenceEnvelope(BaseModel):
    """Orthogonal evidence-origin and verification-result contract."""

    evidence_basis: EvidenceBasis | None = None
    verification_outcome: VerificationOutcome | None = None
    verification_reason_codes: list[str] = Field(default_factory=list)
    verification_refs: list[EvidenceRef] = Field(default_factory=list)
    verified_at: datetime | None = None

    model_config = {"extra": "forbid"}


__all__ = [
    "EvidenceBasis",
    "EvidenceEnvelope",
    "EvidenceRef",
    "EvidenceRefKind",
    "VerificationOutcome",
]
