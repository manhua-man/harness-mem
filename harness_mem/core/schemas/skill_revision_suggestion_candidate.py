"""Reviewed suggestion to improve a low-success skill without rewriting it."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


RevisionTrigger = Literal["low_success_rate", "zero_success_after_repeated_use"]


class SkillRevisionSuggestionCandidate(BaseModel):
    """Pending suggestion to review and improve a confirmed skill."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    source_skill_id: str
    trigger: RevisionTrigger
    summary: str
    usage_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    recent_failure_signal_ids: list[str] = Field(default_factory=list)
    recent_success_signal_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: Literal["pending", "accepted", "rejected"] = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    @field_validator("project_name", "source_skill_id", "summary", "trigger")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("recent_failure_signal_ids", "recent_success_signal_ids")
    @classmethod
    def _strip_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "source_skill_id": self.source_skill_id,
            "trigger": self.trigger,
            "summary": self.summary,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "recent_failure_signal_ids": list(self.recent_failure_signal_ids),
            "recent_success_signal_ids": list(self.recent_success_signal_ids),
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillRevisionSuggestionCandidate":
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "recent_failure_signal_ids" not in data:
            data["recent_failure_signal_ids"] = []
        if "recent_success_signal_ids" not in data:
            data["recent_success_signal_ids"] = []
        if "success_rate" not in data:
            data["success_rate"] = None
        if "status" not in data:
            data["status"] = "pending"
        return cls(**data)
