"""Lossless transcript source and chunk schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


TranscriptSourceStatus = Literal[
    "discovered",
    "syncing",
    "synced",
    "changed",
    "missing",
    "failed",
    "legacy_partial",
]
TranscriptCoverage = Literal["complete", "partial", "unknown"]


class TranscriptSource(BaseModel):
    """One project-scoped host session at one current source revision."""

    id: str
    project_name: str
    project_root: str
    client: str
    session_id: str
    source_kind: str
    source_uri: str
    source_revision: str
    raw_sha256: str
    normalized_sha256: str
    raw_size_bytes: int = 0
    normalized_size_bytes: int = 0
    mtime_ns: int | None = None
    parser_version: str = "transcript-v1"
    status: TranscriptSourceStatus = "discovered"
    coverage: TranscriptCoverage = "unknown"
    chunk_count: int = 0
    sequence_count: int = 0
    metadata: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    synced_at: datetime | None = None

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        payload = self.model_dump(mode="json")
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "TranscriptSource":
        return cls(**payload)


class TranscriptSourceRevision(BaseModel):
    """Immutable audit metadata for one captured native source revision."""

    source_id: str
    source_revision: str
    project_name: str
    project_root: str
    client: str
    session_id: str
    source_kind: str
    source_uri: str
    raw_sha256: str
    normalized_sha256: str
    raw_size_bytes: int
    normalized_size_bytes: int
    mtime_ns: int | None = None
    parser_version: str = "transcript-v1"
    coverage: TranscriptCoverage = "complete"
    chunk_count: int = 0
    sequence_count: int = 0
    metadata: dict = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> "TranscriptSourceRevision":
        return cls(**payload)


class TranscriptChunk(BaseModel):
    """Exact ordered character range from one transcript source revision."""

    id: str
    source_id: str
    project_name: str
    client: str
    session_id: str
    source_revision: str
    chunk_index: int
    char_start: int
    char_end: int
    sequence_start: int | None = None
    sequence_end: int | None = None
    raw_content: str
    content_sha256: str
    size_bytes: int
    starts_on_boundary: bool = True
    ends_on_boundary: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> "TranscriptChunk":
        return cls(**payload)


class TranscriptScanFrontier(BaseModel):
    """Durable round-robin position for one project/client source root."""

    project_name: str
    client: str
    source_root: str
    cursor_key: str | None = None
    # When only one changed session may be synchronized, alternate the recent
    # and backlog lanes across invocations so an active current session cannot
    # starve historical recovery forever.
    next_lane: Literal["recent", "backlog"] = "recent"
    retry_sources: dict[str, "TranscriptScanRetry"] = Field(default_factory=dict)
    scan_cycle: int = 0
    scanned_in_cycle: int = 0
    last_scanned_at: datetime | None = None
    last_completed_cycle_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: dict) -> "TranscriptScanFrontier":
        return cls(**payload)


class TranscriptScanRetry(BaseModel):
    """Retry state for a source that could not be read or parsed."""

    attempts: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "allow"}


__all__ = [
    "TranscriptChunk",
    "TranscriptCoverage",
    "TranscriptScanFrontier",
    "TranscriptScanRetry",
    "TranscriptSource",
    "TranscriptSourceRevision",
    "TranscriptSourceStatus",
]
