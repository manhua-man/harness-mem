"""LocalMemoryBackend — unified local backend composing verbatim + structured stores."""

from __future__ import annotations

import os
from pathlib import Path

from harness_mem.core.interfaces.verbatim_store import VerbatimStore
from harness_mem.core.interfaces.structured_store import StructuredStore
from harness_mem.storage.canonical_store import bootstrap_canonical_runtime
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.transcript_store import TranscriptStore


def resolve_default_data_dir() -> Path:
    override = str(os.environ.get("HARNESS_MEM_DATA_DIR") or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".harness-mem" / "data"


DEFAULT_DATA_DIR = resolve_default_data_dir()


class LocalMemoryBackend:
    """Unified local memory backend.

    Combines LocalVerbatimStore and LocalStructuredStore under one roof,
    sharing the same data directory.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._verbatim_store: LocalVerbatimStore | None = None
        self._structured_store: LocalStructuredStore | None = None
        self._reflection_job_store: ReflectionJobStore | None = None
        self._transcript_store: TranscriptStore | None = None
        self.runtime_state: str = "canonical"
        self.runtime_error: str | None = None
        self.runtime_recovery_hint: str | None = None

    async def init(self) -> None:
        """Initialize the backend using canonical-first runtime bootstrap."""
        runtime = bootstrap_canonical_runtime(self.data_dir)
        self.runtime_state = runtime.mode
        self.runtime_error = runtime.error
        self.runtime_recovery_hint = runtime.recovery_hint
        canonical_mode = runtime.mode != "degraded_fallback"

        self._verbatim_store = LocalVerbatimStore(
            self.data_dir,
            canonical_mode=canonical_mode,
        )
        self._structured_store = LocalStructuredStore(
            self.data_dir,
            canonical_mode=canonical_mode,
        )
        self._transcript_store = TranscriptStore(self.data_dir)
        await self._verbatim_store.init_runtime()
        await self._structured_store.init_runtime()

    async def close(self) -> None:
        """Close both stores."""
        if self._verbatim_store:
            self._verbatim_store.close()
            self._verbatim_store = None
        if self._structured_store:
            self._structured_store.close()
            self._structured_store = None
        if self._transcript_store:
            self._transcript_store.close()
            self._transcript_store = None
        self._reflection_job_store = None

    @property
    def initialized(self) -> bool:
        """Return whether all public stores are ready for handler use."""

        return bool(
            self._verbatim_store is not None
            and self._structured_store is not None
            and self._transcript_store is not None
        )

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

    @property
    def transcript_store(self) -> TranscriptStore:
        if self._transcript_store is None:
            raise RuntimeError("Backend not initialized. Call init() first.")
        return self._transcript_store

    @property
    def reflection_job_store(self) -> ReflectionJobStore:
        """Internal dream job ledger wrapping the structured SQLiteIndex.

        The historical store/table name remains for data compatibility. Lazy
        construction keeps callers sharing one connection-locked store through
        the structured store's public index boundary.
        """
        if self._structured_store is None:
            raise RuntimeError("Backend not initialized. Call init() first.")
        if self._reflection_job_store is None:
            # Share the structured store's derived index through its public
            # lifecycle boundary rather than opening a second handle.
            self._reflection_job_store = ReflectionJobStore(self._structured_store.index)
        return self._reflection_job_store
