from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from harness_mem.adapters.opencode import OpenCodeAdapter


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
            ("part-user", "msg-user", "ses-match", json.dumps({"type": "text", "text": "Fix the cache"})),
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

    adapter = OpenCodeAdapter(None, database_path=database, project_root=Path("F:/repo/app"))
    sessions = adapter.list_sessions()

    assert [session["session_id"] for session in sessions] == ["ses-match"]
    observation = adapter.session_to_observation(database, "ses-match", "app")
    assert observation.client == "opencode"
    assert "Fix the cache" in observation.raw_content
    assert "read" in observation.raw_content
    assert observation.metadata["opencode_session_id"] == "ses-match"
