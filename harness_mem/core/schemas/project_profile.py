"""ProjectProfile schema — project metadata and hints."""

from datetime import datetime, timezone
from typing import Optional
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
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
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
            "last_updated": self.last_updated.isoformat(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectProfile":
        for field in ("last_updated", "created_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field])
        return cls(**data)
