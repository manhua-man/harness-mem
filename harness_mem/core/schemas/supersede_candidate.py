"""SupersedeCandidate schema - pending mark-not-delete truth replacement."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class SupersedeCandidate(BaseModel):
    """Pending request to mark old truth historical after replacement.

    v1.7.1 keeps supersede operations in the review layer. Confirming one of
    these candidates sets ``valid_to`` on the target truth and links both truth
    records through ``superseded_by`` / ``supersedes``. It never deletes truth.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    target_type: str = Field(description="memory_entry | relation_fact | confirmed_rule")
    target_id: str = Field(description="Existing truth id to mark historical")
    replacement_type: str = Field(description="memory_entry | relation_fact | confirmed_rule")
    replacement_id: str = Field(description="Current truth id that replaces target")
    reason: str
    evidence: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: str = Field(default="pending", description="pending | accepted | rejected")
    source: str = Field(default="", description="Source observation/session/candidate id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: datetime | None = None
    reviewer_id: str | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "replacement_type": self.replacement_type,
            "replacement_id": self.replacement_id,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewer_id": self.reviewer_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SupersedeCandidate":
        for field in ("created_at", "reviewed_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "source" not in data:
            data["source"] = ""
        if "reviewed_at" not in data:
            data["reviewed_at"] = None
        if "reviewer_id" not in data:
            data["reviewer_id"] = None
        return cls(**data)
