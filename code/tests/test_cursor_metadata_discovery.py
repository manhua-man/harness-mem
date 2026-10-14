"""Metadata discovery against isolated native SQLite and JSONL sources."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import harness_mem.adapters.cursor.adapter as module
import harness_mem.adapters.cursor.sqlite_history as history
from harness_mem.adapters.cursor.adapter import CursorAdapter


def database(path: Path, *session_ids: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        for sid in session_ids:
            db.executemany("INSERT INTO cursorDiskKV VALUES (?, ?)", [
                (f"composerData:{sid}", json.dumps({
                    "composerId": sid, "fullConversationHeadersOnly": [{"bubbleId": "b"}],
                    "text": "private composer body",
                })),
                (f"bubbleId:{sid}:b", json.dumps({"bubbleId": "b", "text": f"private {sid}"})),
                (f"bubbleId:{sid}:orphan", json.dumps({"bubbleId": "orphan", "text": "keep all"})),
            ])
    return path


def workspace(path: Path, owner: Path, *session_ids: str) -> Path:
    db = database(path, *session_ids)
    (path.parent / "workspace.json").write_text(json.dumps({"folder": owner.as_uri()}))
    return db


def membership(user: Path, owner: Path, *, sid: str = "s", wid: str = "hash") -> tuple[Path, Path]:
    global_db = database(user / "globalStorage/state.vscdb", sid)
    workspace_db = workspace(user / f"workspaceStorage/{wid}/state.vscdb", owner)
    with sqlite3.connect(workspace_db) as db:
        db.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO ItemTable VALUES (?, ?)", (
            "composer.composerHeaders", json.dumps({"allComposers": [{"composerId": sid}]}),
        ))
    return global_db, workspace_db


def jsonl(projects: Path, sid: str, records: list[dict], *, slug: str = "untrusted") -> Path:
    path = projects / slug / "agent-transcripts" / sid / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def forbid_exporters(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("metadata discovery called a body exporter or body matcher")

    monkeypatch.setattr(module, "enumerate_source_records", forbidden)
    monkeypatch.setattr(module, "parse_cursor_jsonl_session", forbidden)
    monkeypatch.setattr(module, "list_session_files", forbidden)
    monkeypatch.setattr(CursorAdapter, "_matching_project_dirs", forbidden)
    monkeypatch.setattr(CursorAdapter, "_project_dir_mentions_root", forbidden)


def test_metadata_listing_never_reads_sqlite_bodies_or_exports_jsonl(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    owner = tmp_path / "exact native 世界"
    source = jsonl(projects, "j", [{"cwd": str(owner)}, {
        "role": "user", "message": {"content": "private text"},
    }])
    global_db, workspace_db = membership(tmp_path / "User", owner)
    before = {path: path.read_bytes() for path in (global_db, workspace_db, source)}
    forbid_exporters(monkeypatch)
    real_connect = sqlite3.connect

    def guarded_connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)

        def authorize(action, table, column, *rest):
            if action == sqlite3.SQLITE_READ and table == "cursorDiskKV" and column == "value":
                pytest.fail("metadata discovery fetched a composer/bubble value")
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorize)
        return db

    monkeypatch.setattr(history.sqlite3, "connect", guarded_connect)
    real_read_bytes, real_read_text = Path.read_bytes, Path.read_text

    def no_jsonl_bytes(path):
        assert path.suffix != ".jsonl", "metadata must read only a bounded prefix"
        return real_read_bytes(path)

    def no_jsonl_text(path, *args, **kwargs):
        assert path.suffix != ".jsonl", "metadata must not read the entire JSONL"
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", no_jsonl_bytes)
    monkeypatch.setattr(Path, "read_text", no_jsonl_text)
    adapter = CursorAdapter(None, projects_dir=projects, project_root=owner,
                            sqlite_databases=(global_db, workspace_db))
    records = adapter.list_session_metadata()
    assert {(r["path"], r["session_id"]) for r in records} == {(source, "j"), (global_db, "s")}
    for record in records:
        assert record["project_roots"] == [str(owner.resolve())]
        assert record["metadata_status"] == "available"
        assert record["size_bytes"] == record["path"].stat().st_size
        assert record["mtime_ns"] == record["path"].stat().st_mtime_ns
        assert "source_status" not in record and "lines" not in record
    assert adapter._sqlite_sources == {}
    assert all(real_read_bytes(path) == raw for path, raw in before.items())


def test_jsonl_slug_tool_body_and_relative_roots_are_not_proof(tmp_path, monkeypatch):
    owner = tmp_path / "wanted"
    projects = tmp_path / "projects"
    jsonl(projects, "unknown", [{
        "role": "assistant", "message": {"content": [
            {"type": "text", "text": str(owner)},
            {"type": "tool_use", "input": {"cwd": str(owner), "path": str(owner)}},
        ]},
    }, {"workspace_root": "relative/root"}], slug="wanted")
    jsonl(projects, "known", [{"workspace_root": str(owner)}], slug="unrelated")
    forbid_exporters(monkeypatch)
    adapter = CursorAdapter(None, projects_dir=projects, project_root=owner)
    records = {r["session_id"]: r for r in adapter.list_session_metadata()}
    assert records["unknown"]["project_roots"] == []
    assert records["unknown"]["metadata_status"] == "unknown"
    assert "cwd" not in records["unknown"]
    assert records["known"]["project_roots"] == [str(owner)]


def test_jsonl_bounded_discovery_does_not_truncate_selected_read(tmp_path):
    projects = tmp_path / "projects"
    owner = tmp_path / "owner"
    source = jsonl(projects, "long", [{"cwd": str(owner)}, {
        "role": "user", "message": {"content": "x" * 100000 + "end-of-body"},
    }])
    adapter = CursorAdapter(None, projects_dir=projects)
    record, = adapter.list_session_metadata()
    assert record["project_roots"] == [str(owner)]
    result = adapter.read_session_source(source, "long")
    assert result["raw_bytes"] == source.read_bytes()
    assert "end-of-body" in result["source_text"]


def test_jsonl_multiple_native_roots_preserved_and_drift_blocked(tmp_path):
    projects = tmp_path / "projects"
    roots = [str(tmp_path / "a"), str(tmp_path / "b")]
    source = jsonl(projects, "s", [{"cwd": roots[0]}, {"workspace_root": roots[1]}])
    adapter = CursorAdapter(None, projects_dir=projects)
    record, = adapter.list_session_metadata()
    assert record["project_roots"] == roots
    assert "cwd" not in record
    jsonl(projects, "s", [{"cwd": str(tmp_path / "new")}])
    with pytest.raises(ValueError, match="ownership_changed"):
        adapter.read_session_source(source, "s")


def test_global_unknown_and_conflicting_membership_do_not_guess(tmp_path, monkeypatch):
    global_db, first = membership(tmp_path / "User", tmp_path / "a")
    second = workspace(tmp_path / "User/workspaceStorage/hash2/state.vscdb", tmp_path / "b")
    with sqlite3.connect(global_db) as db:
        db.execute("CREATE TABLE composerHeaders (composerId TEXT, workspaceId TEXT)")
        db.executemany("INSERT INTO composerHeaders VALUES (?, ?)", [("s", "hash2"), ("s", "missing")])
        db.execute("INSERT INTO cursorDiskKV VALUES ('composerData:unknown', 'not JSON')")
    (global_db.parent / "workspace.json").write_text(json.dumps({"folder": tmp_path.as_uri()}))
    forbid_exporters(monkeypatch)
    records = CursorAdapter(None, sqlite_databases=(global_db, first, second)).list_session_metadata()
    assert {r["session_id"] for r in records} == {"s", "unknown"}
    assert all(r["metadata_status"] == "unknown" and r["project_roots"] == [] for r in records)


@pytest.mark.parametrize("schema", [
    "CREATE TABLE cursorDiskKV (key TEXT, value TEXT)",
    "CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT, extra TEXT)",
    "CREATE VIEW cursorDiskKV AS SELECT key,value FROM privateBodies",
])
def test_unsupported_schema_no_fallback_body_scan(tmp_path, monkeypatch, schema):
    path = tmp_path / "bad.vscdb"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE privateBodies (key TEXT, value TEXT)")
        db.execute("INSERT INTO privateBodies VALUES ('composerData:s', 'private body')")
        db.execute(schema)
    forbid_exporters(monkeypatch)
    issues = []
    assert CursorAdapter(None, sqlite_databases=(path,)).list_session_metadata(issues=issues) == []
    assert len(issues) == 1
    assert issues[0]["code"].startswith("cursor_sqlite_unsupported_")


def test_selection_queries_exact_composer_and_all_its_bubbles_only(tmp_path, monkeypatch):
    path = workspace(tmp_path / "workspace/state.vscdb", tmp_path, "s", "sa", "other")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE cursorDiskKV SET value='broken' WHERE key='composerData:other'")
    adapter = CursorAdapter(None, sqlite_databases=(path,))
    adapter.list_session_metadata()
    queries = []
    real_connect = sqlite3.connect

    def trace_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(history.sqlite3, "connect", trace_connect)
    source = adapter.read_session_source(path, "s")
    records = json.loads(source["source_text"])["records"]
    assert [r[0] for r in records] == ["composerData:s", "bubbleId:s:b", "bubbleId:s:orphan"]
    reads = [q for q in queries if q.startswith("SELECT key, value")]
    assert len(reads) == 2
    assert "= 'composerData:s'" in reads[0]
    assert "'bubbleId:s:'" in reads[1] and "'bubbleId:s;'" in reads[1]
    assert source["project_roots"] == [str(tmp_path)]
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM cursorDiskKV")
    assert adapter.read_session_source(path, "s")["raw_bytes"] == source["raw_bytes"]
    assert len([q for q in queries if q.startswith("SELECT key, value")]) == 2
    with pytest.raises(ValueError, match="not pinned"):
        adapter.read_session_source(path, "not-listed")


@pytest.mark.parametrize("cached", [False, True])
def test_workspace_root_change_blocks_selection_even_after_pinning(tmp_path, cached):
    path = workspace(tmp_path / "workspace/state.vscdb", tmp_path / "old", "s")
    adapter = CursorAdapter(None, sqlite_databases=(path,))
    adapter.list_session_metadata()
    if cached:
        adapter.read_session_source(path, "s")
    (path.parent / "workspace.json").write_text(json.dumps({"folder": (tmp_path / "new").as_uri()}))
    with pytest.raises(ValueError, match="ownership_changed"):
        adapter.read_session_source(path, "s")


@pytest.mark.parametrize("change", ["root", "membership", "conflict", "unknown_to_known"])
def test_global_owner_rechecked_from_fresh_metadata(tmp_path, change):
    user = tmp_path / "User"
    global_db, first = membership(user, tmp_path / "old")
    paths = (global_db, first)
    if change == "unknown_to_known":
        paths = (global_db,)
    elif change in {"membership", "conflict"}:
        second = workspace(user / "workspaceStorage/second/state.vscdb", tmp_path / "new")
        paths += (second,)
    adapter = CursorAdapter(None, sqlite_databases=paths)
    adapter.list_session_metadata()
    if change == "root":
        (first.parent / "workspace.json").write_text(json.dumps({"folder": (tmp_path / "new").as_uri()}))
    elif change in {"membership", "conflict"}:
        if change == "membership":
            with sqlite3.connect(first) as db:
                db.execute("DELETE FROM ItemTable")
        with sqlite3.connect(global_db) as db:
            db.execute("CREATE TABLE composerHeaders (composerId TEXT, workspaceId TEXT)")
            db.execute("INSERT INTO composerHeaders VALUES ('s','second')")
    else:
        # Evidence appearing later cannot silently upgrade an unknown selection.
        adapter._metadata_databases += (first,)
    with pytest.raises(ValueError, match="ownership_changed"):
        adapter.read_session_source(global_db, "s")


def test_user_and_profile_memberships_are_isolated(tmp_path):
    first, first_workspace = membership(tmp_path / "User", tmp_path / "a")
    profile, profile_workspace = membership(tmp_path / "User/profiles/p", tmp_path / "b")
    unknown = database(tmp_path / "other/User/globalStorage/state.vscdb", "s")
    adapter = CursorAdapter(None, sqlite_databases=(first, first_workspace, profile, profile_workspace, unknown))
    records = {r["path"]: r for r in adapter.list_session_metadata()}
    assert records[first]["project_roots"] == [str(tmp_path / "a")]
    assert records[profile]["project_roots"] == [str(tmp_path / "b")]
    assert records[unknown]["project_roots"] == []
    assert adapter.read_session_source(profile, "s")["project_roots"] == [str(tmp_path / "b")]
    assert set(history.discover_sqlite_databases(tmp_path / "User")) == {
        first, first_workspace, profile, profile_workspace,
    }


def test_metadata_limit_size_and_explicit_override_remain_isolated(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    small = jsonl(projects, "small", [{"cwd": str(tmp_path)}])
    big = jsonl(projects, "big", [{"cwd": str(tmp_path)}, {"message": "x" * 2000}])
    monkeypatch.setattr(module, "discover_sqlite_databases", lambda: pytest.fail("live discovery"))
    adapter = CursorAdapter(None, projects_dir=projects)
    record, = adapter.list_session_metadata(min_size_kb=1)
    assert record["path"] == big
    assert record["size_bytes"] > small.stat().st_size
    assert len(adapter.list_session_metadata(limit=1)) == 1
    assert adapter.list_session_metadata(limit=0) == []
    assert CursorAdapter(None, sqlite_databases=()).list_session_metadata() == []


def test_membership_dependency_paths_cover_only_own_profile(tmp_path):
    first, first_workspace = membership(tmp_path / "User", tmp_path / "a")
    other, other_workspace = membership(tmp_path / "User/profiles/p", tmp_path / "b")
    writer = sqlite3.connect(first_workspace)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE ItemTable SET value=value")
    writer.commit()
    try:
        records = CursorAdapter(None, sqlite_databases=(first, first_workspace, other, other_workspace)).list_session_metadata()
        row = next(row for row in records if row["path"] == first)
        dependencies = set(row["metadata_paths"])
        assert {first, first_workspace, first_workspace.parent / "workspace.json",
                Path(str(first_workspace) + "-wal")} <= dependencies
        assert other not in dependencies and other_workspace not in dependencies
        assert other_workspace.parent / "workspace.json" not in dependencies
        assert all(isinstance(path, Path) and path.exists() for path in dependencies)
    finally:
        writer.close()


def test_selected_read_updates_dependencies_when_wal_appears(tmp_path):
    path = workspace(tmp_path / "workspace/state.vscdb", tmp_path, "s")
    adapter = CursorAdapter(None, sqlite_databases=(path,))
    record, = adapter.list_session_metadata()
    wal = Path(str(path) + "-wal")
    assert wal not in record["metadata_paths"]
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE cursorDiskKV SET value=value")
    writer.commit()
    try:
        adapter.read_session_source(path, "s")
        assert wal in record["metadata_paths"]
    finally:
        writer.close()


def test_automatic_project_discovery_uses_cursor_metadata_only(tmp_path, monkeypatch):
    from harness_mem.commands.session_inventory import discover_session_projects

    owner = tmp_path / "project"
    owner.mkdir()
    projects = tmp_path / "projects"
    jsonl(projects, "j", [{"cwd": str(owner)}])
    jsonl(projects, "unknown", [{"role": "user", "message": str(owner)}])
    first, first_workspace = membership(tmp_path / "User", owner)
    forbid_exporters(monkeypatch)
    result = discover_session_projects(
        tmp_path / "memory", clients=["cursor"], adapter_factory=lambda _: CursorAdapter(
            None, projects_dir=projects, sqlite_databases=(first, first_workspace),
        ),
    )
    project, = result["projects"]
    assert Path(project["project_root"]) == owner
    assert {row["session_id"] for row in project["sessions"]} == {"j", "s"}
    assert all(row["revision_verified"] is False for row in project["sessions"])
    assert result["unclassified"] == [{"client": "cursor", "session_id": "unknown",
                                      "reason": "project_not_determined"}]
    assert not (tmp_path / "memory").exists()


@pytest.mark.parametrize("change", ["workspace", "membership", "wal"])
def test_preview_cache_invalidates_external_owner_dependencies(tmp_path, monkeypatch, change):
    import harness_mem.commands.session_inventory as inventory
    from harness_mem.config.merge import MergedConfig

    owner = tmp_path / "owner"
    owner.mkdir()
    first, first_workspace = membership(tmp_path / "User", owner)
    monkeypatch.setattr(inventory, "load_merged_config", lambda *_: MergedConfig())
    def factory(_):
        return CursorAdapter(None, sqlite_databases=(first, first_workspace))

    writer = sqlite3.connect(first_workspace)
    if change == "wal":
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE ItemTable SET value=value")
        writer.commit()
    try:
        row, = inventory.collect_session_inventory(
            tmp_path / "memory", project_root=owner, project_name="owner",
            clients=["cursor"], adapter_factory=factory,
        ).rows
        initial = inventory.read_session_page(
            tmp_path / "memory", project_root=owner, project_name="owner", session=row,
            page_chars=20, adapter_factory=factory,
        )
        assert initial["revision_verified"] is True
        if change == "workspace":
            (first_workspace.parent / "workspace.json").write_text(json.dumps({
                "folder": (tmp_path / "different").as_uri(),
            }))
        else:
            writer.execute("DELETE FROM ItemTable")
            writer.commit()
        with pytest.raises(ValueError, match="changed|outside project"):
            inventory.read_session_page(
                tmp_path / "memory", project_root=owner, project_name="owner", session=row,
                offset=20, page_chars=20, adapter_factory=factory,
            )
    finally:
        writer.close()
