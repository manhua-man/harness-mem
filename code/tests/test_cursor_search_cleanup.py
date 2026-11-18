"""Cursor search cleanup operates only on isolated SQLite databases."""
from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from harness_mem.adapters.cursor.search_cleanup import (
    SearchCleanupBlocked,
    _CANDIDATES_SQL,
    _CONVERSATIONS_SQL,
    _FTS_SQL,
    delete_search_rows,
    restore_search_rows,
    search_rows_absent,
    search_rows_sha256,
    select_search_rows,
)


def _write_document(db, rowid, identity, body, *, source="local", scope="", archived=1):
    title, branches = f"Title {identity}", "[]"
    db.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rowid, source, scope, identity, title, branches, 123, archived,
         "a" * 64 if source == "local" else None, None if source == "local" else "cache"),
    )
    db.execute("INSERT INTO conversation_fts (rowid, title, body, branches) VALUES (?, ?, ?, ?)",
               (rowid, title, body, branches))


@pytest.fixture
def search_db(tmp_path):
    database = tmp_path / "conversation-search.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        for ddl in (_CONVERSATIONS_SQL, _CANDIDATES_SQL, _FTS_SQL):
            db.execute(ddl)
        _write_document(db, 1, "archive", "selectedexact")
        _write_document(db, 2, "archive-neighbor", "neighborunique")
        _write_document(db, 3, "current", "currentunique", archived=0)
        db.executemany("INSERT INTO conversation_search_candidates VALUES (?, 124)",
                       [("archive",), ("archive-neighbor",), ("current",)])
        db.commit()
    return database


def _matches(db, word):
    return db.execute("SELECT rowid FROM conversation_fts WHERE conversation_fts MATCH ?", (word,)).fetchall()


def test_delete_rollback_commit_and_exact_restore(search_db):
    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN IMMEDIATE")
        selected = select_search_rows(db, "archive")
        neighbor = select_search_rows(db, "archive-neighbor")
        assert selected is not None and neighbor is not None
        original = search_rows_sha256(selected)
        delete_search_rows(db, selected)
        assert search_rows_absent(db, selected) and not _matches(db, "selectedexact")
        db.rollback()

    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN IMMEDIATE")
        assert select_search_rows(db, "archive") == selected
        assert _matches(db, "selectedexact") == [(1,)]
        delete_search_rows(db, selected)
        db.commit()

    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN IMMEDIATE")
        assert search_rows_absent(db, selected)
        assert select_search_rows(db, "archive-neighbor") == neighbor
        assert _matches(db, "neighborunique") == [(2,)]
        assert _matches(db, "currentunique") == [(3,)]
        restore_search_rows(db, selected)
        restore_search_rows(db, selected)
        db.commit()

    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN")
        restored = select_search_rows(db, "archive")
        assert restored is not None and search_rows_sha256(restored) == original
        assert select_search_rows(db, "archive-neighbor") == neighbor
        assert _matches(db, "selectedexact") == [(1,)]
        db.execute("INSERT INTO conversation_fts(conversation_fts) VALUES ('integrity-check')")


@pytest.mark.parametrize(("mutation", "reason"), [
    ("DELETE FROM conversation_search_candidates WHERE id='archive'", "cursor_cleanup_search_identity_unverified"),
    ("UPDATE conversations SET is_archived=0 WHERE id='archive'", "cursor_cleanup_search_archive_unverified"),
    ("UPDATE conversations SET title='unindexed' WHERE id='archive'", "cursor_cleanup_search_fts_unverified"),
    ("DELETE FROM conversation_fts WHERE rowid=1", "cursor_cleanup_search_fts_unverified"),
    ("ALTER TABLE conversations ADD COLUMN extra TEXT", "cursor_cleanup_search_schema_unverified"),
])
def test_search_rejects_unproved_state(search_db, mutation, reason):
    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN")
        db.execute(mutation)
        with pytest.raises(SearchCleanupBlocked, match=reason):
            select_search_rows(db, "archive")


def test_same_id_cloud_copy_is_not_owned(search_db):
    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN")
        _write_document(db, 4, "archive", "cloudunique", source="cloud-cache", scope="account")
        with pytest.raises(SearchCleanupBlocked, match="cursor_cleanup_search_identity_unverified"):
            select_search_rows(db, "archive")
        assert _matches(db, "cloudunique") == [(4,)]


def test_delete_and_restore_refuse_changed_witness_or_reused_rowid(search_db):
    with closing(sqlite3.connect(search_db)) as db:
        db.execute("BEGIN IMMEDIATE")
        selected = select_search_rows(db, "archive")
        assert selected is not None
        db.execute("UPDATE conversation_search_candidates SET updated_at=500 WHERE id='archive'")
        with pytest.raises(SearchCleanupBlocked, match="cursor_cleanup_search_source_changed"):
            delete_search_rows(db, selected)
        assert _matches(db, "selectedexact") == [(1,)]
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        delete_search_rows(db, selected)
        _write_document(db, 1, "new-document", "reusedrowid")
        assert select_search_rows(db, "archive") is None
        assert not search_rows_absent(db, selected)
        with pytest.raises(SearchCleanupBlocked, match="cursor_cleanup_search_restore_conflict"):
            restore_search_rows(db, selected)
        assert _matches(db, "reusedrowid") == [(1,)]
        assert not _matches(db, "selectedexact")
