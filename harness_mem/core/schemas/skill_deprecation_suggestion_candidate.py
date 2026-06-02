"""Reviewed suggestion to retire a stale or conflicting shared skill."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


DeprecationTrigger = Literal["stale_shared_skill", "conflicting_shared_skill"]


class SkillDeprecationSuggestionCandidate(BaseModel):
    """Pending suggestion to retire a shared skill after review."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    source_skill_id: str
    trigger: DeprecationTrigger
    summary: str
    conflicting_skill_id: str = ""
    usage_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    last_used_at: datetime | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: Literal["pending", "accepted", "rejected"] = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    @field_validator("project_name", "source_skill_id", "trigger", "summary")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("conflicting_skill_id")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "source_skill_id": self.source_skill_id,
            "trigger": self.trigger,
            "summary": self.summary,
            "conflicting_skill_id": self.conflicting_skill_id,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillDeprecationSuggestionCandidate":
        data = dict(data)
        for field in ("created_at", "last_used_at"):
            if isinstance(data.get(field), str) and data.get(field):
                data[field] = datetime.fromisoformat(data[field])
        if "conflicting_skill_id" not in data:
            data["conflicting_skill_id"] = ""
        if "success_rate" not in data:
            data["success_rate"] = None
        if "last_used_at" not in data:
            data["last_used_at"] = None
        if "status" not in data:
            data["status"] = "pending"
        return cls(**data)
