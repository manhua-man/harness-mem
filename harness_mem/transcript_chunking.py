"""Lossless transcript revision and chunk construction."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.transcript import TranscriptChunk

DEFAULT_TRANSCRIPT_CHUNK_CHARS = 32_000


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest for the exact UTF-8 representation."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    """Return the SHA-256 digest for exact native source bytes."""

    return hashlib.sha256(value).hexdigest()


def transcript_source_id(
    *,
    client: str,
    project_name: str,
    session_id: str,
    source_uri: str = "",
) -> str:
    """Build a stable project-scoped identifier for one host session."""

    key = f"harness-mem://transcript/{client}/{project_name}/{session_id}/{source_uri}"
    return str(uuid5(NAMESPACE_URL, key))


def transcript_revision(value: str) -> str:
    """Build a content-addressed source revision."""

    return f"sha256:{sha256_text(value)}"


def transcript_bytes_revision(value: bytes) -> str:
    """Build a content-addressed revision from exact native source bytes."""

    return f"sha256:{sha256_bytes(value)}"


def source_uri_from_path(path: Path) -> str:
    """Return a portable local source URI without resolving missing paths."""

    return path.expanduser().absolute().as_uri()


def chunk_transcript_text(
    value: str,
    *,
    source_id: str,
    project_name: str,
    client: str,
    session_id: str,
    source_revision: str | None = None,
    max_chars: int = DEFAULT_TRANSCRIPT_CHUNK_CHARS,
) -> list[TranscriptChunk]:
    """Split transcript text without dropping or rewriting any character.

    Newline boundaries are preferred. A single oversized line is split at the
    hard limit; adjacent chunks still reconstruct the original value exactly.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not value:
        return []

    revision = source_revision or transcript_revision(value)
    chunks: list[TranscriptChunk] = []
    start = 0
    index = 0
    while start < len(value):
        hard_end = min(start + max_chars, len(value))
        end = hard_end
        if hard_end < len(value):
            boundary = value.rfind("\n", start + 1, hard_end + 1)
            if boundary >= start:
                end = boundary + 1
        if end <= start:
            end = hard_end

        content = value[start:end]
        digest = sha256_text(content)
        chunk_key = f"{source_id}:{revision}:{index}:{start}:{end}:{digest}"
        chunks.append(
            TranscriptChunk(
                id=str(uuid5(NAMESPACE_URL, chunk_key)),
                source_id=source_id,
                project_name=project_name,
                client=client,
                session_id=session_id,
                source_revision=revision,
                chunk_index=index,
                char_start=start,
                char_end=end,
                raw_content=content,
                content_sha256=digest,
                size_bytes=len(content.encode("utf-8")),
                starts_on_boundary=start == 0 or value[start - 1] == "\n",
                ends_on_boundary=end == len(value) or value[end - 1] == "\n",
            )
        )
        start = end
        index += 1
    return chunks


def reconstruct_transcript(
    chunks: list[TranscriptChunk],
    *,
    expected_sha256: str | None = None,
) -> str:
    """Reconstruct and validate one complete transcript revision."""

    if not chunks:
        return ""
    ordered = sorted(chunks, key=lambda item: item.chunk_index)
    expected_index = 0
    expected_start = 0
    source_id = ordered[0].source_id
    revision = ordered[0].source_revision
    contents: list[str] = []
    for chunk in ordered:
        if chunk.source_id != source_id or chunk.source_revision != revision:
            raise ValueError("chunks belong to different transcript revisions")
        if chunk.chunk_index != expected_index:
            raise ValueError("chunk index gap detected")
        if chunk.char_start != expected_start:
            raise ValueError("chunk character range gap detected")
        if chunk.char_end - chunk.char_start != len(chunk.raw_content):
            raise ValueError("chunk character range does not match content")
        if sha256_text(chunk.raw_content) != chunk.content_sha256:
            raise ValueError("chunk content hash mismatch")
        contents.append(chunk.raw_content)
        expected_index += 1
        expected_start = chunk.char_end

    value = "".join(contents)
    if expected_sha256 is not None and sha256_text(value) != expected_sha256:
        raise ValueError("reconstructed transcript content hash mismatch")
    return value


__all__ = [
    "DEFAULT_TRANSCRIPT_CHUNK_CHARS",
    "chunk_transcript_text",
    "reconstruct_transcript",
    "sha256_bytes",
    "sha256_text",
    "source_uri_from_path",
    "transcript_revision",
    "transcript_bytes_revision",
    "transcript_source_id",
]
