"""ConfirmedRule schema — confirmed actionable rules."""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ConfirmedRule(BaseModel):
    """User-confirmed actionable rules.

    These rules are loaded during wake-up and influence
    how the agent approaches work in a new session.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    pattern: str = Field(description="Rule content / pattern text")
    trigger: str = Field(description="When this rule applies")
    examples: list[str] = Field(default_factory=list)
    confirmed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_candidate_id: str = Field(
        description="Original rule_candidate id this was promoted from"
    )
    source_session_id: str = Field(
        default="",
        description="Session ID this rule was created from"
    )
    tags: list[str] = Field(default_factory=list)
    provenance: Optional[dict] = Field(
        default=None,
        description="来源线索: {session_id, observation_ids, agent_type, tool_name}"
    )
    valid_from: datetime | None = Field(
        default=None,
        description="When this rule becomes valid. Defaults to confirmed_at.",
    )
    valid_to: datetime | None = Field(
        default=None,
        description="When this rule stops being current; None means current.",
    )
    recorded_at: datetime | None = Field(
        default=None,
        description="When harness-mem recorded this rule. Defaults to confirmed_at.",
    )
    supersedes: list[str] = Field(
        default_factory=list,
        description="Rule ids this rule supersedes.",
    )
    superseded_by: list[str] = Field(
        default_factory=list,
        description="Rule ids that supersede this rule.",
    )

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: object) -> None:
        if self.valid_from is None:
            self.valid_from = self.confirmed_at
        if self.recorded_at is None:
            self.recorded_at = self.confirmed_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "pattern": self.pattern,
            "trigger": self.trigger,
            "examples": self.examples,
            "confirmed_at": self.confirmed_at.isoformat(),
            "source_candidate_id": self.source_candidate_id,
            "source_session_id": self.source_session_id,
            "tags": self.tags,
            "provenance": self.provenance,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConfirmedRule":
        for field in ("confirmed_at", "valid_from", "valid_to", "recorded_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "provenance" not in data:
            data["provenance"] = None
        if "valid_from" not in data or data["valid_from"] is None:
            data["valid_from"] = data.get("confirmed_at")
        if "recorded_at" not in data or data["recorded_at"] is None:
            data["recorded_at"] = data.get("confirmed_at")
        if "valid_to" not in data:
            data["valid_to"] = None
        if "supersedes" not in data or data["supersedes"] is None:
            data["supersedes"] = []
        if "superseded_by" not in data or data["superseded_by"] is None:
            data["superseded_by"] = []
        return cls(**data)
