"""RelationFact schema - entity-to-entity facts."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class RelationFact(BaseModel):
    """A typed relationship between two project entities.

    Relation facts are intentionally local-first and evidence-backed. They are
    stored as JSON blobs, with a small SQLite index for scoped reads and FTS.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    source_entity: str = Field(description="Origin entity for the relation")
    target_entity: str = Field(description="Target entity for the relation")
    relation_type: str = Field(description="Typed relation, e.g. depends_on")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    status: str = Field(
        default="accepted",
        description="pending | accepted | rejected"
    )
    evidence: str = Field(description="Human-readable evidence for the relation")
    source: str = Field(description="Source observation id, entry id, or 'manual'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)
    provenance: dict | None = Field(
        default=None,
        description="Source clues: {session_id, observation_ids, agent_type, tool_name}",
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "source_entity": self.source_entity,
            "target_entity": self.target_entity,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "status": self.status,
            "evidence": self.evidence,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationFact":
        for field in ("created_at", "updated_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "status" not in data:
            data["status"] = "accepted"
        if "tags" not in data:
            data["tags"] = []
        if "provenance" not in data:
            data["provenance"] = None
        return cls(**data)
