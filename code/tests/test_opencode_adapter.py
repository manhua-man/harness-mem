from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from harness_mem.adapters.opencode import OpenCodeAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _build_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                directory TEXT NOT NULL,
                title TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                data TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
            ("ses-match", "F:/repo/app", "Matching work", 1000, 2000),
        )
        db.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
            ("ses-other", "F:/repo/other", "Other work", 1000, 3000),
        )
        db.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            (
                "msg-user",
                "ses-match",
                1000,
                json.dumps({"role": "user"}),
            ),
        )
        db.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            (
                "msg-assistant",
                "ses-match",
                1100,
                json.dumps({"role": "assistant"}),
            ),
        )
        db.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "part-user",
                "msg-user",
                "ses-match",
                json.dumps({"type": "text", "text": "Fix the cache"}),
            ),
        )
        db.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "part-tool",
                "msg-assistant",
                "ses-match",
                json.dumps({"type": "tool", "tool": "read"}),
            ),
        )


def test_opencode_reads_sqlite_sessions_scoped_by_directory(tmp_path: Path) -> None:
    database = tmp_path / "opencode.db"
    _build_database(database)

    adapter = OpenCodeAdapter(
        None, database_path=database, project_root=Path("F:/repo/app")
    )
    sessions = adapter.list_sessions()

    assert [session["session_id"] for session in sessions] == ["ses-match"]
    observation = adapter.session_to_observation(database, "ses-match", "app")
    assert observation.client == "opencode"
    assert "Fix the cache" in observation.raw_content
    assert "read" in observation.raw_content
    assert observation.metadata["opencode_session_id"] == "ses-match"


def test_opencode_normalizes_native_workspace_aliases(tmp_path: Path) -> None:
    database = tmp_path / "opencode.db"
    _build_database(database)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.mkdir()
    aliased_workspace = alias_parent / ".." / workspace.name
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE session SET directory = ? WHERE id = ?",
            (str(aliased_workspace), "ses-match"),
        )

    adapter = OpenCodeAdapter(
        None,
        database_path=database,
        project_root=workspace,
    )

    assert [session["session_id"] for session in adapter.list_sessions()] == [
        "ses-match"
    ]


def test_opencode_snapshots_complete_per_session_revisions(tmp_path: Path) -> None:
    async def exercise() -> None:
        database = tmp_path / "opencode.db"
        _build_database(database)
        long_tail = "message-start-" + "x" * 60_000 + "-message-end"
        with sqlite3.connect(database) as db:
            db.execute("ALTER TABLE message ADD COLUMN extra BLOB")
            db.execute(
                "UPDATE message SET data = ?, extra = ? WHERE id = ?",
                (
                    json.dumps({"role": "user", "content": long_tail}),
                    b"\x00\x01\xff",
                    "msg-user",
                ),
            )

        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = OpenCodeAdapter(
                backend,
                database_path=database,
                project_root=Path("F:/repo/app"),
            )
            first = await adapter.sync_session(database, "ses-match", "app")
            first_raw = backend.transcript_store.reconstruct_raw(first.source.id)
            first_observation = await backend.verbatim_store.get(first.observation_id)

            assert first.action == "ingested"
            assert b'"$sqlite_blob_base64":"AAH/"' in first_raw
            assert b'"session_id":"ses-other"' not in first_raw
            assert first_observation is not None
            assert "message-start-" in first_observation.raw_content
            assert "-message-end" in first_observation.raw_content
            assert len(first_observation.raw_content) > 50_000

            with sqlite3.connect(database) as db:
                db.execute(
                    "UPDATE session SET title = ?, time_updated = ? WHERE id = ?",
                    ("Unrelated revision", 4000, "ses-other"),
                )
            unchanged = await adapter.sync_session(database, "ses-match", "app")
            assert unchanged.action == "unchanged"
            assert (
                backend.transcript_store.reconstruct_raw(first.source.id) == first_raw
            )

            with sqlite3.connect(database) as db:
                db.execute(
                    "INSERT INTO part VALUES (?, ?, ?, ?)",
                    (
                        "part-user-tail",
                        "msg-user",
                        "ses-match",
                        json.dumps({"type": "text", "text": "new session tail"}),
                    ),
                )
                db.execute(
                    "UPDATE session SET time_updated = ? WHERE id = ?",
                    (5000, "ses-match"),
                )
            updated = await adapter.sync_session(database, "ses-match", "app")

            assert updated.action == "updated"
            assert updated.observation_id == first.observation_id
            assert (
                backend.transcript_store.reconstruct_raw(
                    first.source.id,
                    source_revision=first.source.source_revision,
                )
                == first_raw
            )
            assert b"new session tail" in backend.transcript_store.reconstruct_raw(
                updated.source.id
            )
            assert len(backend.transcript_store.list_revisions(updated.source.id)) == 2
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_opencode_ingest_scans_past_unchanged_recent_sessions(tmp_path: Path) -> None:
    async def exercise() -> None:
        database = tmp_path / "opencode.db"
        _build_database(database)
        with sqlite3.connect(database) as db:
            db.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                ("ses-older", "F:/repo/app", "Older work", 500, 1000),
            )

        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = OpenCodeAdapter(
                backend,
                database_path=database,
                project_root=Path("F:/repo/app"),
            )
            await adapter.sync_session(database, "ses-match", "app")

            result = await adapter.ingest("app", limit=1)

            assert result["sessions_found"] == 2
            assert result["candidate_sessions"] == 2
            assert result["ingested"] == 1
            assert result["updated"] == 0
            assert result["unchanged"] == 1
            assert result["skipped_existing"] == 1

            with sqlite3.connect(database) as db:
                db.execute(
                    "UPDATE part SET data = ? WHERE id = ?",
                    (
                        json.dumps({"type": "text", "text": "grown session"}),
                        "part-user",
                    ),
                )
                db.execute(
                    "UPDATE session SET time_updated = ? WHERE id = ?",
                    (6000, "ses-match"),
                )

            grown = await adapter.ingest("app", limit=1)
            assert grown["candidate_sessions"] == 1
            assert grown["ingested"] == 0
            assert grown["updated"] == 1
            assert grown["unchanged"] == 0
        finally:
            await backend.close()

    asyncio.run(exercise())
