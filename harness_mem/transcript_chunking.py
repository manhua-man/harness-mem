"""Lossless transcript revision and chunk construction."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas.transcript import TranscriptChunk

DEFAULT_TRANSCRIPT_CHUNK_CHARS = 32_000


@dataclass(frozen=True, slots=True)
class TranscriptLogicalUnit:
    """One indivisible semantic range in an exact transcript rendering.

    Callers should place an assistant tool call and its matching tool result in
    the same unit. Units must form a contiguous partition of the source text.
    The chunker keeps a unit intact unless that unit alone exceeds ``max_chars``.
    """

    char_start: int
    char_end: int
    unit_id: str
    kind: str = "message"


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
    logical_units: Sequence[TranscriptLogicalUnit] | None = None,
) -> list[TranscriptChunk]:
    """Split transcript text without dropping or rewriting any character.

    Newline boundaries are preferred when no semantic boundaries are supplied.
    When ``logical_units`` are supplied, complete units are preferred and a
    unit is split only when it alone exceeds the hard limit. Adjacent chunks
    always reconstruct the original value exactly.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not value:
        return []

    units = _validate_logical_units(value, logical_units)

    revision = source_revision or transcript_revision(value)
    chunks: list[TranscriptChunk] = []
    start = 0
    index = 0
    logical_index = 0
    while start < len(value):
        hard_end = min(start + max_chars, len(value))
        end = hard_end
        boundary_strategy: Literal["newline", "logical_unit", "hard_limit"] = (
            "hard_limit"
        )
        sequence_start: int | None = None
        sequence_end: int | None = None
        logical_unit_ids: list[str] = []
        logical_unit_kinds: list[str] = []
        starts_on_boundary = start == 0 or value[start - 1] == "\n"
        ends_on_boundary = end == len(value) or value[end - 1] == "\n"
        starts_with_continuation = False
        ends_with_continuation = False

        if units is not None:
            first_index = logical_index
            sequence_start = first_index
            starts_on_boundary = start == units[first_index].char_start
            last_complete_index: int | None = None
            scan_index = first_index
            while (
                scan_index < len(units)
                and units[scan_index].char_end <= hard_end
            ):
                last_complete_index = scan_index
                scan_index += 1
            if last_complete_index is not None:
                end = units[last_complete_index].char_end
                last_index = last_complete_index
                boundary_strategy = "logical_unit"
            else:
                # The containing logical unit is larger than max_chars. This
                # is the only semantic-boundary mode that permits a hard split.
                end = hard_end
                last_index = first_index
                boundary_strategy = "hard_limit"

            sequence_end = last_index + 1
            logical_unit_ids = [
                unit.unit_id for unit in units[first_index : last_index + 1]
            ]
            logical_unit_kinds = [
                unit.kind for unit in units[first_index : last_index + 1]
            ]
            ends_on_boundary = end == units[last_index].char_end
            starts_with_continuation = not starts_on_boundary
            ends_with_continuation = not ends_on_boundary
            if ends_on_boundary:
                logical_index = last_index + 1
            else:
                logical_index = last_index
        elif hard_end < len(value):
            boundary = value.rfind("\n", start + 1, hard_end + 1)
            if boundary >= start:
                end = boundary + 1
                boundary_strategy = "newline"
            starts_on_boundary = start == 0 or value[start - 1] == "\n"
            ends_on_boundary = end == len(value) or value[end - 1] == "\n"
        else:
            boundary_strategy = "newline"
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
                sequence_start=sequence_start,
                sequence_end=sequence_end,
                raw_content=content,
                content_sha256=digest,
                size_bytes=len(content.encode("utf-8")),
                starts_on_boundary=starts_on_boundary,
                ends_on_boundary=ends_on_boundary,
                boundary_strategy=boundary_strategy,
                logical_unit_ids=logical_unit_ids,
                logical_unit_kinds=logical_unit_kinds,
                starts_with_continuation=starts_with_continuation,
                ends_with_continuation=ends_with_continuation,
            )
        )
        start = end
        index += 1
    return chunks


def _validate_logical_units(
    value: str,
    logical_units: Sequence[TranscriptLogicalUnit] | None,
) -> tuple[TranscriptLogicalUnit, ...] | None:
    if logical_units is None:
        return None
    units = tuple(logical_units)
    if not units:
        raise ValueError("logical_units must cover the non-empty transcript")

    expected_start = 0
    seen_ids: set[str] = set()
    for unit in units:
        if unit.char_start != expected_start:
            raise ValueError("logical_units must be contiguous and ordered")
        if unit.char_end <= unit.char_start or unit.char_end > len(value):
            raise ValueError("logical unit range is outside the transcript")
        if not unit.unit_id or unit.unit_id in seen_ids:
            raise ValueError("logical unit ids must be non-empty and unique")
        if not unit.kind:
            raise ValueError("logical unit kind must be non-empty")
        seen_ids.add(unit.unit_id)
        expected_start = unit.char_end
    if expected_start != len(value):
        raise ValueError("logical_units must cover the complete transcript")
    return units


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
    "TranscriptLogicalUnit",
    "chunk_transcript_text",
    "reconstruct_transcript",
    "sha256_bytes",
    "sha256_text",
    "source_uri_from_path",
    "transcript_revision",
    "transcript_bytes_revision",
    "transcript_source_id",
]
