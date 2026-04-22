"""VerbatimStore interface — Observation read/write abstraction."""

from __future__ import annotations
from typing import Protocol, runtime_checkable

from harness_mem.core.schemas.observation import Observation


@runtime_checkable
class VerbatimStore(Protocol):
    """Observation store interface for verbatim layer.

    The verbatim layer stores raw session/event data exactly as received,
    without summarization or transformation.
    """

    async def save(self, observation: Observation) -> str:
        """Save an observation. Returns the observation id."""
        ...

    async def get(self, id: str) -> Observation | None:
        """Get a single observation by id."""
        ...

    async def list(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[Observation]:
        """List observations, optionally filtered by session_id."""
        ...

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Observation]:
        """Full-text search observations."""
        ...

    async def delete(self, id: str) -> bool:
        """Delete an observation. Returns True if deleted."""
        ...

    async def timeline(
        self,
        project_name: str | None = None,
        limit: int = 50,
    ) -> list[Observation]:
        """Get observations in chronological order."""
        ...
