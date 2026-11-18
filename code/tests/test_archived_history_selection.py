"""Archive-only selection through the public manual history path."""
from __future__ import annotations

import asyncio
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.cursor import sqlite_cleanup
from harness_mem.adapters.cursor import cross_store_cleanup
from harness_mem.commands import session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def native_archives(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    user = tmp_path / "User"
    workspace = user / "workspaceStorage" / "work"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text(json.dumps({"folder": root.as_uri()}), encoding="utf-8")
    workspace_db = workspace / "state.vscdb"
    database = user / "globalStorage" / "state.vscdb"
    database.parent.mkdir()
    with closing(sqlite3.connect(workspace_db)) as db:
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE composerHeaders (composerId TEXT PRIMARY KEY, workspaceId TEXT, isArchived INTEGER)")
        db.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO ItemTable VALUES ('unrelated', 'untouched')")
        for identity, archived in [("closed", 1), ("closed-neighbor", 0), ("unknown", None)]:
            db.execute("INSERT INTO composerHeaders VALUES (?, 'work', ?)", (identity, archived))
            db.executemany("INSERT INTO cursorDiskKV VALUES (?, ?)", [
                (f"composerData:{identity}", json.dumps({
                    "composerId": identity, "fullConversationHeadersOnly": [{"bubbleId": "b"}],
                })),
                (f"bubbleId:{identity}:b", '{"bubbleId":"b","text":"Hello there","type":1}'),
            ])
    codex_current, codex_archive = tmp_path / "sessions", tmp_path / "archived_sessions"
    for directory, identity in [(codex_current, "codex-current"), (codex_archive, "codex-closed")]:
        directory.mkdir()
        (directory / f"rollout-{identity}.jsonl").write_text(json.dumps({
            "type": "session_meta", "payload": {"id": identity, "cwd": str(root)},
        }) + "\n", encoding="utf-8")

    def adapter(client):
        if client == "cursor":
            return CursorAdapter(None, sqlite_databases=(database, workspace_db))
        assert client == "codex"
        return CodexAdapter(None, sessions_dir=codex_current, archive_dir=codex_archive, scope="all")

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", adapter)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(sqlite_cleanup, "discover_sqlite_databases", lambda: (database, workspace_db))
    monkeypatch.setattr(sqlite_cleanup, "cursor_profile_roots", lambda: (user,))
    monkeypatch.setattr(sqlite_cleanup.cursor_adapter, "DEFAULT_PROJECTS_DIR", tmp_path / "projects")
    try:
        yield root, database, backend, tool_handlers.build_tool_handlers()
    finally:
        asyncio.run(backend.close())


def test_inventory_keeps_only_native_archives_when_requested(native_archives):
    _root, _database, _backend, handlers = native_archives
    inspect = handlers["inspect_sessions"]
    inventory = inspect(clients=["codex", "cursor"])
    assert {row["session_id"]: row["archive_state"] for row in inventory["sessions"]} == {
        "closed": "archived", "closed-neighbor": "not_archived", "unknown": "unknown",
        "codex-closed": "archived", "codex-current": "not_archived",
    }
    filtered = inspect(clients=["codex", "cursor"], archived_only=True)
    assert {row["session_id"] for row in filtered["sessions"]} == {"closed", "codex-closed"}
    nonarchive = next(row for row in inventory["sessions"] if row["session_id"] == "closed-neighbor")
    rejected = handlers["prepare_session_distill"](batch_sessions=[nonarchive], scope="all", archived_only=True)
    assert not rejected["success"] and "verified archive" in rejected["error"]


@pytest.mark.parametrize("device_scope", [True, False])
@pytest.mark.parametrize("mutation", ["unarchive", "edit"])
def test_archive_selection_rechecks_before_finalize(native_archives, device_scope, mutation):
    root, database, backend, handlers = native_archives
    prepare = handlers["prepare_session_distill"]
    scope = {"scope": "all"} if device_scope else {"project_name": "project", "project_root": str(root)}
    inventory = handlers["inspect_sessions"](clients=["cursor"], archived_only=True, **scope)
    packet = prepare(batch_sessions=inventory["sessions"], archived_only=True, **scope)
    assert packet["success"], packet
    with closing(sqlite3.connect(database)) as db, db:
        if mutation == "unarchive":
            db.execute("UPDATE composerHeaders SET isArchived=0 WHERE composerId='closed'")
        else:
            db.execute("UPDATE cursorDiskKV SET value=? WHERE key='bubbleId:closed:b'",
                       ('{"bubbleId":"b","text":"Changed greeting","type":1}',))
    final = handlers["finalize_session_distill"](packet["project_name"], packet["distill_job_id"], {})
    assert not final["success"] and final["reason_codes"] == ["archived_source_changed_or_unverified"], final
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).status != "completed"
    held = handlers["inspect_sessions"](batch_id=packet["batch_id"])
    assert held["progress"]["states"] == {"blocked": 1}, held


def _sqlite_records(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("composerHeaders", "cursorDiskKV", "ItemTable")}


def _add_search_copy(index):
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, body TEXT)")
        db.execute("CREATE TABLE conversation_search_candidates (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO conversations VALUES ('closed', 'Another native copy')")


@pytest.mark.parametrize("scenario", [
    "success", "busy", "rollback", "companion", "other_profile", "search_only_profile", "additional",
    "uncertain_commit", "receipt_failure",
])
def test_cursor_archived_row_cleanup_on_isolated_database(native_archives, monkeypatch, scenario):
    root, database, backend, handlers = native_archives
    prepare = handlers["prepare_session_distill"]
    scope = {"project_name": "project", "project_root": str(root)}
    inventory = handlers["inspect_sessions"](clients=["cursor"], archived_only=True, **scope)
    packet = prepare(batch_sessions=inventory["sessions"], archived_only=True, **scope)
    assert packet["success"], packet
    finished = handlers["finalize_session_distill"]("project", packet["distill_job_id"], {
        "session_summary": "The archived conversation is a greeting with no durable knowledge.",
        "final_user_request": "Greet the assistant.", "final_outcome": "Reviewed the complete greeting.",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "no_promotion",
    })
    assert finished["success"], finished
    note = Path(finished["note"]["path"])
    note_before = note.read_bytes()
    before = _sqlite_records(database)
    workspace_db = database.parent.parent / "workspaceStorage" / "work" / "state.vscdb"
    workspace_bytes = workspace_db.read_bytes()
    batch = {**scope, "batch_id": packet["batch_id"], "cleanup_processed": True}
    preview = prepare(**batch)
    assert preview["counts"] == {"ready": 1}, preview
    assert _sqlite_records(database) == before
    if scenario == "companion":
        index = database.with_name("conversation-search.db")
        _add_search_copy(index)
        index_bytes = index.read_bytes()
    elif scenario == "search_only_profile":
        other_profile = root.parent / "User" / "profiles" / "search-only"
        index = other_profile / "globalStorage" / "conversation-search.db"
        index.parent.mkdir(parents=True)
        _add_search_copy(index)
        index_bytes = index.read_bytes()
        monkeypatch.setattr(sqlite_cleanup, "cursor_profile_roots", lambda: (database.parent.parent, other_profile))
    elif scenario == "other_profile":
        other = root.parent / "other-profile" / "User" / "globalStorage" / "state.vscdb"
        other.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database)) as live, closing(sqlite3.connect(other)) as copy:
            live.backup(copy)
        other_bytes = other.read_bytes()
        monkeypatch.setattr(sqlite_cleanup, "discover_sqlite_databases", lambda: (database, workspace_db, other))
    elif scenario == "rollback":
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("CREATE TABLE dependent (id TEXT REFERENCES composerHeaders(composerId))")
            db.execute("INSERT INTO dependent VALUES ('closed')")
    elif scenario == "additional":
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT INTO cursorDiskKV VALUES ('unknownNamespace:closed:artifact', 'keep')")
        before = _sqlite_records(database)

    with closing(sqlite3.connect(database)) as locker, monkeypatch.context() as boundary:
        if scenario == "busy":
            locker.execute("BEGIN IMMEDIATE")
        if scenario == "uncertain_commit":
            boundary.setattr(sqlite_cleanup, "_absence_verified", lambda _: False)
        if scenario == "receipt_failure":
            save = backend.transcript_store.save_deletion_receipt

            def interrupt_native_receipt(receipt):
                if receipt.get("native_cleanup", {}).get("status") == "deleted":
                    raise OSError("simulated interruption before recording native commit")
                save(receipt)

            boundary.setattr(backend.transcript_store, "save_deletion_receipt", interrupt_native_receipt)
        applied = prepare(**batch, apply_cleanup=True)
        locker.rollback()

    assert note.read_bytes() == note_before
    assert workspace_db.read_bytes() == workspace_bytes
    if scenario in {"busy", "rollback", "companion", "other_profile", "search_only_profile", "additional"}:
        expected = "partial_failure" if scenario in {"busy", "rollback"} else "retained"
        assert applied["counts"] == {expected: 1}, applied
        assert _sqlite_records(database) == before
        if scenario in {"companion", "search_only_profile"}:
            assert index.read_bytes() == index_bytes
            assert applied["sessions"][0]["reason_codes"] == ["cursor_cleanup_search_copy_retained"]
        if scenario == "other_profile":
            assert other.read_bytes() == other_bytes
            assert applied["sessions"][0]["reason_codes"] == ["cursor_cleanup_other_store_copy_retained"]
        if scenario == "additional":
            assert applied["sessions"][0]["reason_codes"] == ["archived_source_changed_or_unverified"]
        return
    assert _sqlite_records(database) == {
        "composerHeaders": [row for row in before["composerHeaders"] if row[0] != "closed"],
        "cursorDiskKV": [row for row in before["cursorDiskKV"]
                         if row[0] not in {"composerData:closed", "bubbleId:closed:b"}],
        "ItemTable": before["ItemTable"],
    }
    if scenario in {"uncertain_commit", "receipt_failure"}:
        assert not applied["success"] and applied["status"] == "partial", applied
        backup, = (backend.data_dir / "cursor-cleanup-backups").glob("*.sqlite")
        restored = database.parent / "restore-check.vscdb"
        with closing(sqlite3.connect(backup)) as saved, closing(sqlite3.connect(restored)) as copy:
            saved.backup(copy)
        assert _sqlite_records(restored) == before
        pending = prepare(**batch, apply_cleanup=True)
        assert pending["sessions"][0]["reason_codes"] == ["cursor_cleanup_commit_unverified"], pending
        assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).source_cleanup_status != "deleted"
    else:
        assert applied["counts"] == {"deleted": 1}, applied
        replay = prepare(**batch, apply_cleanup=True)
        assert replay["counts"] == {"already_deleted": 1}, replay
        assert list((backend.data_dir / "cursor-cleanup-backups").glob("*.sqlite")) == []
        _add_search_copy(database.with_name("conversation-search.db"))
        replay = prepare(**batch, apply_cleanup=True)
        assert replay["sessions"][0]["reason_codes"] == ["cursor_cleanup_absence_unverified"], replay


def _search_records(path):
    with closing(sqlite3.connect(path)) as db:
        return {
            "conversations": db.execute("SELECT * FROM conversations ORDER BY fts_rowid").fetchall(),
            "candidates": db.execute("SELECT * FROM conversation_search_candidates ORDER BY id").fetchall(),
            "fts": db.execute("SELECT rowid,title,body,branches FROM conversation_fts ORDER BY rowid").fetchall(),
        }


class _InterruptedCursorCleanup(BaseException):
    """Simulate an unhandled exit between durable native commits."""


@pytest.mark.parametrize("scenario", [
    "normal", "rollback_retry", "search_commit_exit", "primary_commit_exit", "changed",
    "unack_search", "unack_primary", "checkpoint_changed", "restored_then_search_removed", "search_changed",
])
def test_cursor_cross_store_cleanup_preserves_results_and_retries(native_archives, monkeypatch, scenario):
    from test_cursor_search_cleanup import _CANDIDATES_SQL, _CONVERSATIONS_SQL, _FTS_SQL, _write_document

    root, database, backend, handlers = native_archives
    prepare = handlers["prepare_session_distill"]
    statement = "Keep one signed acceptance note for every completed review."
    title = "Signed acceptance notes"
    task = "Check the restore example before release."
    policy = root / "policy.txt"
    policy.write_text(statement, encoding="utf-8")
    index = database.with_name("conversation-search.db")
    with closing(sqlite3.connect(index)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        for ddl in (_CONVERSATIONS_SQL, _CANDIDATES_SQL, _FTS_SQL):
            db.execute(ddl)
        _write_document(db, 1, "closed", "selectedtext")
        _write_document(db, 2, "closed-neighbor", "neighborunique", archived=0)
        db.executemany("INSERT INTO conversation_search_candidates VALUES (?, 124)", [("closed",), ("closed-neighbor",)])
    checkpoint = "checkpointId:closed:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cursorDiskKV VALUES (?,?)", (checkpoint, json.dumps({
            "files": [], "nonExistentFiles": [], "newlyCreatedFolders": [],
            "activeInlineDiffs": [], "inlineDiffNewlyCreatedResources": {},
        })))
    primary_before, search_before = _sqlite_records(database), _search_records(index)
    scope = {"project_name": "project", "project_root": str(root)}
    inventory = handlers["inspect_sessions"](clients=["cursor"], archived_only=True, **scope)
    packet = prepare(batch_sessions=inventory["sessions"], archived_only=True, **scope)
    assert packet["success"], packet
    job_id = packet["distill_job_id"]
    candidate = handlers["govern_memory"](action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision",
        "content": statement, "source": policy.name, "distill_job_id": job_id,
        "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": policy.name,
                               "content_sha256": sha256(policy.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "A continuing acceptance rule.",
        "canonical_title": title, "topic_path": ["Acceptance"],
    })
    assert candidate["success"], candidate
    finished = handlers["finalize_session_distill"]("project", job_id, {
        "session_summary": "The retention policy is verified and the restore check remains open.",
        "final_user_request": "Retain the policy and follow-up.", "final_outcome": "Saved the policy and the task.",
        "last_turn_status": "unfinished", "contradictions": [], "unfinished_work": [task],
        "evidence_status": "answered", "promotion_decision": "partial",
        "final_scope_judgment": {candidate["entry_id"]: {"points": [{
            "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
            "source_use": "reusable_knowledge", "reason": "The current policy file proves this rule.",
            "scope_segments": [{"text": title + "\n" + statement, "source_use": "reusable_knowledge",
                                "future_scope": "durable", "standalone": True, "content_role": "claim",
                                "source_support": "supported"}],
        }]}},
    })
    assert finished["success"], finished
    note = Path(finished["note"]["path"])
    note_before = note.read_bytes()
    handoffs = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
    assert [item["next_steps"] for item in handoffs] == [[task]]
    batch = {**scope, "batch_id": packet["batch_id"], "cleanup_processed": True}
    preview = prepare(**batch)
    assert preview["counts"] == {"ready": 1} and preview["sessions"][0]["counts"] == {"planned": 7}, preview
    native = preview["sessions"][0]["native"]
    assert native["file_targets"] == []
    assert native["record_sets"]["primary"]["key_value_rows"] == 3
    assert native["record_sets"]["search"]["records"] == 3
    assert all(len(record["sha256"]) == 64 for record in native["record_sets"].values())
    assert _sqlite_records(database) == primary_before and _search_records(index) == search_before

    if scenario == "checkpoint_changed":
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE cursorDiskKV SET value=json_set(value,'$.files',json('[{}]')) WHERE key=?",
                       (checkpoint,))
        modified = _sqlite_records(database)
        blocked = prepare(**batch, apply_cleanup=True)
        assert blocked["counts"] == {"retained": 1}, blocked
        assert _sqlite_records(database) == modified and _search_records(index) == search_before
        return
    if scenario == "search_changed":
        with closing(sqlite3.connect(index)) as db, db:
            db.execute("UPDATE conversation_fts SET body='changed after preview' WHERE rowid=1")
        changed_index = _search_records(index)
        blocked = prepare(**batch, apply_cleanup=True)
        assert blocked["sessions"][0]["reason_codes"] == ["cursor_cleanup_search_witness_changed_or_missing"], blocked
        assert _sqlite_records(database) == primary_before and _search_records(index) == changed_index
        return
    with monkeypatch.context() as failure:
        if scenario in {"rollback_retry", "restored_then_search_removed"}:
            def fail_primary(*_):
                raise sqlite3.OperationalError("injected primary write failure")

            failure.setattr(cross_store_cleanup, "delete_primary_rows", fail_primary)
            partial = prepare(**batch, apply_cleanup=True)
            assert partial["sessions"][0]["reason_codes"][0] == "cursor_cross_store_search_restored", partial
            assert _sqlite_records(database) == primary_before and _search_records(index) == search_before
        elif scenario in {"search_commit_exit", "primary_commit_exit", "changed", "unack_search", "unack_primary"}:
            save = backend.transcript_store.save_deletion_receipt

            def interrupt(receipt):
                native = receipt.get("native_cleanup", {})
                phase = native.get("cross_store", {}).get("phase")
                stop = (native.get("status") == "deleted" if scenario == "primary_commit_exit"
                        else phase == "verified" if scenario == "unack_primary" else phase == "search_committed")
                if stop:
                    if scenario in {"search_commit_exit", "changed"}:
                        save(receipt)
                    raise _InterruptedCursorCleanup()
                return save(receipt)

            failure.setattr(backend.transcript_store, "save_deletion_receipt", interrupt)
            with pytest.raises(_InterruptedCursorCleanup):
                prepare(**batch, apply_cleanup=True)
            assert len(list((backend.data_dir / "cursor-cleanup-backups").glob("*.sqlite"))) == 2
            assert not any(row[3] == "closed" for row in _search_records(index)["conversations"])
            if scenario not in {"primary_commit_exit", "unack_primary"}:
                assert _sqlite_records(database) == primary_before
    if scenario == "restored_then_search_removed":
        from harness_mem.adapters.cursor.search_cleanup import delete_search_rows, select_search_rows
        with closing(sqlite3.connect(index)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = select_search_rows(db, "closed")
            assert rows is not None
            delete_search_rows(db, rows)
        search_now = _search_records(index)
        blocked = prepare(**batch, apply_cleanup=True)
        assert blocked["sessions"][0]["reason_codes"] == ["cursor_cross_store_commit_unverified"], blocked
        assert _sqlite_records(database) == primary_before and _search_records(index) == search_now
        return
    if scenario in {"unack_search", "unack_primary"}:
        primary_now, search_now = _sqlite_records(database), _search_records(index)
        blocked = prepare(**batch, apply_cleanup=True)
        assert blocked["sessions"][0]["reason_codes"] == ["cursor_cross_store_commit_unverified"], blocked
        assert _sqlite_records(database) == primary_now and _search_records(index) == search_now
        backups = backend.data_dir / "cursor-cleanup-backups"
        for suffix, read, expected in (
            ("primary", _sqlite_records, primary_before), ("search", _search_records, search_before),
        ):
            saved, = backups.glob(f"*.{suffix}.sqlite")
            restored = root / f"restored-{suffix}.sqlite"
            with closing(sqlite3.connect(saved)) as source, closing(sqlite3.connect(restored)) as copy:
                source.backup(copy)
            assert read(restored) == expected
        return
    if scenario == "changed":
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("UPDATE cursorDiskKV SET value=? WHERE key='bubbleId:closed:b'",
                       ('{"bubbleId":"b","text":"Changed archive","type":1}',))
        modified, index_now = _sqlite_records(database), _search_records(index)
        blocked = prepare(**batch, apply_cleanup=True)
        assert blocked["counts"] == {"retained": 1}, blocked
        assert _sqlite_records(database) == modified and _search_records(index) == index_now
        return
    if scenario != "normal":
        prior, = backend.transcript_store.list_deletion_audit(project_name="project")
        assert prepare(**batch)["counts"] == {"ready": 1}
    result = prepare(**batch, apply_cleanup=True)
    assert result["counts"] == {"deleted": 1}, result
    if scenario != "normal":
        assert result["sessions"][0]["receipt_id"] == prior["id"]
    assert _sqlite_records(database) == {
        "composerHeaders": [row for row in primary_before["composerHeaders"] if row[0] != "closed"],
        "cursorDiskKV": [row for row in primary_before["cursorDiskKV"]
                         if row[0] not in {"composerData:closed", "bubbleId:closed:b", checkpoint}],
        "ItemTable": primary_before["ItemTable"],
    }
    assert _search_records(index) == {
        "conversations": [row for row in search_before["conversations"] if row[0] != 1],
        "candidates": [row for row in search_before["candidates"] if row[0] != "closed"],
        "fts": [row for row in search_before["fts"] if row[0] != 1],
    }
    assert list((backend.data_dir / "cursor-cleanup-backups").glob("*.sqlite")) == []
    reopened = LocalMemoryBackend(backend.data_dir)
    asyncio.run(backend.close())
    asyncio.run(reopened.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
        if scenario == "normal":
            # A Cursor installation can have SQLite history without exported JSONL.
            monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: CursorAdapter(
                None, projects_dir=sqlite_cleanup.cursor_adapter.DEFAULT_PROJECTS_DIR,
                sqlite_databases=sqlite_cleanup.discover_sqlite_databases(),
            ))
            inventory = session_inventory.collect_session_inventory(
                reopened.data_dir, project_root=root, project_name="project", clients=["cursor"], lightweight=True,
            )
            assert {issue["reason"] for issue in inventory.issues} == {"projects_dir_missing"}
        replay = prepare(**batch, apply_cleanup=True)
        assert replay["counts"] == {"already_deleted": 1}, replay
        found = handlers["search_memory"](query=title, project_name="project", scope="project", detail="full")
        assert found["memories"] == [{"title": title, "statement": statement}]
        assert note.read_bytes() == note_before
        assert reopened.structured_store.list_record_payloads("task_handoffs", strict=True) == handoffs
        if scenario == "normal":
            export = sqlite_cleanup.cursor_adapter.DEFAULT_PROJECTS_DIR / "project" / "agent-transcripts" / "closed" / "closed.jsonl"
            export.parent.mkdir(parents=True)
            export.write_text("{}\n", encoding="utf-8")
            replay = prepare(**batch, apply_cleanup=True)
            assert replay["sessions"][0]["reason_codes"] == ["cursor_cleanup_absence_unverified"], replay
            assert export.read_text(encoding="utf-8") == "{}\n"
            export.unlink()
            export.parent.rmdir()
            with closing(sqlite3.connect(index)) as db, db:
                db.execute("INSERT INTO conversation_fts(rowid,title,body,branches) VALUES (1,'orphan','returned','[]')")
            replay = prepare(**batch, apply_cleanup=True)
            assert replay["sessions"][0]["reason_codes"] == ["cursor_cleanup_absence_unverified"], replay
    finally:
        asyncio.run(reopened.close())
