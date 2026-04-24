"""LocalMemoryBackend — unified local backend composing verbatim + structured stores."""

from __future__ import annotations
from pathlib import Path

from harness_mem.core.interfaces.verbatim_store import VerbatimStore
from harness_mem.core.interfaces.structured_store import StructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.local_structured_store import LocalStructuredStore


DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"


class LocalMemoryBackend:
    """Unified local memory backend.

    Combines LocalVerbatimStore and LocalStructuredStore under one roof,
    sharing the same data directory.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._verbatim_store: LocalVerbatimStore | None = None
        self._structured_store: LocalStructuredStore | None = None

    async def init(self) -> None:
        """Initialize both stores."""
        self._verbatim_store = LocalVerbatimStore(self.data_dir)
        self._structured_store = LocalStructuredStore(self.data_dir)

    async def close(self) -> None:
        """Close both stores."""
        if self._verbatim_store:
            self._verbatim_store.close()
            self._verbatim_store = None
        if self._structured_store:
            self._structured_store.close()
            self._structured_store = None

    @property
    def verbatim_store(self) -> VerbatimStore:
        if self._verbatim_store is None:
            raise RuntimeError("Backend not initialized. Call init() first.")
        return self._verbatim_store

    @property
    def structured_store(self) -> StructuredStore:
        if self._structured_store is None:
            raise RuntimeError("Backend not initialized. Call init() first.")
        return self._structured_store
