"""ProjectProfileStore interface — project profile read/write."""

from __future__ import annotations
from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.project_profile import ProjectProfile


@runtime_checkable
class ProjectProfileStore(Protocol):
    """Project profile store interface."""

    async def save(self, profile: ProjectProfile) -> str:
        """Save a project profile. Returns the profile id."""
        ...

    async def get(self, project_name: str) -> ProjectProfile | None:
        """Get project profile by project name."""
        ...

    async def list(self) -> list[ProjectProfile]:
        """List all project profiles."""
        ...
