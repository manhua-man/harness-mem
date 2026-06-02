"""Skill schema - confirmed procedural memory."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SkillScope = Literal["project", "workspace", "global"]


class Skill(BaseModel):
    """Confirmed procedural memory that can be retrieved for a task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    name: str
    activation_condition: str
    steps: list[str] = Field(min_length=1)
    termination_condition: str
    success_examples: list[str] = Field(default_factory=list)
    source_candidate_id: str = ""
    source_session_id: str = ""
    scope: SkillScope = Field(default="project")
    origin_project: str = ""
    source_ids: list[str] = Field(default_factory=list)
    portability_notes: str = ""
    disabled_assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: str = Field(default="active", description="active | retired")
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _default_origin_project(self) -> "Skill":
        if not self.origin_project:
            self.origin_project = self.project_name
        return self

    @field_validator(
        "project_name",
        "name",
        "activation_condition",
        "termination_condition",
        "scope",
    )
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped

    @field_validator("steps", "success_examples")
    @classmethod
    def _strip_text_list(cls, value: list[str]) -> list[str]:
        stripped = [item.strip() for item in value if item.strip()]
        if not stripped and value:
            raise ValueError("list must contain non-empty text")
        return stripped

    @field_validator("source_ids", "disabled_assumptions")
    @classmethod
    def _strip_optional_text_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("origin_project", "portability_notes")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    def record_result(self, *, success: bool, used_at: datetime | None = None) -> "Skill":
        used_at = used_at or datetime.now(timezone.utc)
        usage_count = self.usage_count + 1
        success_count = self.success_count + (1 if success else 0)
        failure_count = self.failure_count + (0 if success else 1)
        return self.model_copy(
            update={
                "usage_count": usage_count,
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": success_count / usage_count if usage_count else None,
                "last_used_at": used_at,
                "updated_at": used_at,
            }
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "name": self.name,
            "activation_condition": self.activation_condition,
            "steps": self.steps,
            "termination_condition": self.termination_condition,
            "success_examples": self.success_examples,
            "source_candidate_id": self.source_candidate_id,
            "source_session_id": self.source_session_id,
            "scope": self.scope,
            "origin_project": self.origin_project,
            "source_ids": self.source_ids,
            "portability_notes": self.portability_notes,
            "disabled_assumptions": self.disabled_assumptions,
            "confidence": self.confidence,
            "status": self.status,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        for field in ("created_at", "updated_at", "last_used_at"):
            if isinstance(data.get(field), str) and data[field]:
                data[field] = datetime.fromisoformat(data[field])
        if "source_candidate_id" not in data:
            data["source_candidate_id"] = ""
        if "source_session_id" not in data:
            data["source_session_id"] = ""
        if "scope" not in data:
            data["scope"] = "project"
        if "origin_project" not in data or not data.get("origin_project"):
            data["origin_project"] = data.get("project_name", "")
        if "source_ids" not in data:
            source_ids = []
            if data.get("source_candidate_id"):
                source_ids.append(str(data["source_candidate_id"]))
            if data.get("source_session_id"):
                source_ids.append(str(data["source_session_id"]))
            data["source_ids"] = source_ids
        if "portability_notes" not in data:
            data["portability_notes"] = ""
        if "disabled_assumptions" not in data:
            data["disabled_assumptions"] = []
        if "usage_count" not in data:
            data["usage_count"] = 0
        if "success_count" not in data:
            data["success_count"] = 0
        if "failure_count" not in data:
            data["failure_count"] = 0
        return cls(**data)
