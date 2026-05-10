"""VerbatimStore interface — Observation read/write abstraction."""

from __future__ import annotations
import builtins
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
    ) -> builtins.list[Observation]:
        """List observations, optionally filtered by session_id."""
        ...

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        project_name: str | None = None,
        limit: int = 20,
        mode: str = "auto",
        temporal_bias: bool = False,
    ) -> builtins.list[Observation]:
        """Full-text search observations, optionally filtered by session_id or project_name."""
        ...

    async def delete(self, id: str) -> bool:
        """Delete an observation. Returns True if deleted."""
        ...

    async def soft_delete(self, id: str) -> bool:
        """Soft-delete an observation by setting compacted=True. Returns True if updated."""
        ...

    async def timeline(
        self,
        project_name: str | None = None,
        limit: int = 50,
    ) -> builtins.list[Observation]:
        """Get observations in chronological order."""
        ...
