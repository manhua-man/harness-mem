"""RuleCandidate schema — unconfirmed rules from corrections."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class RuleCandidate(BaseModel):
    """Unconfirmed rules extracted from user corrections.

    These are patterns/triggers identified during a session
    that may become ConfirmedRule after user confirmation.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    session_id: str = Field(description="Source session id")
    pattern: str = Field(description="Rule content / pattern text")
    trigger: str = Field(description="When this rule applies")
    examples: list[str] = Field(default_factory=list)
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0
    )
    status: str = Field(
        default="pending",
        description="pending | accepted | rejected"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "session_id": self.session_id,
            "pattern": self.pattern,
            "trigger": self.trigger,
            "examples": self.examples,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RuleCandidate":
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)
