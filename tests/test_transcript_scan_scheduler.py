from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from harness_mem.adapters.protocol import SessionRecord
from harness_mem.adapters.scan_scheduler import (
    plan_session_scan,
    session_scan_key,
    sync_sessions_fairly,
)
from harness_mem.storage.transcript_store import TranscriptStore


def _session(root: Path, index: int) -> SessionRecord:
    path = root / f"session-{index:03d}.jsonl"
    return {
        "path": path,
        "name": path.name,
        "session_id": f"session-{index:03d}",
        "size_kb": 1.0,
        "size_bytes": 1024,
        "size": "1 KB",
        "lines": 1,
    }


def test_frontier_persists_and_continues_after_restart(tmp_path: Path) -> None:
    sessions = [_session(tmp_path, index) for index in range(10, 0, -1)]
    store = TranscriptStore(tmp_path / "data")
    first = plan_session_scan(
        store,
        project_name="demo",
        client="cursor",
        source_root=tmp_path,
        sessions=sessions,
        change_limit=5,
    )
    for session in first.sessions[:5]:
        first.mark_scanned(session)
    first.commit()
    first_cursor = first.frontier.cursor_key
    store.close()

    reopened = TranscriptStore(tmp_path / "data")
    second = plan_session_scan(
        reopened,
        project_name="demo",
        client="cursor",
        source_root=tmp_path,
        sessions=sessions,
        change_limit=5,
    )

    assert second.frontier.cursor_key == first_cursor
    assert session_scan_key(second.sessions[3]) != first_cursor
    reopened.close()


def test_backlog_progresses_while_new_recent_sessions_keep_arriving(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "data")
    sessions = [_session(tmp_path, index) for index in range(20, 0, -1)]
    original_keys = {session_scan_key(session) for session in sessions}
    backlog_scanned: set[str] = set()

    for tick in range(12):
        sessions.insert(0, _session(tmp_path, 100 + tick))
        plan = plan_session_scan(
            store,
            project_name="demo",
            client="cursor",
            source_root=tmp_path,
            sessions=sessions,
            change_limit=5,
        )
        for session in plan.sessions[:5]:
            plan.mark_scanned(session)
        backlog_scanned.update(
            key for key in plan.scanned_keys if key not in {
                session_scan_key(item) for item in sessions[:3]
            }
        )
        plan.commit()

    assert original_keys <= backlog_scanned | {
        session_scan_key(session) for session in sessions[:3]
    }
    store.close()


def test_change_limit_one_alternates_active_recent_and_backlog(tmp_path: Path) -> None:
    """A continually changing latest session cannot monopolize a one-item run."""

    store = TranscriptStore(tmp_path / "data")
    sessions = [_session(tmp_path, index) for index in range(8, 0, -1)]
    scanned: list[str] = []

    async def sync_one(session: SessionRecord) -> SimpleNamespace:
        scanned.append(str(session["session_id"]))
        return SimpleNamespace(action="updated")

    for _ in range(6):
        asyncio.run(
            sync_sessions_fairly(
                store,
                project_name="demo",
                client="cursor",
                source_root=tmp_path,
                sessions=sessions,
                change_limit=1,
                sync_session=sync_one,
            )
        )

    # The two newest records form the recent lane. A backlog source must still
    # receive a changed-session slot despite every candidate reporting changed.
    assert any(session_id not in {"session-008", "session-007"} for session_id in scanned)
    store.close()


def test_failed_source_waits_for_retry_window_without_blocking_backlog(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path / "data")
    sessions = [_session(tmp_path, index) for index in range(5, 0, -1)]
    failed = sessions[-1]
    first = plan_session_scan(
        store,
        project_name="demo",
        client="cursor",
        source_root=tmp_path,
        sessions=sessions,
        change_limit=2,
    )
    first.mark_failed(failed, ValueError("bad transcript"))
    first.commit()

    delayed = plan_session_scan(
        store,
        project_name="demo",
        client="cursor",
        source_root=tmp_path,
        sessions=sessions,
        change_limit=2,
    )
    assert session_scan_key(failed) not in {session_scan_key(item) for item in delayed.sessions}

    retry = delayed.frontier.retry_sources[session_scan_key(failed)]
    retry.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    delayed.commit()
    due = plan_session_scan(
        store,
        project_name="demo",
        client="cursor",
        source_root=tmp_path,
        sessions=sessions,
        change_limit=2,
    )
    assert session_scan_key(failed) in {session_scan_key(item) for item in due.sessions}
    due.mark_succeeded(failed)
    due.commit()

    recovered = store.get_scan_frontier(
        project_name="demo",
        client="cursor",
        source_root=tmp_path.resolve().as_posix().casefold(),
    )
    assert recovered is not None
    assert session_scan_key(failed) not in recovered.retry_sources
    store.close()
