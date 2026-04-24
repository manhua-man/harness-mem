"""Observation schema — verbatim layer raw session/event."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """Raw session/event from a client adapter.

    This is the verbatim layer — stores original transcript, events,
    commands, and output exactly as received.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    client: str = Field(description="e.g. claude-code, codex, cursor")
    raw_content: str = Field(description="Original transcript or event JSON")
    content_type: str = Field(
        description="transcript | event | command | output"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    compacted: bool = Field(default=False, description="Soft-delete marker for purge")

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "client": self.client,
            "raw_content": self.raw_content,
            "content_type": self.content_type,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "tags": self.tags,
            "compacted": self.compacted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Observation":
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
