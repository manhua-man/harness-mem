from __future__ import annotations

import pytest

from harness_mem.transcript_chunking import (
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
