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
        default="pending",
        description=(
            "Candidate layer: pending | deferred | rejected. "
            "Truth layer: auto_confirmed | provisional | user_confirmed. "
            "Historical: superseded."
        ),
    )
    evidence: str = Field(description="Human-readable evidence for the relation")
    source: str = Field(description="Source observation id, entry id, or 'manual'")
    distill_job_id: str | None = Field(
        default=None,
        description="Lossless distill job that produced this candidate, if any.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)
    provenance: dict | None = Field(
        default=None,
        description="Source clues: {session_id, observation_ids, agent_type, tool_name}",
    )
    valid_from: datetime | None = Field(
        default=None,
        description="When this relation becomes valid. Defaults to created_at.",
    )
    valid_to: datetime | None = Field(
        default=None,
        description="When this relation stops being current; None means current.",
    )
    recorded_at: datetime | None = Field(
        default=None,
        description="When harness-mem recorded this relation. Defaults to created_at.",
    )
    supersedes: list[str] = Field(
        default_factory=list,
        description="Relation ids this fact supersedes.",
    )
    superseded_by: list[str] = Field(
        default_factory=list,
        description="Relation ids that supersede this fact.",
    )

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: object) -> None:
        if self.valid_from is None:
            self.valid_from = self.created_at
        if self.recorded_at is None:
            self.recorded_at = self.created_at

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
            "distill_job_id": self.distill_job_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "provenance": self.provenance,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationFact":
        for field in (
            "created_at",
            "updated_at",
            "valid_from",
            "valid_to",
            "recorded_at",
        ):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        if "status" not in data:
            data["status"] = "pending"
        else:
            from harness_mem.governance_status import normalize_status_on_load

            data["status"] = normalize_status_on_load(data.get("status"))
        if "tags" not in data:
            data["tags"] = []
        if "provenance" not in data:
            data["provenance"] = None
        if "distill_job_id" not in data:
            data["distill_job_id"] = None
        if "valid_from" not in data or data["valid_from"] is None:
            data["valid_from"] = data.get("created_at")
        if "recorded_at" not in data or data["recorded_at"] is None:
            data["recorded_at"] = data.get("created_at")
        if "valid_to" not in data:
            data["valid_to"] = None
        if "supersedes" not in data or data["supersedes"] is None:
            data["supersedes"] = []
        if "superseded_by" not in data or data["superseded_by"] is None:
            data["superseded_by"] = []
        return cls(**data)
