"""A local store binding scoped to a single synchronous Agent operation."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional

from harness_mem.storage.local_memory_backend import LocalMemoryBackend, resolve_default_data_dir


active_backend: ContextVar[Optional[LocalMemoryBackend]] = ContextVar("agent_backend", default=None)


@contextmanager
def agent_backend(data_dir: str | Path | None = None) -> Iterator[LocalMemoryBackend]:
    directory = Path(data_dir) if data_dir is not None else resolve_default_data_dir()
    backend = LocalMemoryBackend(directory)
    binding = active_backend.set(backend)
    try:
        asyncio.run(backend.init())
        yield backend
    finally:
        active_backend.reset(binding)
        asyncio.run(backend.close())
