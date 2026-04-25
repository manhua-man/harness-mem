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

    model_config = {"extra": "allow"}

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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConfirmedRule":
        if isinstance(data.get("confirmed_at"), str):
            data["confirmed_at"] = datetime.fromisoformat(data["confirmed_at"])
        if "provenance" not in data:
            data["provenance"] = None
        return cls(**data)
