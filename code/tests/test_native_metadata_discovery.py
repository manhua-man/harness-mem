"""Synthetic discovery contracts: bounded headers and session-table reads only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import pytest

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.grok.adapter import GrokAdapter, grok_project_bucket
import harness_mem.adapters.hermes.adapter as hermes_module
from harness_mem.adapters.hermes.adapter import HermesAdapter
import harness_mem.adapters.opencode.adapter as opencode_module
from harness_mem.adapters.opencode.adapter import OpenCodeAdapter
from harness_mem.adapters.source_metadata import HEADER_BYTES


def _jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


@pytest.fixture
def metadata_only(monkeypatch):
    """Fail on complete file reads, native conversation parsers or exports."""
    real_open = Path.open
    reads: list[tuple[Path, int]] = []

    class PrefixReader:
        def __init__(self, path, stream):
            self.path, self.stream = path, stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert 0 <= size <= HEADER_BYTES, "discovery attempted an unbounded read"
            reads.append((self.path, size))
            return self.stream.read(size)

    def guarded_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if mode == "rb":
            return PrefixReader(path, stream)
        raise AssertionError("discovery must use bounded binary header reads")

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery parsed or exported a conversation")

    # Activate after fixture files have been created.
    def activate():
        monkeypatch.setattr(Path, "open", guarded_open)
        monkeypatch.setattr(Path, "read_text", forbidden)
        monkeypatch.setattr(Path, "read_bytes", forbidden)
        for client in ("codex", "claude_code", "grok", "hermes", "opencode"):
            module = __import__(f"harness_mem.adapters.{client}.adapter", fromlist=["adapter"])
            for name in (
                "list_session_files", "parse_codex_archive_jsonl_session", "render_codex_conversation",
                "parse_claude_jsonl_session", "parse_grok_jsonl_session", "parse_hermes_json_session",
                "read_hermes_session_id", "_export_state_db_session", "_export_session",
            ):
                if hasattr(module, name):
                    monkeypatch.setattr(module, name, forbidden)
    return activate, reads


def _guard_sql(monkeypatch, module, table):
    connect = module._connect_readonly
    reads: list[str] = []

    def guarded(path):
        connection = connect(path)

        def authorize(action, name, column, database, source):
            if action == sqlite3.SQLITE_READ:
                reads.append(name)
                return sqlite3.SQLITE_OK if name == table else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(module, "_connect_readonly", guarded)
    return reads


def _hermes_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions (id TEXT, title TEXT, started_at REAL, ended_at REAL,
                                   git_repo_root TEXT, cwd TEXT, archived INTEGER);
            CREATE TABLE messages (session_id TEXT, content TEXT);
        """)


def _opencode_db(path: Path, root: str, session_id="selected"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE session (id TEXT, directory TEXT, title TEXT,
                                  time_created INTEGER, time_updated INTEGER);
            CREATE TABLE message (session_id TEXT, data TEXT);
            CREATE TABLE part (session_id TEXT, data TEXT);
        """)
        db.execute("INSERT INTO session VALUES (?, ?, ?, 1000, 2000)", (session_id, root, "Title"))
        db.execute("INSERT INTO message VALUES (?, ?)", (session_id, '{"cwd":"/message-root"}'))


def test_codex_metadata_merges_current_archive_and_uses_only_structured_headers(tmp_path, metadata_only):
    current, archive = tmp_path / "sessions", tmp_path / "archived_sessions"
    root, other = str(tmp_path / "repo"), str(tmp_path / "other")
    path = _jsonl(current / "2026" / "rollout-current.jsonl", [
        {"type": "session_meta", "payload": {"id": "shared", "cwd": root}},
        {"type": "response_item", "payload": {"cwd": other, "content": "x" * 200_000}},
    ])
    copy = _jsonl(archive / "rollout-copy.jsonl", [{"type": "session_meta", "payload": {"id": "shared", "cwd": other}}])
    _jsonl(archive / "rollout-old.jsonl", [{"type": "session_meta", "payload": {"id": "old", "cwd": root}}])
    _jsonl(current / "rollout-unbound.jsonl", [{"type": "response_item", "payload": {"cwd": root}}])
    _jsonl(current / "rollout-ambiguous.jsonl", [
        {"type": "session_meta", "payload": {"id": "ambiguous", "cwd": root}},
        {"type": "turn_context", "payload": {"cwd": other}},
    ])
    activate, reads = metadata_only
    activate()
    adapter = CodexAdapter(None, sessions_dir=current, archive_dir=archive, scope="all")
    discovered = adapter.list_session_metadata()
    records = {record["session_id"]: record for record in discovered}
    # The same native id may identify different continuations or source roots.
    # Discovery preserves both locators; only complete-byte validation can
    # establish whether they are identical copies.
    assert len(discovered) == 5
    assert len(records) == 4
    shared = {record["path"]: record for record in discovered if record["session_id"] == "shared"}
    assert set(shared) == {path, copy}
    assert shared[path]["metadata_paths"] == [path]
    assert shared[path]["project_roots"] == [root]
    assert shared[path]["source_kind"] == "codex-current"
    assert shared[copy]["metadata_paths"] == [copy]
    assert shared[copy]["project_roots"] == [other]
    assert shared[copy]["source_kind"] == "codex-archive"
    assert records["old"]["source_kind"] == "codex-archive"
    for key in ("unbound", "ambiguous"):
        assert records[key]["metadata_status"] == "unknown"
        assert "cwd" not in records[key]
    assert reads and all(size == HEADER_BYTES for _, size in reads)
    assert not any("lines" in record or "source_status" in record for record in records.values())
    assert len(adapter.list_session_metadata(limit=1)) == 1
    assert adapter.list_session_metadata(min_size_kb=1000) == []


def test_codex_turn_context_fallback_and_project_scope(tmp_path, metadata_only):
    root = tmp_path / "repo"
    sessions = tmp_path / "sessions"
    _jsonl(sessions / "rollout-context.jsonl", [{"type": "turn_context", "payload": {"cwd": str(root)}}])
    _jsonl(sessions / "rollout-spoof.jsonl", [{"type": "event_msg", "payload": {"cwd": str(root)}}])
    metadata_only[0]()
    records = CodexAdapter(None, sessions_dir=sessions, project_root=root).list_session_metadata()
    assert [record["session_id"] for record in records] == ["context"]


def test_claude_metadata_does_not_use_lossy_bucket_or_message_paths(tmp_path, metadata_only):
    sessions, root = tmp_path / "projects", str(tmp_path / "repo")
    _jsonl(sessions / "lossy-bucket" / "native-id.jsonl", [
        {"type": "user", "cwd": root, "message": {"content": "hello"}},
        {"type": "assistant", "message": {"cwd": "/false", "content": "x" * 200_000}},
    ])
    _jsonl(sessions / "another-bucket" / "unbound.jsonl", [
        {"type": "user", "message": {"content": root, "cwd": root}, "tools": [{"cwd": root}]},
    ])
    _jsonl(sessions / "lossy-bucket" / "ambiguous.jsonl", [{"cwd": root}, {"cwd": str(tmp_path / "other")}])
    metadata_only[0]()
    records = {r["session_id"]: r for r in ClaudeCodeAdapter(None, sessions_dir=sessions).list_session_metadata()}
    assert len(records) == 3
    assert records["native-id"]["project_roots"] == [root]
    assert records["native-id"]["metadata_paths"] == [records["native-id"]["path"]]
    assert records["unbound"]["project_roots"] == []
    assert records["unbound"]["metadata_status"] == records["ambiguous"]["metadata_status"] == "unknown"


def test_grok_metadata_decodes_only_full_path_buckets_and_checks_headers(tmp_path, metadata_only):
    sessions, root, other = tmp_path / "sessions", tmp_path / "repo", tmp_path / "repo-other"
    bucket = sessions / grok_project_bucket(root.resolve())
    _jsonl(bucket / "good" / "chat_history.jsonl", [
        {"type": "user", "content": str(other), "tools": [{"cwd": str(other)}]},
        {"type": "assistant", "content": "x" * 200_000},
    ])
    _jsonl(bucket / "conflict" / "chat_history.jsonl", [{"cwd": str(other)}])
    _jsonl(sessions / "lossy-repo" / "unknown" / "chat_history.jsonl", [{"content": str(root)}])
    _jsonl(sessions / grok_project_bucket(other.resolve()) / "other" / "chat_history.jsonl", [{"cwd": str(other)}])
    metadata_only[0]()
    records = {r["session_id"]: r for r in GrokAdapter(None, sessions_dir=sessions).list_session_metadata()}
    assert len(records) == 4
    assert records["good"]["project_roots"] == [str(root.resolve())]
    assert records["good"]["metadata_paths"] == [records["good"]["path"]]
    assert records["conflict"]["metadata_status"] == records["unknown"]["metadata_status"] == "unknown"
    scoped = GrokAdapter(None, sessions_dir=sessions, project_root=root).list_session_metadata()
    assert [r["session_id"] for r in scoped] == ["good"]


def test_hermes_metadata_json_prefix_never_decodes_messages(tmp_path, metadata_only):
    sessions, root, cwd = tmp_path / "sessions", str(tmp_path / "repo"), str(tmp_path / "repo" / "subdir")
    sessions.mkdir()
    (sessions / "session_copy.json").write_text(json.dumps({
        "session_id": "native-id", "git_repo_root": root, "cwd": cwd,
        "messages": [{"cwd": "/false", "content": "x" * 200_000}],
    }), encoding="utf-8")
    (sessions / "session_unbound.json").write_text(json.dumps({
        "session_id": "unbound", "messages": [{"cwd": root, "content": root}],
    }), encoding="utf-8")
    (sessions / "session_ambiguous.json").write_text(json.dumps({
        "session_id": "ambiguous", "cwd": root, "git_repo_root": str(tmp_path / "other"), "messages": [],
    }), encoding="utf-8")
    metadata_only[0]()
    records = {r["session_id"]: r for r in HermesAdapter(None, sessions_dir=sessions).list_session_metadata()}
    assert records["native-id"]["project_roots"] == [root]
    assert records["native-id"]["metadata_paths"] == [records["native-id"]["path"]]
    assert records["native-id"]["metadata_status"] == "available"
    assert records["unbound"]["project_roots"] == []
    assert records["ambiguous"]["metadata_status"] == "unknown"
    scoped = HermesAdapter(None, sessions_dir=sessions, project_root=Path(root)).list_session_metadata()
    assert [r["session_id"] for r in scoped] == ["native-id"]


def test_hermes_metadata_includes_archived_sql_rows_and_preserves_both_bindings(tmp_path, monkeypatch, metadata_only):
    path, root, cwd = tmp_path / "state.db", str(tmp_path / "repo"), str(tmp_path / "repo" / "sub")
    _hermes_db(path)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO sessions VALUES (?, ?, 1, 2, ?, ?, ?)", [
            ("archived", "Archived", root, cwd, 1),
            ("unknown", "Unbound", None, None, 0),
            ("conflict", "Conflict", root, str(tmp_path / "other"), 0),
        ])
        db.execute("INSERT INTO messages VALUES (?, ?)", ("unknown", root))
    adapter = HermesAdapter(None, sessions_dir=tmp_path / "sessions", state_db=path)
    reads = _guard_sql(monkeypatch, hermes_module, "sessions")
    metadata_only[0]()
    records = {r["session_id"]: r for r in adapter.list_session_metadata()}
    assert set(records) == {"archived", "unknown", "conflict"}
    assert records["archived"]["project_roots"] == [root]
    assert records["archived"]["source_kind"] == "sqlite-session-export"
    assert records["archived"]["metadata_paths"] == [path, path.with_name("state.db-wal")]
    assert records["unknown"]["metadata_status"] == records["conflict"]["metadata_status"] == "unknown"
    assert set(reads) == {"sessions"}
    # Manual history discovery must not change automatic archived-session policy.
    assert "archived" not in {r["session_id"] for r in adapter.list_sessions()}


def test_hermes_metadata_active_profile_json_and_db_override(tmp_path, monkeypatch, metadata_only):
    profile, other = tmp_path / "active", tmp_path / "other"
    root = str(tmp_path / "repo")
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.delenv("HERMES_STATE_DB", raising=False)
    (profile / "sessions").mkdir(parents=True)
    (profile / "sessions" / "session_json.json").write_text(json.dumps({"session_id": "copy", "cwd": root}), encoding="utf-8")
    _hermes_db(profile / "state.db")
    _hermes_db(other / "state.db")
    with sqlite3.connect(profile / "state.db") as db:
        db.execute("INSERT INTO sessions VALUES ('copy', 'DB wins', 1, 2, ?, ?, 1)", (root, root))
    with sqlite3.connect(other / "state.db") as db:
        db.execute("INSERT INTO sessions VALUES ('override', '', 1, 2, ?, ?, 0)", (root, root))
    adapter = HermesAdapter(None, home_dir=tmp_path)
    assert adapter.sessions_dir == profile / "sessions"
    assert adapter.state_db == profile / "state.db"
    # Resolve the active profile at construction, even after module import.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    default_adapter = HermesAdapter(None)
    assert default_adapter.sessions_dir == profile / "sessions"
    assert default_adapter.state_db == profile / "state.db"
    metadata_only[0]()
    records = adapter.list_session_metadata()
    assert len(records) == 1 and records[0]["path"] == profile / "state.db"
    monkeypatch.setenv("HERMES_STATE_DB", str(other / "state.db"))
    overridden = HermesAdapter(None, home_dir=tmp_path)
    assert overridden.sessions_dir == profile / "sessions"
    assert {r["session_id"] for r in overridden.list_session_metadata()} == {"copy", "override"}
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-profile"))
    monkeypatch.delenv("HERMES_STATE_DB")
    assert HermesAdapter(None, home_dir=tmp_path).list_session_metadata() == []


def test_hermes_metadata_retains_historical_json_root(tmp_path, monkeypatch, metadata_only):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_STATE_DB", raising=False)
    active = tmp_path / "AppData" / "Local" / "hermes"
    monkeypatch.setattr(hermes_module, "default_hermes_home", lambda: active)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for base, session_id in ((active, "current"), (tmp_path / ".hermes", "historical")):
        (base / "sessions").mkdir(parents=True)
        (base / "sessions" / f"session_{session_id}.json").write_text(
            json.dumps({"session_id": session_id, "cwd": str(tmp_path / "repo")}), encoding="utf-8",
        )
    metadata_only[0]()
    records = HermesAdapter(None).list_session_metadata()
    assert {r["session_id"] for r in records} == {"current", "historical"}


def test_opencode_metadata_only_selected_database_session_table(tmp_path, monkeypatch, metadata_only):
    root = str(tmp_path / "repo")
    older, selected = tmp_path / ".local/share/opencode/opencode.db", tmp_path / ".local/share/opencode/opencode-beta.db"
    _opencode_db(older, root, "older-profile")
    _opencode_db(selected, root)
    os.utime(older, (100, 100))
    os.utime(selected, (200, 200))
    with sqlite3.connect(selected) as db:
        db.execute("INSERT INTO session VALUES ('unbound', NULL, 'Unknown', 1000, 3000)")
    reads = _guard_sql(monkeypatch, opencode_module, "session")
    metadata_only[0]()
    adapter = OpenCodeAdapter(None, home_dir=tmp_path)
    assert adapter.database_path == selected
    records = {r["session_id"]: r for r in adapter.list_session_metadata()}
    assert set(records) == {"selected", "unbound"}
    assert records["selected"]["project_roots"] == [root]
    assert records["selected"]["metadata_paths"] == [selected, selected.with_name(selected.name + "-wal")]
    assert records["unbound"]["metadata_status"] == "unknown"
    assert set(reads) == {"session"}
    assert OpenCodeAdapter(None, database_path=selected, project_root=Path(root)).list_session_metadata()[0]["session_id"] == "selected"
    assert OpenCodeAdapter(None, database_path=older).list_session_metadata()[0]["session_id"] == "older-profile"


@pytest.mark.parametrize("client", ["hermes", "opencode"])
def test_sqlite_metadata_dependencies_include_wal_changes(client, tmp_path, metadata_only):
    path, root, other = tmp_path / "native.db", str(tmp_path / "repo"), str(tmp_path / "other")
    if client == "hermes":
        _hermes_db(path)
        adapter = HermesAdapter(None, sessions_dir=tmp_path / "sessions", state_db=path)
    else:
        _opencode_db(path, root)
        adapter = OpenCodeAdapter(None, database_path=path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        if client == "hermes":
            writer.execute("INSERT INTO sessions VALUES ('selected', '', 1, 2, ?, ?, 0)", (root, root))
        writer.commit()
        metadata_only[0]()
        first = adapter.list_session_metadata()[0]
        wal = path.with_name(path.name + "-wal")
        assert wal in first["metadata_paths"] and wal.is_file()
        database_stat = (path.stat().st_mtime_ns, path.stat().st_size)
        if client == "hermes":
            writer.execute("UPDATE sessions SET cwd = ?, git_repo_root = ?", (other, other))
        else:
            writer.execute("UPDATE session SET directory = ?", (other,))
        writer.commit()
        second = adapter.list_session_metadata()[0]
        assert first["project_roots"] == [root] and second["project_roots"] == [other]
        assert (path.stat().st_mtime_ns, path.stat().st_size) == database_stat
    finally:
        writer.close()


@pytest.mark.parametrize("client", ["codex", "claude", "grok", "hermes", "opencode"])
def test_metadata_discovery_has_only_explicit_count_limit(client, tmp_path, metadata_only):
    root, sessions = str(tmp_path / "repo"), tmp_path / "sessions"
    count = 137
    if client == "opencode":
        path = tmp_path / "opencode.db"
        _opencode_db(path, root, "0")
        with sqlite3.connect(path) as db:
            db.executemany("INSERT INTO session VALUES (?, ?, '', 1000, 2000)", [(str(i), root) for i in range(1, count)])
        adapter = OpenCodeAdapter(None, database_path=path)
    else:
        for i in range(count):
            if client == "codex":
                _jsonl(sessions / f"rollout-{i}.jsonl", [{"type": "session_meta", "payload": {"id": str(i), "cwd": root}}])
            elif client == "claude":
                _jsonl(sessions / "bucket" / f"{i}.jsonl", [{"cwd": root}])
            elif client == "grok":
                _jsonl(sessions / grok_project_bucket(Path(root)) / str(i) / "chat_history.jsonl", [{"cwd": root}])
            else:
                sessions.mkdir(exist_ok=True)
                (sessions / f"session_{i}.json").write_text(json.dumps({"session_id": str(i), "cwd": root}), encoding="utf-8")
        adapter = {
            "codex": CodexAdapter, "claude": ClaudeCodeAdapter,
            "grok": GrokAdapter, "hermes": HermesAdapter,
        }[client](None, sessions_dir=sessions)
    metadata_only[0]()
    assert len(adapter.list_session_metadata()) == count
    assert len(adapter.list_session_metadata(limit=3)) == 3
    assert adapter.list_session_metadata(limit=0) == []
    assert adapter.list_session_metadata(min_size_kb=1_000_000) == []


@pytest.mark.parametrize("client", ["codex", "claude", "grok"])
def test_incomplete_prefix_record_cannot_bind_owner(client, tmp_path, metadata_only):
    root, sessions = str(tmp_path / "repo"), tmp_path / "sessions"
    if client == "codex":
        path = sessions / "rollout-oversized.jsonl"
        record = {"type": "session_meta", "payload": {"cwd": root, "extra": "x" * 200_000}}
        adapter = CodexAdapter(None, sessions_dir=sessions)
    elif client == "claude":
        path, record = sessions / "bucket" / "oversized.jsonl", {"cwd": root, "extra": "x" * 200_000}
        adapter = ClaudeCodeAdapter(None, sessions_dir=sessions)
    else:
        path = sessions / "unbound-bucket" / "oversized" / "chat_history.jsonl"
        record = {"cwd": root, "extra": "x" * 200_000}
        adapter = GrokAdapter(None, sessions_dir=sessions)
    _jsonl(path, [record])
    metadata_only[0]()
    records = adapter.list_session_metadata()
    assert len(records) == 1
    assert records[0]["project_roots"] == []
    assert records[0]["metadata_status"] == "unknown"
