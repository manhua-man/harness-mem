"""MemoryEntry schema — structured project knowledge."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


MemoryType = Literal["episodic", "semantic", "procedural"]
"""Three-layer memory typing introduced in v1.6.0.

- ``semantic`` — stable, structured project knowledge (rules, facts, decisions).
  This is the v1.6.0 default; existing entries auto-derive to ``semantic`` when
  their ``category`` matches the registered set (architecture / convention /
  api / bug / decision).
- ``episodic`` — event-shaped recollections. Used for entries whose ``category``
  is unknown or free-form when loaded from legacy data.
- ``procedural`` — multi-step skills / how-tos. Reserved for v1.8 — accepted
  through the API but not produced by any v1.6.x ingest / distill path.

Wake-up bucket budgets and search-time filtering on this field arrive in
v1.6.1. v1.6.0 only exposes the field; behavior remains unchanged.
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

    Mirrors the rule documented in ``openspec/changes/2026-05-17-v160-eval-and-typing``:
    registered categories map to ``semantic``; anything else (including missing
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
        default="accepted",
        description="pending | accepted | rejected"
    )
    source: str = Field(
        description="Source observation id or 'manual'"
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
    provenance: dict | None = Field(
        default=None,
        description="来源线索: {session_id, observation_ids, agent_type, tool_name}"
    )
    memory_type: MemoryType = Field(
        default="semantic",
        description=(
            "Three-layer memory typing (v1.6.0): episodic (events), "
            "semantic (rules/facts), procedural (reserved for v1.8). "
            "Exposed read-only in v1.6.0; consumed by wake-up bucketing in v1.6.1."
        ),
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "category": self.category,
            "content": self.content,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "compacted": self.compacted,
            "usage_count": self.usage_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "provenance": self.provenance,
            "memory_type": self.memory_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        for field in ("created_at", "updated_at", "last_accessed_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "status" not in data:
            data["status"] = "accepted"
        if "compacted" not in data:
            data["compacted"] = False
        if "usage_count" not in data:
            data["usage_count"] = 0
        if "last_accessed_at" not in data:
            data["last_accessed_at"] = None
        if "provenance" not in data:
            data["provenance"] = None
        if "memory_type" not in data or data["memory_type"] is None:
            data["memory_type"] = _derive_memory_type(data.get("category"))
        return cls(**data)
