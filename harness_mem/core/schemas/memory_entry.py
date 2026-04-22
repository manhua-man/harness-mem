"""MemoryEntry schema — structured project knowledge."""

from datetime import datetime, timezone
from typing import Optional
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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        for field in ("created_at", "updated_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)
