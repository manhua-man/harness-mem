"""MemoryEntry schema — structured project knowledge."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


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

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "category": self.category,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "compacted": self.compacted,
            "usage_count": self.usage_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        for field in ("created_at", "updated_at", "last_accessed_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "compacted" not in data:
            data["compacted"] = False
        if "usage_count" not in data:
            data["usage_count"] = 0
        if "last_accessed_at" not in data:
            data["last_accessed_at"] = None
        if "provenance" not in data:
            data["provenance"] = None
        return cls(**data)
