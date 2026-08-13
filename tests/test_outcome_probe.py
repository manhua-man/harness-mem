from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from harness_mem.outcome_probe import (
    _read_only_connection,
    inspect_distill_notes,
    inspect_hook_outcome,
    inspect_retrieval_outcome,
)
from harness_mem.qualification.distill_outcome_probe import (
    run_distill_outcome_probe,
)
from harness_mem.hook_receipts import record_hook_execution


def _job(*, session_id: str, completed_at: datetime, summary: str):
    return SimpleNamespace(
        id=f"job-{session_id}",
        session_id=session_id,
        status="completed",
        completed_at=completed_at,
        semantic_review={"session_summary": summary},
    )


def test_hook_probe_accepts_fresh_interleaved_codex_actions(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    hook_file = project_root / ".codex" / "hooks.json"
    hook_file.parent.mkdir()
    hook_file.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],'
        '"Stop":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "harness_mem.outcome_probe.collect_hook_file_statuses",
        lambda *_args, **_kwargs: [
            SimpleNamespace(exists=True, configured=True)
        ],
    )
    record_hook_execution(
        tmp_path,
        project_root=project_root,
        project_name="demo",
        client="codex",
        action="wake-start",
        trigger_id="session-a",
        source="native-hook",
    )
    record_hook_execution(
        tmp_path,
        project_root=project_root,
        project_name="demo",
        client="codex",
        action="post-turn-maintenance",
        trigger_id="session-b",
        source="native-hook",
    )

    result = inspect_hook_outcome(
        tmp_path,
        project_root=project_root,
        client="codex",
    )

    assert result["actions_verified"] is True
    assert result["session_pair_status"] == "mismatched"
    assert result["lifecycle_verified"] is False


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


def test_distill_note_probe_rejects_long_renderer_placeholder(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    job = _job(
        session_id="placeholder-session",
        completed_at=now,
        summary="The session topic could not be recovered from the available evidence.",
    )
    path = tmp_path / "revisions" / job.id / "placeholder-session.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# placeholder-session\n\n## 会话主题\nRecovered topic.\n\n"
        "## 最终结果\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        [job],
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["semantic_summaries_meaningful"] == 0
    assert result["semantic_summary_coverage_complete"] is False
    assert result["notes"][0]["semantic_summary_present"] is False


def test_distill_note_probe_prefers_latest_job_bound_revision_note(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    old_job = _job(
        session_id="growing-session",
        completed_at=now - timedelta(minutes=5),
        summary="The earlier revision completed a preliminary review.",
    )
    latest_job = _job(
        session_id="growing-session",
        completed_at=now,
        summary="The latest revision completed the final review independently.",
    )
    path = (
        tmp_path
        / "revisions"
        / latest_job.id
        / "growing-session.md"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Session growing-session\n\n## 会话主题\nUseful context.\n\n"
        "## 最终结果\n" + "Useful outcome.\n" * 30,
        encoding="utf-8",
    )

    result = inspect_distill_notes(
        [old_job, latest_job],
        notes_dir=tmp_path,
        since=now - timedelta(days=1),
    )

    assert result["unique_completed_sessions"] == 1
    assert result["note_coverage_complete"] is True
    assert result["notes"][0]["path"] == str(path)


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


def test_partial_distill_runtime_outcome_probe() -> None:
    result = run_distill_outcome_probe()

    assert result["verified"] is True
    assert result["partial_candidate_promoted"] is True
    assert result["handoff_job_bound"] is True
    assert result["dream_blocked_for_partial"] is True
    assert result["note_paths_distinct"] is True
