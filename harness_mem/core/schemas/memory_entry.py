"""MemoryEntry schema — structured project knowledge."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from harness_mem.core.schemas.evidence import (
    EvidenceBasis,
    EvidenceRef,
    VerificationOutcome,
)


MemoryType = Literal["episodic", "semantic", "procedural"]
"""Three-layer memory typing used by search and wake selection.

- ``semantic`` — stable, structured project knowledge (rules, facts, decisions).
  This is the default; existing entries auto-derive to ``semantic`` when
  their ``category`` matches the registered set (architecture / convention /
  api / bug / decision).
- ``episodic`` — event-shaped recollections. Used for entries whose ``category``
  is unknown or free-form when loaded from legacy data.
- ``procedural`` — multi-step skills / how-tos. Accepted by the read model and
  governed separately from ordinary semantic facts.
"""


_SEMANTIC_CATEGORIES: frozenset[str] = frozenset({
    "architecture",
    "convention",
    "api",
    "bug",
    "decision",
})


def _derive_memory_type(category: str | None) -> MemoryType:
    """Derive memory_type from category for legacy entries lacking the field.

    Registered categories map to ``semantic``; anything else (including missing
    or empty ``category``) falls back to ``episodic``. This function NEVER
    returns ``procedural`` — that type is only produced when explicitly set by
    the caller.
    """
    if category and category in _SEMANTIC_CATEGORIES:
        return "semantic"
    return "episodic"


class MemoryEntry(BaseModel):
    """Stable, structured, long-term reusable project knowledge.

    Category values:
    - architecture: project structure, tech stack decisions
    - convention: coding standards, naming patterns
    - api: endpoint contracts, data formats
    - bug: known issues, workaround patterns
    - decision: architectural choices, tool selections
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    category: str = Field(
        description="architecture | convention | api | bug | decision"
    )
    content: str
    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0,
        description="Confidence score 0.0-1.0"
    )
    status: str = Field(
        default="pending",
        description=(
            "Candidate layer: pending | deferred | rejected. "
            "Truth layer: auto_confirmed | provisional | user_confirmed. "
            "Historical: superseded."
        ),
    )
    source: str = Field(
        description="Source observation id or 'manual'"
    )
    distill_job_id: str | None = Field(
        default=None,
        description="Lossless distill job that produced this candidate, if any.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    tags: list[str] = Field(default_factory=list)
    compacted: bool = Field(default=False, description="Soft-delete marker for purge")
    usage_count: int = Field(default=0, ge=0, description="Number of times this entry was surfaced")
    last_accessed_at: datetime | None = Field(default=None, description="Last time this entry was surfaced")
    tier: Literal["hot", "warm", "cold", "archive"] = Field(
        default="hot",
        description="Lifecycle tier. Default reads include hot/warm; deep recall includes cold/archive.",
    )
    decay_score: float = Field(
        default=0.0,
        ge=0.0,
        description="Lifecycle scorer output used for downgrade/archive candidates.",
    )
    provenance: dict | None = Field(
        default=None,
        description="来源线索: {session_id, observation_ids, agent_type, tool_name}"
    )
    evidence_basis: EvidenceBasis | None = None
    verification_outcome: VerificationOutcome | None = None
    verification_reason_codes: list[str] = Field(default_factory=list)
    verification_refs: list[EvidenceRef] = Field(default_factory=list)
    verified_at: datetime | None = None
    memory_type: MemoryType = Field(
        default="semantic",
        description=(
            "Three-layer memory typing: episodic (events), semantic "
            "(rules/facts), or procedural (ordered workflows)."
        ),
    )
    valid_from: datetime | None = Field(
        default=None,
        description="When this truth becomes valid. Defaults to created_at.",
    )
    valid_to: datetime | None = Field(
        default=None,
        description="When this truth stops being current; None means current.",
    )
    recorded_at: datetime | None = Field(
        default=None,
        description="When harness-mem recorded this truth. Defaults to created_at.",
    )
    supersedes: list[str] = Field(
        default_factory=list,
        description="Truth ids this entry supersedes.",
    )
    superseded_by: list[str] = Field(
        default_factory=list,
        description="Truth ids that supersede this entry.",
    )

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: object) -> None:
        if self.valid_from is None:
            self.valid_from = self.created_at
        if self.recorded_at is None:
            self.recorded_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "category": self.category,
            "content": self.content,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "distill_job_id": self.distill_job_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "compacted": self.compacted,
            "usage_count": self.usage_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "tier": self.tier,
            "decay_score": self.decay_score,
            "provenance": self.provenance,
            "evidence_basis": self.evidence_basis,
            "verification_outcome": self.verification_outcome,
            "verification_reason_codes": list(self.verification_reason_codes),
            "verification_refs": [ref.to_dict() for ref in self.verification_refs],
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "memory_type": self.memory_type,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        for field in (
            "created_at",
            "updated_at",
            "last_accessed_at",
            "valid_from",
            "valid_to",
            "recorded_at",
            "verified_at",
        ):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "status" not in data:
            data["status"] = "pending"
        else:
            from harness_mem.governance_status import normalize_status_on_load

            data["status"] = normalize_status_on_load(data.get("status"))
        if "compacted" not in data:
            data["compacted"] = False
        if "usage_count" not in data:
            data["usage_count"] = 0
        if "last_accessed_at" not in data:
            data["last_accessed_at"] = None
        if "tier" not in data or data["tier"] is None:
            data["tier"] = "hot"
        if "decay_score" not in data or data["decay_score"] is None:
            data["decay_score"] = 0.0
        if "provenance" not in data:
            data["provenance"] = None
        data.setdefault("evidence_basis", None)
        data.setdefault("verification_outcome", None)
        data.setdefault("verification_reason_codes", [])
        data["verification_refs"] = [
            ref if isinstance(ref, EvidenceRef) else EvidenceRef.from_dict(ref)
            for ref in data.get("verification_refs") or []
        ]
        data.setdefault("verified_at", None)
        if "distill_job_id" not in data:
            data["distill_job_id"] = None
        if "memory_type" not in data or data["memory_type"] is None:
            data["memory_type"] = _derive_memory_type(data.get("category"))
        if "valid_from" not in data or data["valid_from"] is None:
            data["valid_from"] = data.get("created_at")
        if "recorded_at" not in data or data["recorded_at"] is None:
            data["recorded_at"] = data.get("created_at")
        if "valid_to" not in data:
            data["valid_to"] = None
        if "supersedes" not in data or data["supersedes"] is None:
            data["supersedes"] = []
        if "superseded_by" not in data or data["superseded_by"] is None:
            data["superseded_by"] = []
        return cls(**data)
