"""Shared adapter contracts for session-oriented clients."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation

if TYPE_CHECKING:
    from harness_mem.adapters.snapshot import TranscriptSyncResult

Issue = dict[str, str]


class SessionRecord(TypedDict, total=False):
    """Normalized session metadata surfaced by client adapters."""

    path: Path
    name: str
    session_id: str
    size_kb: float
    size_bytes: int
    size: str
    lines: int
    mtime: datetime
    mtime_ns: int
    cwd: str
    source_kind: str
    cursor_project_dir: str


class SessionAdapter(Protocol):
    """Minimal contract shared by CLI and MCP-facing runtime code."""

    backend: MemoryBackend | None

    def list_sessions(
        self,
        project_name: str | None = None,
        *,
        min_size_kb: int = 0,
        limit: int | None = None,
        issues: list[Issue] | None = None,
    ) -> list[SessionRecord]:
        """Return recent sessions for the adapter's source client."""

    def session_to_observation(
        self,
        session_path: Path,
        session_id: str,
        project_name: str | None = None,
        *,
        issues: list[Issue] | None = None,
    ) -> Observation:
        """Build the derived search rendering for a native session."""

    async def sync_session(
        self,
        session_path: Path,
        session_id: str,
        project_name: str,
    ) -> TranscriptSyncResult:
        """Capture one complete native revision and refresh its search projection."""

    async def ingest(
        self,
        project_name: str | None = None,
        limit: int = 10,
        min_size_kb: int = 0,
    ) -> dict[str, Any]:
        """Scan and synchronize changed sessions into the backend."""
