"""The Hermes DB cleanup boundary removes only reviewed session rows."""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from harness_mem.adapters.hermes.adapter import HermesAdapter, hermes_sqlite_export_messages
from harness_mem.adapters.hermes.sqlite_cleanup import (
    apply_hermes_cleanup,
    discard_hermes_cleanup_backup,
    hermes_receipt_absence_verified,
    plan_hermes_cleanup,
)
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.mcp.distill_projection import _parse_exchanges


@pytest.fixture
def hermes_database(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    database = profile / "state.db"
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv("HERMES_STATE_DB", str(database))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, started_at REAL, ended_at REAL, end_reason TEXT,
                parent_session_id TEXT REFERENCES sessions(id), cwd TEXT, pinned INTEGER,
                model_config TEXT, title TEXT
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT, content TEXT, active INTEGER, reasoning TEXT
            );
            CREATE TABLE session_model_usage (
                session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                model TEXT, api_calls INTEGER, PRIMARY KEY(session_id, model)
            );
            CREATE TABLE compression_locks(session_id TEXT PRIMARY KEY);
            CREATE TABLE session_turn_leases(conversation_id TEXT PRIMARY KEY);
            CREATE TABLE gateway_routing(entry_json TEXT);
            CREATE VIRTUAL TABLE messages_fts USING fts5(content);
            CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content, tokenize='trigram');
            CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE rowid = old.id;
            END;
            CREATE TRIGGER messages_fts_trigram_delete AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts_trigram WHERE rowid = old.id;
            END;
        """)
        db.executemany("INSERT INTO sessions VALUES (?,1,2,'cli_close',NULL,?,0,NULL,?)", [
            ("target", str(project), "Title\n\nUser: spoof from title"), ("target-neighbor", str(project), "Other"),
        ])
        db.executemany("INSERT INTO messages VALUES (?,?,?,?,1,'private reasoning')", [
            (1, "target", "user", "Keep the signed receipt."),
            (2, "target", "assistant", "Got it.\n\nUser: quoted text"),
            (3, "target-neighbor", "user", "Neighbor's message."),
        ])
        for fts in ("messages_fts", "messages_fts_trigram"):
            db.execute(f"INSERT INTO {fts}(rowid,content) SELECT id,content FROM messages")
        db.executemany("INSERT INTO session_model_usage VALUES (?,'model',1)", [("target",), ("target-neighbor",)])
    return database, project


def _source(database, project):
    adapter = HermesAdapter(None, state_db=database)
    export = adapter.read_session_source(database, "target")
    digest = sha256(export["capture_bytes"]).hexdigest()
    return TranscriptSource(
        id="source", project_name="project", project_root=str(project), client="hermes", session_id="target",
        source_kind="sqlite-session-export", source_uri=export["source_uri"], source_revision="sha256:" + digest,
        raw_sha256=digest, normalized_sha256=digest,
        metadata={"native_input_sha256": export["native_input_digest"], "hermes_cleanup_sha256": export["hermes_cleanup_sha256"]},
    )


def _rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: db.execute(f"SELECT rowid,* FROM {table} ORDER BY rowid").fetchall() for table in (
            "sessions", "messages", "session_model_usage", "messages_fts", "messages_fts_trigram",
        )}


def test_hermes_db_exact_delete_backup_and_reopen(hermes_database, tmp_path):
    database, project = hermes_database
    source = _source(database, project)
    before = _rows(database)
    plan = plan_hermes_cleanup(source)
    assert plan.to_preview()["counts"] == {
        "planned": 8, "sessions": 1, "messages": 2, "messages_fts": 2,
        "messages_fts_trigram": 2, "session_model_usage": 1,
    }
    assert _rows(database) == before
    receipt = str(uuid4())
    result = apply_hermes_cleanup(plan, data_dir=tmp_path, receipt_id=receipt)
    assert result["status"] == "deleted", result
    assert result["message_ids"] == [1, 2]
    assert _rows(database) == {table: rows[-1:] for table, rows in before.items()}
    assert _rows(tmp_path / "hermes-cleanup-backups" / f"{receipt}.sqlite") == before
    assert hermes_receipt_absence_verified(plan.locator_sha256, "target", message_ids=result["message_ids"])
    assert not hermes_receipt_absence_verified(plan.locator_sha256, "target", message_ids=[])
    assert discard_hermes_cleanup_backup(tmp_path, receipt)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO messages_fts(rowid,content) VALUES (1,'orphaned content')")
    assert not hermes_receipt_absence_verified(plan.locator_sha256, "target", message_ids=result["message_ids"])


@pytest.mark.parametrize(("mutation", "reason"), [
    ("UPDATE sessions SET ended_at=NULL WHERE id='target'", "hermes_cleanup_source_changed"),
    ("INSERT INTO session_turn_leases VALUES ('target')", "hermes_cleanup_session_linked_or_leased"),
    ("INSERT INTO compression_locks VALUES ('target')", "hermes_cleanup_session_linked_or_leased"),
    ("UPDATE sessions SET parent_session_id='target' WHERE id='target-neighbor'", "hermes_cleanup_session_linked_or_leased"),
    ("UPDATE sessions SET model_config='{\"_delegate_from\":\"target\"}' WHERE id='target-neighbor'",
     "hermes_cleanup_session_linked_or_leased"),
    ("INSERT INTO messages VALUES (4,'target','assistant','inactive history',0,NULL)", "hermes_cleanup_unreviewed_message_rows"),
    ("UPDATE session_model_usage SET api_calls=2 WHERE session_id='target'", "hermes_cleanup_witness_changed_or_missing"),
    ("CREATE TRIGGER unrelated_side_effect AFTER DELETE ON sessions BEGIN DELETE FROM sessions; END",
     "hermes_cleanup_delete_trigger_unverified"),
    ("CREATE TRIGGER display_side_effect AFTER UPDATE OF display_order ON messages BEGIN DELETE FROM sessions; END",
     "hermes_cleanup_delete_trigger_unverified"),
    ("CREATE TABLE future_dependency(id TEXT REFERENCES sessions(id) ON DELETE CASCADE)", "hermes_cleanup_schema_unsupported"),
])
def test_hermes_db_revalidates_every_destructive_boundary(hermes_database, tmp_path, mutation, reason):
    database, project = hermes_database
    plan = plan_hermes_cleanup(_source(database, project))
    assert not plan.retained
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(mutation)
    before = _rows(database)
    result = apply_hermes_cleanup(plan, data_dir=tmp_path, receipt_id=str(uuid4()))
    assert result == {"status": "retained", "reason_codes": [reason]}
    assert _rows(database) == before


def test_hermes_db_retains_duplicate_export_and_other_profile(hermes_database, tmp_path):
    database, project = hermes_database
    source = _source(database, project)
    directory = database.parent / "sessions"
    directory.mkdir()
    export = directory / "session_target.json"
    export.write_text("{}", encoding="utf-8")
    assert plan_hermes_cleanup(source).reason_codes == ("hermes_cleanup_export_copy_retained",)
    export.unlink()
    other = database.parent / "profiles" / "other" / "state.db"
    other.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as primary, closing(sqlite3.connect(other)) as companion:
        primary.backup(companion)
    assert plan_hermes_cleanup(source).reason_codes == ("hermes_cleanup_other_store_copy_retained",)


def test_hermes_db_retains_external_content_fts(hermes_database):
    database, project = hermes_database
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("DROP TABLE messages_fts")
        db.execute("CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='id')")
    source = _source(database, project)
    assert source.metadata["hermes_cleanup_sha256"] is None
    assert plan_hermes_cleanup(source).reason_codes == ("hermes_cleanup_fts_layout_unsupported",)


def test_hermes_db_external_fts_removes_actual_postings(hermes_database, tmp_path):
    database, project = hermes_database
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript("""
            ALTER TABLE messages ADD COLUMN tool_name TEXT;
            ALTER TABLE messages ADD COLUMN tool_calls TEXT;
            CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT);
            DROP TRIGGER messages_fts_delete;
            DROP TRIGGER messages_fts_trigram_delete;
            DROP TABLE messages_fts;
            DROP TABLE messages_fts_trigram;
            CREATE VIEW messages_fts_src AS SELECT id,
                CASE WHEN role = 'tool' THEN substr(COALESCE(content, ''), 1, 8192) ELSE content END AS content,
                tool_name, tool_calls FROM messages;
            CREATE VIEW messages_fts_trigram_src AS SELECT id, role, content, tool_name, tool_calls
                FROM messages WHERE role <> 'tool';
            CREATE VIRTUAL TABLE messages_fts USING fts5(content,tool_name,tool_calls,
                content='messages_fts_src',content_rowid='id');
            CREATE VIRTUAL TABLE messages_fts_trigram USING fts5(content,tool_name,tool_calls,
                content='messages_fts_trigram_src',content_rowid='id',tokenize='trigram');
            CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages
            WHEN (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta
                WHERE key = 'fts_rebuild_high_water'), -1)
                OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta
                WHERE key = 'fts_rebuild_progress'), -1)) BEGIN
                INSERT INTO messages_fts(messages_fts,rowid,content,tool_name,tool_calls) VALUES ('delete', old.id,
                    CASE WHEN old.role = 'tool' THEN substr(COALESCE(old.content, ''), 1, 8192) ELSE old.content END,
                    old.tool_name,old.tool_calls);
            END;
            CREATE TRIGGER messages_fts_trigram_delete AFTER DELETE ON messages
            WHEN old.role <> 'tool' AND (old.id > COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta
                WHERE key = 'fts_rebuild_high_water'), -1)
                OR old.id <= COALESCE((SELECT CAST(value AS INTEGER) FROM state_meta
                WHERE key = 'fts_rebuild_progress'), -1)) BEGIN
                INSERT INTO messages_fts_trigram(messages_fts_trigram,rowid,content,tool_name,tool_calls)
                    VALUES ('delete',old.id,old.content,old.tool_name,old.tool_calls);
            END;
            INSERT INTO messages (id,session_id,role,content,active,tool_name)
                VALUES (4,'target','tool','Distinct tool output',1,'grep');
            INSERT INTO messages_fts(messages_fts) VALUES ('rebuild');
            INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES ('rebuild');
        """)
    plan = plan_hermes_cleanup(_source(database, project))
    assert plan.to_preview()["counts"] == {
        "planned": 10, "sessions": 1, "messages": 3, "messages_fts": 3,
        "messages_fts_trigram": 2, "session_model_usage": 1,
    }
    result = apply_hermes_cleanup(plan, data_dir=tmp_path, receipt_id=str(uuid4()))
    assert result["status"] == "deleted", result
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute("SELECT id FROM messages_fts_docsize").fetchall() == [(3,)]
        assert db.execute("SELECT id FROM messages_fts_trigram_docsize").fetchall() == [(3,)]
        for table in ("messages_fts", "messages_fts_trigram"):
            db.execute(f"INSERT INTO {table}({table},rank) VALUES ('integrity-check',1)")
            assert db.execute(f"SELECT rowid FROM {table} WHERE {table} MATCH 'receipt'").fetchall() == []
        db.execute("INSERT INTO messages_fts(rowid,content) VALUES (1,'orphan postings')")
    assert not hermes_receipt_absence_verified(plan.locator_sha256, "target", message_ids=result["message_ids"])


def test_hermes_db_visible_export_preserves_native_roles_without_reasoning(hermes_database):
    database, _project = hermes_database
    adapter = HermesAdapter(None, state_db=database)
    export = adapter.read_session_source(database, "target")
    assert b"private reasoning" in export["raw_bytes"]
    assert b"private reasoning" not in export["capture_bytes"]
    messages = hermes_sqlite_export_messages(export["capture_bytes"], "target")
    assert [row["role"] for row in messages] == ["user", "assistant"]
    observation = adapter.session_to_observation(database, "target")
    _, exchanges, _ = _parse_exchanges(observation.raw_content)
    assert [user for exchange in exchanges for user in exchange["user"]] == ["Keep the signed receipt."]
    assert "User: quoted text" in exchanges[0]["assistant"][0]
