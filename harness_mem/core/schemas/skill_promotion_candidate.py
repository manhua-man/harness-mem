"""SkillPromotionCandidate - reviewed promotion from project to shared scope."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


PromotionScope = Literal["workspace", "global"]


class SkillPromotionCandidate(BaseModel):
    """Pending request to promote a project skill into shared scope."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    source_skill_id: str
    requested_scope: PromotionScope
    origin_project: str
    source_ids: list[str] = Field(default_factory=list)
    portability_notes: str = ""
    disabled_assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: Literal["pending", "accepted", "rejected"] = Field(default="pending")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    @field_validator(
        "project_name",
        "source_skill_id",
        "requested_scope",
        "origin_project",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("source_ids", "disabled_assumptions")
    @classmethod
    def _strip_optional_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("portability_notes")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "source_skill_id": self.source_skill_id,
            "requested_scope": self.requested_scope,
            "origin_project": self.origin_project,
            "source_ids": list(self.source_ids),
            "portability_notes": self.portability_notes,
            "disabled_assumptions": list(self.disabled_assumptions),
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillPromotionCandidate":
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "source_ids" not in data:
            data["source_ids"] = []
        if "portability_notes" not in data:
            data["portability_notes"] = ""
        if "disabled_assumptions" not in data:
            data["disabled_assumptions"] = []
        if "status" not in data:
            data["status"] = "pending"
        return cls(**data)
