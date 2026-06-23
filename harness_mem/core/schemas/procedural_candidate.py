"""ProceduralCandidate schema - reviewable ordered workflow memory."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class ProceduralCandidate(BaseModel):
    """Pending procedural memory extracted from repeated workflows.

    v1.8 starts procedural memory as a read-only, reviewable candidate shape.
    These candidates are not active skills and do not mutate truth or wake
    selection.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    activation_condition: str = Field(description="When this workflow should run")
    steps: list[str] = Field(description="Ordered workflow steps", min_length=1)
    termination_condition: str = Field(description="When the workflow is complete")
    success_examples: list[str] = Field(default_factory=list)
    source_session_id: str = Field(default="", description="Source session provenance")
    source: str = Field(default="", description="Source observation/file/candidate id")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: str = Field(default="pending", description="draft | pending | accepted | rejected")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    @field_validator(
        "project_name",
        "activation_condition",
        "termination_condition",
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "activation_condition": self.activation_condition,
            "steps": self.steps,
            "termination_condition": self.termination_condition,
            "success_examples": self.success_examples,
            "source_session_id": self.source_session_id,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProceduralCandidate":
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "source_session_id" not in data:
            data["source_session_id"] = ""
        if "source" not in data:
            data["source"] = ""
        return cls(**data)
