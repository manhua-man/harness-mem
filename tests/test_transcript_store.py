from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3

import pytest

from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.storage.transcript_store import TranscriptStore
from harness_mem.transcript_chunking import (
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
    transcript_bytes_revision,
    transcript_source_id,
)


def _snapshot(value: str) -> tuple[TranscriptSource, list]:
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id="session-1",
    )
    native_bytes = value.encode("utf-8")
    revision = transcript_bytes_revision(native_bytes)
    source = TranscriptSource(
        id=source_id,
        project_name="demo",
        project_root="C:/work/demo",
        client="cursor",
        session_id="session-1",
        source_kind="file",
        source_uri="file:///C:/transcripts/session-1.jsonl",
        source_revision=revision,
        raw_sha256=sha256_bytes(native_bytes),
        normalized_sha256=sha256_text(value),
        raw_size_bytes=len(native_bytes),
        normalized_size_bytes=len(native_bytes),
        status="syncing",
    )
    chunks = chunk_transcript_text(
        value,
        source_id=source_id,
        project_name="demo",
        client="cursor",
        session_id="session-1",
        source_revision=revision,
        max_chars=16,
    )
    return source, chunks


def test_snapshot_round_trips_and_updates_current_revision(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    first_source, first_chunks = _snapshot("turn one\nanswer one\n")
    second_source, second_chunks = _snapshot(
        "turn one\nanswer one\nturn two\nanswer two\n"
    )

    store.save_snapshot(first_source, first_chunks)
    store.save_snapshot(second_source, second_chunks)

    current = store.find_source(
        project_name="demo",
        client="cursor",
        session_id="session-1",
    )
    assert current is not None
    assert current.source_revision == second_source.source_revision
    assert current.coverage == "complete"
    assert store.reconstruct(current.id) == (
        "turn one\nanswer one\nturn two\nanswer two\n"
    )
    assert store.reconstruct(
        current.id,
        source_revision=first_source.source_revision,
    ) == "turn one\nanswer one\n"
    assert store.reconstruct_raw(
        current.id,
        source_revision=first_source.source_revision,
    ) == b"turn one\nanswer one\n"
    assert len(store.list_revisions(current.id)) == 2
    store.close()


def test_snapshot_validation_rolls_back_incomplete_write(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source, chunks = _snapshot("complete transcript\n")

    with pytest.raises(ValueError, match="content hash"):
        store.save_snapshot(source, chunks[:-1])

    assert store.get_source(source.id) is None
    store.close()


def test_raw_bytes_preserve_bom_crlf_and_invalid_utf8(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    raw = b"\xef\xbb\xbfuser: one\r\nassistant: bad-utf8-\xff\r\n"
    normalized = raw.decode("utf-8-sig", errors="replace")
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id="raw-session",
    )
    revision = transcript_bytes_revision(raw)
    source = TranscriptSource(
        id=source_id,
        project_name="demo",
        project_root="C:/work/demo",
        client="cursor",
        session_id="raw-session",
        source_kind="file",
        source_uri="file:///raw.jsonl",
        source_revision=revision,
        raw_sha256=sha256_bytes(raw),
        normalized_sha256=sha256_text(normalized),
        raw_size_bytes=len(raw),
        normalized_size_bytes=len(normalized.encode("utf-8")),
        status="syncing",
    )
    chunks = chunk_transcript_text(
        normalized,
        source_id=source_id,
        project_name="demo",
        client="cursor",
        session_id="raw-session",
        source_revision=revision,
        max_chars=10,
    )

    store.save_snapshot(source, chunks, raw_bytes=raw)

    assert store.reconstruct_raw(source_id) == raw
    assert store.reconstruct(source_id) == normalized
    store.close()


def test_backend_exposes_transcript_store(tmp_path: Path) -> None:
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()

        assert backend.transcript_store.list_sources() == []

        await backend.close()

    asyncio.run(exercise())


def test_missing_inventory_marks_source_without_deleting_revision(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source, chunks = _snapshot("retained transcript\n")
    store.save_snapshot(source, chunks)

    missing = store.mark_sources_missing_from_inventory(
        project_name="demo",
        client="cursor",
        observed_session_ids=set(),
    )

    assert [item.id for item in missing] == [source.id]
    current = store.get_source(source.id)
    assert current is not None
    assert current.status == "missing"
    assert current.metadata["missing_reason"] == "absent_from_complete_host_inventory"
    assert store.reconstruct_raw(source.id) == b"retained transcript\n"

    store.save_snapshot(source, chunks)
    restored = store.get_source(source.id)
    assert restored is not None
    assert restored.status == "synced"
    store.close()


def test_legacy_v1_ledger_migrates_without_losing_content(tmp_path: Path) -> None:
    db_path = tmp_path / "transcript_ledger.sqlite"
    value = "legacy transcript\n"
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id="legacy",
    )
    revision = transcript_bytes_revision(value.encode("utf-8"))
    chunks = chunk_transcript_text(
        value,
        source_id=source_id,
        project_name="demo",
        client="cursor",
        session_id="legacy",
        source_revision=revision,
    )
    old_source = {
        "id": source_id,
        "project_name": "demo",
        "project_root": "C:/work/demo",
        "client": "cursor",
        "session_id": "legacy",
        "source_kind": "file",
        "source_uri": "file:///legacy.jsonl",
        "source_revision": revision,
        "content_sha256": sha256_text(value),
        "size_bytes": len(value.encode("utf-8")),
        "status": "synced",
        "coverage": "complete",
        "chunk_count": len(chunks),
    }
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE transcript_sources (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            client TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE transcript_chunks (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO transcript_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            source_id,
            "demo",
            "cursor",
            "legacy",
            revision,
            "synced",
            "2026-01-01T00:00:00+00:00",
            json.dumps(old_source),
        ),
    )
    for chunk in chunks:
        conn.execute(
            "INSERT INTO transcript_chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chunk.id,
                chunk.source_id,
                chunk.source_revision,
                chunk.chunk_index,
                chunk.content_sha256,
                chunk.size_bytes,
                json.dumps(chunk.to_dict()),
            ),
        )
    conn.commit()
    conn.close()

    store = TranscriptStore(tmp_path)

    assert store.reconstruct(source_id) == value
    assert store.reconstruct_raw(source_id) == value.encode("utf-8")
    assert store.get_source(source_id).metadata["migrated_from_ledger_v1"] is True
    store.close()


def test_newer_ledger_schema_is_rejected(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "transcript_ledger.sqlite")
    conn.execute("PRAGMA user_version=999")
    conn.close()

    with pytest.raises(RuntimeError, match="newer"):
        TranscriptStore(tmp_path)
