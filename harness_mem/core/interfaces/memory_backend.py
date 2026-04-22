"""MemoryBackend interface — unified memory backend."""

from __future__ import annotations
from typing import Protocol, runtime_checkable

from harness_mem.core.interfaces.verbatim_store import VerbatimStore
from harness_mem.core.interfaces.structured_store import StructuredStore


@runtime_checkable
class MemoryBackend(Protocol):
    """Unified memory backend interface.

    Composes VerbatimStore and StructuredStore under one roof,
    sharing lifecycle (init/close) and data directory.
    """

    async def init(self) -> None:
        """Initialize the backend (create dirs, open connections)."""
        ...

    async def close(self) -> None:
        """Close all connections and release resources."""
        ...

    @property
    def verbatim_store(self) -> VerbatimStore:
        """Access the verbatim store."""
        ...

    @property
    def structured_store(self) -> StructuredStore:
        """Access the structured store."""
        ...
