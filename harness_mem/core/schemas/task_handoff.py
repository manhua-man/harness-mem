"""TaskHandoff schema — task state transfer."""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskHandoff(BaseModel):
    """Task state transfer for session resume.

    Captures what was being worked on, where it stopped,
    and what the next steps are.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    task_id: str = Field(description="Unique task identifier")
    summary: str = Field(description="Brief description of the task")
    status: str = Field(
        default="in_progress",
        description="in_progress | pending | blocked | done"
    )
    last_activity: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    next_steps: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    context: dict = Field(
        default_factory=dict,
        description="Key context: file paths, current state, relevant ids"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    provenance: Optional[dict] = Field(
        default=None,
        description="来源线索: {session_id, observation_ids, agent_type, tool_name}"
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "task_id": self.task_id,
            "summary": self.summary,
            "status": self.status,
            "last_activity": self.last_activity.isoformat(),
            "next_steps": self.next_steps,
            "blockers": self.blockers,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskHandoff":
        for field in ("last_activity", "created_at", "updated_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "provenance" not in data:
            data["provenance"] = None
        return cls(**data)
