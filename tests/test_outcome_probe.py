from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from harness_mem.outcome_probe import (
    _read_only_connection,
    inspect_distill_notes,
    inspect_retrieval_outcome,
)


def _job(*, session_id: str, completed_at: datetime, summary: str):
    return SimpleNamespace(
        id=f"job-{session_id}",
        session_id=session_id,
        status="completed",
        completed_at=completed_at,
        semantic_review={"session_summary": summary},
    )


def test_distill_note_probe_requires_real_meaningful_note(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    jobs = [
        _job(
            session_id="present-session",
            completed_at=now,
            summary="A sufficiently precise summary of the completed session.",
        ),
        _job(
            session_id="missing-session",
            completed_at=now,
            summary="Another sufficiently precise completed-session summary.",
        ),
    ]
    (tmp_path / "present-session.md").write_text(
        "# Session present-session\n\n## Scope\nUseful context.\n\n"
        "## Final outcome\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        jobs,
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["unique_completed_sessions"] == 2
    assert result["notes_meaningful"] == 1
    assert result["note_coverage"] == 0.5
    assert result["note_coverage_complete"] is False
    assert result["semantic_summary_coverage_complete"] is True


def test_retrieval_probe_requires_target_to_return_from_read_model(tmp_path: Path) -> None:
    database = tmp_path / "structured_index.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE memory_entries (
            id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            compacted INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            valid_to TEXT,
            superseded_by TEXT NOT NULL DEFAULT '[]'
        );
        CREATE VIRTUAL TABLE memory_entries_fts USING fts5(
            content, content='memory_entries', content_rowid='rowid'
        );
        INSERT INTO memory_entries (
            id, project_name, content, created_at, status
        ) VALUES (
            'memory-1', 'demo',
            'outcome-verifier requires direct runtime evidence',
            '2026-08-11T00:00:00+00:00', 'user_confirmed'
        );
        INSERT INTO memory_entries_fts(rowid, content)
        SELECT rowid, content FROM memory_entries;
        """
    )
    connection.commit()
    connection.close()

    result = inspect_retrieval_outcome(tmp_path, "demo")

    assert result["readable_truth_count"] == 1
    assert result["probe_attempted"] is True
    assert result["probe_hit"] is True
    assert result["target_id"] == "memory-1"

    read_only = _read_only_connection(database)
    try:
        try:
            read_only.execute("DELETE FROM memory_entries")
        except sqlite3.OperationalError as exc:
            assert "readonly" in str(exc).lower()
        else:
            raise AssertionError("outcome probe connection accepted a write")
    finally:
        read_only.close()
