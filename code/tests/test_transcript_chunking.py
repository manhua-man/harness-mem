from __future__ import annotations

import pytest

from harness_mem.core.schemas.transcript import TranscriptChunk
from harness_mem.transcript_chunking import (
    TranscriptLogicalUnit,
    chunk_transcript_text,
    reconstruct_transcript,
    transcript_revision,
    transcript_source_id,
)


def _chunks(value: str, *, max_chars: int = 20):
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id="session-1",
    )
    return chunk_transcript_text(
        value,
        source_id=source_id,
        project_name="demo",
        client="cursor",
        session_id="session-1",
        max_chars=max_chars,
    )


def test_chunking_reconstructs_every_character() -> None:
    value = "first turn\n" + ("中间内容" * 25) + "\nfinal answer\n"

    chunks = _chunks(value)

    assert len(chunks) > 2
    assert reconstruct_transcript(chunks) == value
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(value)
    assert sum(len(chunk.raw_content) for chunk in chunks) == len(value)


def test_chunking_is_stable_for_same_revision() -> None:
    value = "one\ntwo\nthree\n"

    first = _chunks(value, max_chars=5)
    second = _chunks(value, max_chars=5)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert first[0].source_revision == transcript_revision(value)


def test_reconstruction_rejects_a_gap() -> None:
    chunks = _chunks("one\ntwo\nthree\n", max_chars=5)

    with pytest.raises(ValueError, match="index gap"):
        reconstruct_transcript([chunks[0], *chunks[2:]])


def test_empty_transcript_has_no_chunks() -> None:
    assert _chunks("") == []


def test_legacy_chunk_payload_defaults_boundary_metadata() -> None:
    chunk = _chunks("one\ntwo\n", max_chars=5)[0]
    payload = chunk.model_dump()
    for field in (
        "boundary_strategy",
        "logical_unit_ids",
        "logical_unit_kinds",
        "starts_with_continuation",
        "ends_with_continuation",
    ):
        payload.pop(field)

    restored = TranscriptChunk.from_dict(payload)

    assert restored.boundary_strategy == "newline"
    assert restored.logical_unit_ids == []
    assert restored.logical_unit_kinds == []
    assert restored.starts_with_continuation is False
    assert restored.ends_with_continuation is False


def test_logical_units_keep_tool_call_and_matching_result_together() -> None:
    user = "user asks for status\n"
    tool_exchange = "assistant tool_call(check)\ntool_result(ok)\n"
    outcome = "assistant reports success\n"
    value = user + tool_exchange + outcome
    units = [
        TranscriptLogicalUnit(0, len(user), "user-1", "message"),
        TranscriptLogicalUnit(
            len(user),
            len(user) + len(tool_exchange),
            "tool-1",
            "tool-exchange",
        ),
        TranscriptLogicalUnit(
            len(user) + len(tool_exchange),
            len(value),
            "outcome-1",
            "message",
        ),
    ]

    chunks = chunk_transcript_text(
        value,
        source_id="source",
        project_name="demo",
        client="codex",
        session_id="session",
        max_chars=len(user) + len(tool_exchange) - 1,
        logical_units=units,
    )

    assert reconstruct_transcript(chunks) == value
    assert chunks[0].raw_content == user
    assert chunks[1].raw_content == tool_exchange
    assert chunks[1].logical_unit_ids == ["tool-1"]
    assert chunks[1].logical_unit_kinds == ["tool-exchange"]
    assert chunks[1].boundary_strategy == "logical_unit"
    assert chunks[1].starts_with_continuation is False
    assert chunks[1].ends_with_continuation is False


def test_oversized_logical_unit_has_explicit_continuation_metadata() -> None:
    value = "tool_call\n" + ("x" * 35) + "\ntool_result\n"
    units = [TranscriptLogicalUnit(0, len(value), "tool-oversized", "tool-exchange")]

    chunks = chunk_transcript_text(
        value,
        source_id="source",
        project_name="demo",
        client="codex",
        session_id="session",
        max_chars=20,
        logical_units=units,
    )

    assert reconstruct_transcript(chunks) == value
    assert len(chunks) == 3
    assert chunks[0].ends_with_continuation is True
    assert chunks[1].starts_with_continuation is True
    assert chunks[1].ends_with_continuation is True
    assert chunks[-1].starts_with_continuation is True
    assert chunks[-1].ends_with_continuation is False
    assert all(chunk.logical_unit_ids == ["tool-oversized"] for chunk in chunks)
    assert [chunk.sequence_start for chunk in chunks] == [0, 0, 0]
    assert [chunk.sequence_end for chunk in chunks] == [1, 1, 1]


def test_logical_units_must_be_an_exact_partition() -> None:
    value = "first\nsecond\n"

    with pytest.raises(ValueError, match="contiguous and ordered"):
        chunk_transcript_text(
            value,
            source_id="source",
            project_name="demo",
            client="codex",
            session_id="session",
            logical_units=[TranscriptLogicalUnit(1, len(value), "unit")],
        )
