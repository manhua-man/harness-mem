"""ProjectProfile schema — project metadata and hints."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ProjectProfile(BaseModel):
    """Minimal project profile for wake-up context.

    Captures the essential stacks, key files, and hints
    that help a new session orient quickly.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    description: str = ""
    stacks: list[str] = Field(
        default_factory=list,
        description="Languages and frameworks, e.g. ['php', 'laravel', 'typescript', 'next.js']"
    )
    key_files: list[str] = Field(
        default_factory=list,
        description="Important file paths, e.g. ['backend/app/Services/AuthService.php']"
    )
    service_hints: list[str] = Field(
        default_factory=list,
        description="Service names or URLs, e.g. ['api:8080', 'mysql:3306']"
    )
    database_hints: list[str] = Field(
        default_factory=list,
        description="Database connection strings or types"
    )
    conventions: list[str] = Field(
        default_factory=list,
        description="Coding conventions or rules"
    )
    weak_link_signals: bool = Field(
        default=False,
        description=(
            "Opt-in flag for v2.3.1 weak-link signal application: when True, "
            "wake re-groups confirmed rules into Recent active / Stable / "
            "quiet using RetrievalSignal history, and search_memory boosts "
            "results with repeat search hits plus bounded context outcome "
            "hints. Default off; flip on after "
            "the project has accumulated enough signal history (typically "
            "after a week of normal usage)."
        ),
    )
    retrieval_profile: Literal["light", "quality"] | None = Field(
        default=None,
        description=(
            "Optional retrieval quality profile. None keeps the default light "
            "path. 'quality' opts the project into deterministic query "
            "rewrite/fanout metadata with a noop reranker; it does not enable "
            "HyDE, ANN, Tantivy, LanceDB, or silent default changes."
        ),
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_ingest_at: datetime | None = Field(
        default=None,
        description="Timestamp of last successful ingest for this project"
    )
    last_ingest_session_id: str | None = Field(
        default=None,
        description="Session ID of last successfully ingested session (for incremental cursor)"
    )

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "description": self.description,
            "stacks": self.stacks,
            "key_files": self.key_files,
            "service_hints": self.service_hints,
            "database_hints": self.database_hints,
            "conventions": self.conventions,
            "weak_link_signals": self.weak_link_signals,
            "retrieval_profile": self.retrieval_profile,
            "last_updated": self.last_updated.isoformat(),
            "created_at": self.created_at.isoformat(),
            "last_ingest_at": self.last_ingest_at.isoformat() if self.last_ingest_at else None,
            "last_ingest_session_id": self.last_ingest_session_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectProfile":
        for field in ("last_updated", "created_at", "last_ingest_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)
