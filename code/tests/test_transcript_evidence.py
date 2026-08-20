from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from harness_mem.commands.integration_cmds import cmd_transcript_evidence
from harness_mem.transcript_evidence import (
    TranscriptEvidence,
    collect_transcript_evidence,
    render_transcript_evidence,
)


def test_collect_transcript_evidence_verifies_grok_project_bucket(
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / "repo").resolve()
    project_root.mkdir()
    home = tmp_path / "home"
    bucket = home / ".grok" / "sessions" / quote(str(project_root), safe="")
    first_session = bucket / "session-1"
    second_session = bucket / "session-2"
    first_session.mkdir(parents=True)
    second_session.mkdir(parents=True)
    (first_session / "chat_history.jsonl").write_text(
        '{"type":"user","content":"hello"}\n',
        encoding="utf-8",
    )
    (second_session / "chat_history.jsonl").write_text(
        '{"type":"assistant","content":"world"}\n',
        encoding="utf-8",
    )

    report = collect_transcript_evidence(
        project_root,
        clients=("grok",),
        home_dir=home,
        sample_limit=1,
    )[0]

    assert report.client == "grok"
    assert report.status == "verified_transcript_path"
    assert report.session_count == 2
    assert len(report.sample_files) == 1
    assert report.sample_files[0].name == "chat_history.jsonl"
    assert report.adapter_available is True


def test_collect_transcript_evidence_keeps_unknown_hosts_unavailable(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".hermes" / "sessions").mkdir(parents=True)

    hermes, opencode = collect_transcript_evidence(
        tmp_path,
        clients=("hermes", "opencode"),
        home_dir=home,
    )

    assert hermes.status == "insufficient_evidence"
    assert hermes.adapter_available is True
    assert "no verified JSON or SQLite transcript schema" in hermes.note
    assert opencode.status == "missing"
    assert opencode.adapter_available is True


def test_collect_transcript_evidence_verifies_hermes_session_schema(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sessions_root = home / ".hermes" / "sessions"
    sessions_root.mkdir(parents=True)
    session_file = sessions_root / "session_20260711_abcd.json"
    session_file.write_text(
        json.dumps(
            {
                "session_id": "session_20260711_abcd",
                "model": "test-model",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ],
                "message_count": 2,
            }
        ),
        encoding="utf-8",
    )

    report = collect_transcript_evidence(
        tmp_path,
        clients=("hermes",),
        home_dir=home,
    )[0]

    assert report.client == "hermes"
    assert report.status == "verified_transcript_path"
    assert report.session_count == 1
    assert report.sample_files == (session_file,)
    assert report.adapter_available is True
    assert "session_id and messages[]" in report.note


def test_collect_transcript_evidence_rejects_invalid_hermes_session(tmp_path: Path) -> None:
    home = tmp_path / "home"
    sessions_root = home / ".hermes" / "sessions"
    sessions_root.mkdir(parents=True)
    (sessions_root / "session_20260711_abcd.json").write_text(
        json.dumps({"session_id": "session_20260711_abcd", "messages": []}),
        encoding="utf-8",
    )

    report = collect_transcript_evidence(
        tmp_path,
        clients=("hermes",),
        home_dir=home,
    )[0]

    assert report.status == "insufficient_evidence"
    assert report.session_count == 0
    assert report.sample_files == ()


def test_collect_transcript_evidence_verifies_hermes_state_db(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state_db = home / "AppData" / "Local" / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    with sqlite3.connect(state_db) as db:
        db.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                started_at REAL,
                ended_at REAL,
                message_count INTEGER,
                cwd TEXT,
                git_repo_root TEXT,
                model TEXT,
                archived INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_name TEXT,
                active INTEGER DEFAULT 1
            );
            INSERT INTO sessions VALUES (
                'hermes-db', 'Hermes DB', 'cli', 1700000000, 1700000100,
                1, 'F:/repo', 'F:/repo', 'test', 0
            );
            INSERT INTO messages (session_id, role, content, tool_name)
            VALUES ('hermes-db', 'user', 'hello', '');
            """
        )

    report = collect_transcript_evidence(
        tmp_path,
        clients=("hermes",),
        home_dir=home,
    )[0]

    assert report.status == "verified_transcript_path"
    assert report.session_count == 1
    assert report.sample_files == (state_db,)
    assert "state.db sessions/messages" in report.note


def test_collect_transcript_evidence_verifies_antigravity_cli_history(
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / "repo").resolve()
    project_root.mkdir()
    home = tmp_path / "home"
    history = home / ".gemini" / "antigravity-cli" / "history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        json.dumps(
            {
                "conversationId": "agy-session",
                "workspace": str(project_root),
                "display": "hello",
                "timestamp": 1_700_000_000_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = collect_transcript_evidence(
        project_root,
        clients=("antigravity",),
        home_dir=home,
    )[0]

    assert report.status == "verified_transcript_path"
    assert report.session_count == 1
    assert report.sample_files == (history,)
    assert "CLI history evidence" in report.note


def test_collect_transcript_evidence_keeps_opencode_config_only_insufficient(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    config_root = home / ".config" / "opencode"
    config_root.mkdir(parents=True)
    (config_root / "opencode.json").write_text("{}", encoding="utf-8")
    (config_root / "gstack.jsonc").write_text("{// config only\n}", encoding="utf-8")

    report = collect_transcript_evidence(
        tmp_path,
        clients=("opencode",),
        home_dir=home,
    )[0]

    assert report.client == "opencode"
    assert report.status == "insufficient_evidence"
    assert report.session_count == 0
    assert report.sample_files == ()
    assert report.adapter_available is True
    assert "no verified transcript path/schema" in report.note
    assert config_root in report.roots


def test_collect_transcript_evidence_reports_missing_opencode_roots(tmp_path: Path) -> None:
    report = collect_transcript_evidence(
        tmp_path,
        clients=("opencode",),
        home_dir=tmp_path / "home",
    )[0]

    assert report.status == "missing"
    assert report.session_count == 0
    assert report.sample_files == ()
    assert "No known OpenCode root" in report.note


def test_render_transcript_evidence_reports_adapter_separately(tmp_path: Path) -> None:
    report = TranscriptEvidence(
        client="grok",
        status="verified_transcript_path",
        adapter_available=False,
        roots=(tmp_path / ".grok" / "sessions",),
        session_count=3,
        sample_files=(tmp_path / "chat_history.jsonl",),
        note="Found local transcripts.",
    )

    out = render_transcript_evidence((report,))

    assert "grok: verified_transcript_path | adapter=unavailable" in out
    assert "sessions: 3" in out
    assert "sample:" in out
    assert "Found local transcripts." in out


def test_cmd_transcript_evidence_prints_report(monkeypatch, tmp_path: Path, capsys) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_collect(project_root: Path, *, clients):
        calls.append((project_root, tuple(clients)))
        return (
            TranscriptEvidence(
                client="grok",
                status="missing",
                adapter_available=False,
                roots=(tmp_path / ".grok",),
            ),
        )

    monkeypatch.setattr(
        "harness_mem.commands.integration_cmds.collect_transcript_evidence",
        fake_collect,
    )

    assert cmd_transcript_evidence("grok", str(tmp_path)) == 0

    out = capsys.readouterr().out
    assert "Transcript evidence:" in out
    assert "grok: missing | adapter=unavailable" in out
    assert calls == [(tmp_path.resolve(), ("grok",))]
