"""Synthetic native stores only; never discover a user's Cursor profile."""
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.cursor.sqlite_history import (
    PREFIX_SQL, enumerate_source_records, prefix_rows, read_pinned_source, workspace_owner,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def native(tmp_path, name="one"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "workspace.json").write_text(json.dumps({"folder": tmp_path.as_uri()}))
    database = directory / "state.vscdb"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        db.executemany("INSERT INTO cursorDiskKV VALUES (?, ?)", [
            ("composerData:s", '{ "composerId":"s", "fullConversationHeadersOnly":[{"bubbleId":"b"}], "extra":42 }'),
            ("bubbleId:s:b", '{"bubbleId":"b","text":"hello 世界","type":1,"unknown":{"all":true}}'),
            ("bubbleId:s:extra", '{"bubbleId":"extra","text":"unlisted preserved"}'),
        ])
    return database


def test_exact_serialized_values_and_pinned_read(tmp_path):
    database = native(tmp_path)
    before = database.read_bytes()
    source, = enumerate_source_records(database, project_root=tmp_path)
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT key, value FROM cursorDiskKV ORDER BY key").fetchall()
    assert sorted(map(tuple, json.loads(source.raw_bytes)["records"])) == rows
    assert source.record_count == 3
    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM cursorDiskKV")
    assert read_pinned_source(source) == source.raw_bytes
    assert not source.source_uri.startswith("file:")


@pytest.mark.parametrize("data", [
    {}, {"folder": "vscode-remote://ssh-remote/thing"},
    {"folder": "file://server/share"}, {"workspace": "file:///multi.code-workspace"},
    {"folder": "file:///x", "folders": []}, {"folder": 3},
])
def test_unknown_ownership(tmp_path, data):
    database = native(tmp_path)
    workspace = database.parent / "workspace.json"
    workspace.write_text(json.dumps(data))
    assert workspace_owner(workspace) is None
    issues = []
    source, = enumerate_source_records(database, issues=issues)
    assert source.owner is None
    assert issues[0]["code"] == "cursor_sqlite_ownership_unknown"


def test_encoded_uri_and_wrong_project(tmp_path):
    database = native(tmp_path)
    owner = tmp_path / "space 世界"
    (database.parent / "workspace.json").write_text(json.dumps({"folder": owner.as_uri()}))
    assert workspace_owner(database.parent / "workspace.json") == owner.resolve()
    issues = []
    assert enumerate_source_records(database, project_root=tmp_path, issues=issues) == []
    assert issues[0]["code"] == "cursor_sqlite_project_mismatch"


@pytest.mark.parametrize("mutation,code", [
    ("DROP TABLE cursorDiskKV", "cursor_sqlite_unsupported_schema"),
    ("UPDATE cursorDiskKV SET value='not json' WHERE key='composerData:s'", "corrupt_json"),
    ("UPDATE cursorDiskKV SET value='{}' WHERE key='composerData:s'", "cursor_sqlite_unsupported_composer"),
    ("DELETE FROM cursorDiskKV WHERE key='bubbleId:s:b'", "cursor_sqlite_incomplete_bubbles"),
])
def test_unsupported_and_corrupt_records(tmp_path, mutation, code):
    database = native(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute(mutation)
    issues = []
    assert enumerate_source_records(database, issues=issues) == []
    assert issues[0]["code"] == code


def test_corrupt_and_locked_database(tmp_path):
    database = native(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("BEGIN EXCLUSIVE")
        issues = []
        assert enumerate_source_records(database, issues=issues) == []
        assert issues[0]["code"] == "cursor_sqlite_unreadable"
    database.write_bytes(b"not a database")
    issues = []
    assert enumerate_source_records(database, issues=issues) == []
    assert issues[0]["code"] == "cursor_sqlite_unreadable"


def test_prefix_equivalence_and_index_plan(tmp_path):
    database = native(tmp_path)
    with sqlite3.connect(database) as db:
        db.executemany("INSERT INTO cursorDiskKV VALUES (?, '{}')", [
            (k,) for k in ["composerData:sa", "composerData_", "ComposerData:s",
                           "bubbleId:sa:b", "bubbleId:s:%", "bubbleId:s:_", "noise"]
        ])
        rows = db.execute("SELECT key, value FROM cursorDiskKV").fetchall()
        for prefix in ["composerData:", "bubbleId:s:", "bubbleId:s:%", "bubbleId:s:_"]:
            assert prefix_rows(db, prefix) == sorted(r for r in rows if r[0].startswith(prefix))
            plan = db.execute("EXPLAIN QUERY PLAN " + PREFIX_SQL,
                              (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1))).fetchall()
            assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plan)
            assert not any("SCAN cursorDiskKV" in row[3] for row in plan)


def test_wal_snapshot_is_consistent(tmp_path, monkeypatch):
    import harness_mem.adapters.cursor.sqlite_history as history
    database = native(tmp_path)
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    original = history.prefix_rows

    def racing(connection, prefix):
        result = original(connection, prefix)
        if prefix == "composerData:":
            writer.execute("DELETE FROM cursorDiskKV WHERE key='bubbleId:s:b'")
            writer.commit()
        return result

    monkeypatch.setattr(history, "prefix_rows", racing)
    try:
        source, = enumerate_source_records(database)
        assert b"hello" in source.raw_bytes
    finally:
        writer.close()


def test_identity_only_dedup_and_jsonl_overlap(tmp_path):
    first = native(tmp_path)
    second = native(tmp_path, "two")
    projects = tmp_path / "projects"
    transcript = projects / "anything" / "agent-transcripts" / "s" / "s.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"role":"user","message":{"content":"hello"}}\n')
    adapter = CursorAdapter(None, projects_dir=projects, sqlite_databases=(first, second))
    sessions = adapter.list_sessions()
    assert len(sessions) == 2  # identical native identity collapses, JSONL stays
    with sqlite3.connect(second) as db:
        db.execute("UPDATE cursorDiskKV SET value=replace(value,'hello','different')")
    assert len(adapter.list_sessions()) == 3


def test_revision_pipeline_exact_roundtrip(tmp_path, monkeypatch):
    from harness_mem.config.merge import MergedConfig
    import harness_mem.adapters.snapshot as snapshot
    monkeypatch.setattr(snapshot, "load_merged_config", lambda _: MergedConfig())
    database = native(tmp_path)
    source, = enumerate_source_records(database)

    async def run():
        backend = LocalMemoryBackend(tmp_path / "isolated-memory")
        await backend.init()
        try:
            adapter = CursorAdapter(backend, projects_dir=tmp_path / "absent",
                                    project_root=tmp_path, sqlite_databases=(database,))
            record, = adapter.list_sessions()
            result = await adapter.sync_session(record["path"], record["session_id"], "synthetic")
            assert backend.transcript_store.reconstruct_raw(result.source.id) == source.raw_bytes
            assert backend.transcript_store.reconstruct(result.source.id) == source.raw_bytes.decode()
            assert "native_cleanup_descriptor" not in result.source.metadata
            again = await adapter.sync_sqlite_source(source, "synthetic")
            assert again.action == "unchanged"
        finally:
            await backend.close()

    asyncio.run(run())


def test_read_api_unscoped_and_unknown_ownership(tmp_path):
    database = native(tmp_path)
    adapter = CursorAdapter(None, projects_dir=tmp_path / "absent", sqlite_databases=(database,))
    record, = adapter.list_sessions()
    assert record["cwd"] == str(tmp_path.resolve())
    result = adapter.read_session_source(record["path"], record["session_id"])
    assert result["project_roots"] == [str(tmp_path.resolve())]
    assert result["source_text"].encode() == result["raw_bytes"]
    (database.parent / "workspace.json").write_text('{"folder":"vscode-remote://host/work"}')
    record, = adapter.list_sessions()
    assert "cwd" not in record
    assert adapter.read_session_source(database, "s")["project_roots"] == []
    scoped = CursorAdapter(None, projects_dir=tmp_path / "absent", project_root=tmp_path,
                           sqlite_databases=(database,))
    assert scoped.list_sessions() == []


def test_unknown_schema_isolated_from_good_database(tmp_path):
    bad = native(tmp_path, "bad")
    good = native(tmp_path, "good")
    with sqlite3.connect(bad) as db:
        db.execute("DROP TABLE cursorDiskKV")
        db.execute("CREATE TABLE cursorDiskKV (key TEXT, value TEXT)")
    issues = []
    adapter = CursorAdapter(None, projects_dir=tmp_path / "absent", sqlite_databases=(bad, good))
    record, = adapter.list_sessions(issues=issues)
    assert record["path"] == good
    assert any(i["code"] == "cursor_sqlite_unsupported_key_index" for i in issues)


def test_read_jsonl_does_not_claim_slug_ownership(tmp_path):
    path = tmp_path / "slug.jsonl"
    path.write_bytes(b'{"role":"user"}\n')
    adapter = CursorAdapter(None, projects_dir=tmp_path, project_root=tmp_path)
    result = adapter.read_session_source(path, "slug")
    assert result["project_roots"] == []
    assert result["raw_bytes"] == path.read_bytes()
    with pytest.raises(ValueError, match="not pinned"):
        adapter.read_session_source(tmp_path / "state.vscdb", "s")


@pytest.mark.parametrize("platform,relative", [
    ("win32", "AppData/Roaming/Cursor/User"),
    ("darwin", "Library/Application Support/Cursor/User"),
    ("linux", ".config/Cursor/User"),
])
def test_default_discovery_isolated_known_roots(tmp_path, monkeypatch, platform, relative):
    import harness_mem.adapters.cursor.sqlite_history as history
    import harness_mem.adapters.cursor.adapter as module
    monkeypatch.setattr(history.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(module, "DEFAULT_PROJECTS_DIR", tmp_path / "projects")
    root = tmp_path / relative
    root.mkdir(parents=True)
    global_db = native(root, "globalStorage")
    (global_db.parent / "workspace.json").unlink()
    workspace_storage = root / "workspaceStorage"
    workspace_storage.mkdir()
    workspace_db = native(workspace_storage, "hash")
    (workspace_db.parent / "workspace.json").write_text(json.dumps({"folder": tmp_path.as_uri()}))
    with sqlite3.connect(workspace_db) as db:
        db.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO ItemTable VALUES (?, ?)",
                   ("composer.composerHeaders", '{"allComposers":[{"composerId":"s"}]}'))
        db.execute("DELETE FROM cursorDiskKV")
    assert set(history.discover_sqlite_databases()) == {global_db, workspace_db}
    adapter = CursorAdapter(None)
    record, = adapter.list_sessions()
    assert record["path"] == global_db
    assert adapter.read_session_source(global_db, "s")["project_roots"] == [str(tmp_path)]
    assert adapter.read_session_source(global_db, "s")["readability"] == "readable"
    # Both kinds of explicit override disable all default discovery.
    monkeypatch.setattr(module, "discover_sqlite_databases", lambda: pytest.fail("real discovery"))
    assert CursorAdapter(None, projects_dir=tmp_path / "absent").list_sessions() == []
    assert CursorAdapter(None, sqlite_databases=()).list_sessions() == []


def test_global_hash_membership_ambiguity_and_missing(tmp_path):
    from harness_mem.adapters.cursor.sqlite_history import workspace_memberships
    global_db = native(tmp_path, "globalStorage")
    (global_db.parent / "workspace.json").unlink()
    storage = tmp_path / "workspaceStorage"
    storage.mkdir()
    first = native(storage, "hash1")
    second = native(storage, "hash2")
    (first.parent / "workspace.json").write_text(json.dumps({"folder": (tmp_path / "a").as_uri()}))
    (second.parent / "workspace.json").write_text(json.dumps({"folder": (tmp_path / "b").as_uri()}))
    with sqlite3.connect(global_db) as db:
        db.execute("CREATE TABLE composerHeaders (composerId TEXT, workspaceId TEXT)")
        db.execute("INSERT INTO composerHeaders VALUES ('s','hash1')")
    paths = (global_db, first, second)
    assert workspace_memberships(paths)[tmp_path]["s"] == tmp_path / "a"
    with sqlite3.connect(global_db) as db:
        db.execute("INSERT INTO composerHeaders VALUES ('s','hash2')")
        db.execute("INSERT INTO composerHeaders VALUES ('unknown','missing')")
    assert workspace_memberships(paths)[tmp_path] == {"s": None, "unknown": None}


def test_diagnostic_and_proven_empty_draft(tmp_path):
    from harness_mem.adapters.cursor.sqlite_history import inspect_sqlite_schema
    database = native(tmp_path)
    before = database.read_bytes()
    report = inspect_sqlite_schema(database)
    assert report["status"] == "readable"
    assert report["tables"]["cursorDiskKV"]["key_prefixes"] == {"bubbleId:": 2, "composerData:": 1}
    assert "hello" not in json.dumps(report)
    assert before == database.read_bytes()
    with sqlite3.connect(database) as db:
        db.execute("UPDATE cursorDiskKV SET value=? WHERE key='composerData:s'",
                   ('{"composerId":"s","fullConversationHeadersOnly":[]}',))
    source, = enumerate_source_records(database)
    assert source.readability == "readable"  # orphan bubbles prevent empty claim
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;' ")
    adapter = CursorAdapter(None, sqlite_databases=(database,))
    adapter.list_sessions()
    result = adapter.read_session_source(database, "s")
    assert result["readability"] == "empty_draft"
    assert json.loads(result["source_text"])["records"]
    assert inspect_sqlite_schema(tmp_path / "missing.db")["status"] == "unreadable"
    assert not (tmp_path / "missing.db").exists()


def test_environment_root_and_no_membership_guess(tmp_path, monkeypatch):
    import harness_mem.adapters.cursor.sqlite_history as history
    monkeypatch.setattr(history.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert history.cursor_user_root() == tmp_path / "config/Cursor/User"
    monkeypatch.setattr(history.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert history.cursor_user_root() == tmp_path / "roaming/Cursor/User"
    database = native(tmp_path, "globalStorage")
    # Adjacent metadata on a global container is not composer membership.
    adapter = CursorAdapter(None, sqlite_databases=(database,))
    record, = adapter.list_sessions()
    assert "cwd" not in record
    assert adapter.read_session_source(database, "s")["project_roots"] == []
