from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, read_events, run, write_claude_session

pytestmark = pytest.mark.cli


def test_quickstart_initializes_and_saves_profile(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15.0.0", "react": "19.0.0"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert run(cli.cmd_quickstart("demo", client="skip", limit=5)) == 0
    assert (data_dir / "active_project.txt").read_text(encoding="utf-8").strip() == "demo"
    assert (data_dir / "profiles" / "demo.json").exists()


def test_quickstart_shows_recent_sessions_and_recommends_distill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        json.dumps({"dependencies": {"react": "19.0.0"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_quickstart("demo", client="auto", limit=5)) == 0

    captured = capsys.readouterr().out
    assert "Recent Claude Code sessions:" in captured
    assert "sess-recent-001" in captured
    assert "📍 Phase:" in captured
    assert "harness-mem ds" in captured


def test_quickstart_auto_does_not_ingest_global_codex_sessions(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    (codex_sessions_root / "unrelated.jsonl").write_text(
        json.dumps({"role": "user", "content": "Worked on another repo entirely."}) + "\n",
        encoding="utf-8",
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_quickstart("demo", client="auto", limit=5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert observations == []
    finally:
        run(backend.close())

    captured = capsys.readouterr().out
    assert "Codex sessions (global): 1" in captured
    assert "Auto-ingest skipped for Codex" in captured
    assert "Ingesting codex sessions" not in captured


def test_doctor_reports_uninitialized_state(capsys: pytest.CaptureFixture[str]):
    assert run(cli.cmd_doctor("demo")) == 1
    captured = capsys.readouterr().out
    assert "Initialized: no" in captured
    assert "code: HM-001" in captured
    assert "quickstart" in captured


def test_doctor_reports_missing_project_context(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    data_dir.mkdir(parents=True, exist_ok=True)

    assert run(cli.cmd_doctor()) == 0
    captured = capsys.readouterr().out
    assert "📍 Phase: No Project Selected" in captured
    assert "code: HM-002" in captured
    assert "harness-mem use <project-name>" in captured


def test_doctor_shows_recent_sessions_and_recommends_wake(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="sess-recent-001",
                    client="claude-code",
                    raw_content="Worked on the SQLite search migration.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session"],
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Use SQLite FTS5 for local search.",
                    source="session:sess-recent-001",
                    tags=["search"],
                )
            )
        )
    finally:
        run(backend.close())

    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr().out
    assert "Recent Claude Code sessions:" in captured
    assert "sess-recent-001" in captured
    assert "📍 Phase:" in captured
    assert "harness-mem wake" in captured


def test_doctor_reports_memory_quality_counts(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    old_time = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Old memory that has not been reused.",
                    source="manual",
                    created_at=old_time,
                    updated_at=old_time,
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="architecture",
                    content="Recently reused memory.",
                    source="manual",
                    usage_count=2,
                    last_accessed_at=datetime.now(timezone.utc),
                )
            )
        )
    finally:
        run(backend.close())

    assert run(cli.cmd_doctor("demo")) == 0
    captured = capsys.readouterr().out
    assert "Memory quality: 1 stale, 1 never accessed" in captured


def test_doctor_recommends_project_scoped_auto_ingest_for_codex_sessions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    assert cli.cmd_use("demo") == 0

    (codex_sessions_root / "unrelated.jsonl").write_text(
        json.dumps({"role": "user", "content": "Worked on another repo entirely."}) + "\n",
        encoding="utf-8",
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr().out
    assert "Codex sessions (global): 1" in captured
    assert "not project-scoped" in captured
    assert "harness-mem ingest auto -p demo -n 1" in captured
    assert "--scope all" in captured
    assert "Start by ingesting the newest session" not in captured


def test_doctor_codex_only_project_recommends_search_until_structured_memory_exists(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="codex-session-001",
                    client="codex",
                    raw_content="Worked on JWT expiry handling in the auth flow.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session", "codex"],
                )
            )
        )
    finally:
        run(backend.close())

    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr().out
    assert "Observations: 1" in captured
    assert "Memory entries: 0" in captured
    assert "harness-mem search <query>" in captured
    assert "wake-up needs structured memory" in captured
    assert "harness-mem wake" not in captured


def test_doctor_logs_next_step_event(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="sess-recent-001",
                    client="claude-code",
                    raw_content="Worked on the SQLite search migration.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session"],
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Use SQLite FTS5 for local search.",
                    source="session:sess-recent-001",
                    tags=["search"],
                )
            )
        )
    finally:
        run(backend.close())

    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_doctor("demo")) == 0

    events = read_events(data_dir)
    assert any(
        event["type"] == "next_step_shown"
        and event["command"] == "doctor"
        and event["next_step"] == "harness-mem wake"
        for event in events
    )
