"""Exact row mutations for a recognized Cursor conversation search store.

Connections and transactions belong to the cross-store cleanup coordinator.
No operation here commits, rolls back, opens a database, or edits FTS shadows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
import sqlite3
from typing import Any


class SearchCleanupBlocked(ValueError):
    """The search store cannot safely participate in this cleanup."""


_CONVERSATIONS_SQL = """CREATE TABLE conversations (
    fts_rowid INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('local', 'cloud-cache')),
    scope TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    branches TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    is_archived INTEGER NOT NULL,
    root_fingerprint TEXT,
    cache_fingerprint TEXT,
    UNIQUE(source, scope, id),
    CHECK (
        (source = 'local' AND scope = '' AND root_fingerprint IS NOT NULL AND cache_fingerprint IS NULL)
        OR (source = 'cloud-cache' AND scope <> '' AND root_fingerprint IS NULL)
    )
)"""
_CANDIDATES_SQL = """CREATE TABLE conversation_search_candidates (
    id TEXT PRIMARY KEY, updated_at INTEGER NOT NULL
)"""
_FTS_SQL = """CREATE VIRTUAL TABLE conversation_fts USING fts5(
    title, body, branches, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3'
)"""
_TABLES = {
    "conversations": _CONVERSATIONS_SQL,
    "conversation_search_candidates": _CANDIDATES_SQL,
    "conversation_fts": _FTS_SQL,
    "conversation_fts_config": "CREATE TABLE 'conversation_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID",
    "conversation_fts_content": "CREATE TABLE 'conversation_fts_content'(id INTEGER PRIMARY KEY, c0, c1, c2)",
    "conversation_fts_data": "CREATE TABLE 'conversation_fts_data'(id INTEGER PRIMARY KEY, block BLOB)",
    "conversation_fts_docsize": "CREATE TABLE 'conversation_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB)",
    "conversation_fts_idx": "CREATE TABLE 'conversation_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID",
}
_OPTIONAL_TABLES = {
    "conversation_search_reconciliation": """CREATE TABLE conversation_search_reconciliation (
        id INTEGER PRIMARY KEY CHECK (id = 1), cursor TEXT NOT NULL, in_progress INTEGER NOT NULL
    )""",
    "conversation_search_settings": """CREATE TABLE conversation_search_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1), effective_conversation_cap INTEGER NOT NULL
    )""",
}
_INDEXES = {
    "conversation_search_candidates_recency": """CREATE INDEX conversation_search_candidates_recency
        ON conversation_search_candidates(updated_at DESC, id)""",
    "conversations_recency": """CREATE INDEX conversations_recency
        ON conversations(updated_at DESC, source, scope, id)""",
    "sqlite_autoindex_conversation_search_candidates_1": None,
    "sqlite_autoindex_conversations_1": None,
}
_CONVERSATION_COLUMNS = (
    "fts_rowid, source, scope, id, title, branches, updated_at, is_archived, "
    "root_fingerprint, cache_fingerprint"
)


@dataclass(frozen=True)
class SearchRows:
    identity: str
    conversation: tuple[Any, ...] = field(repr=False)
    fts: tuple[Any, ...] = field(repr=False)
    candidate: tuple[Any, ...] = field(repr=False)

    @property
    def fts_rowid(self) -> int:
        return int(self.conversation[0])


def search_rows_sha256(rows: SearchRows) -> str:
    """Seal all three logical rows, without putting their text in a receipt."""
    raw = json.dumps(
        [rows.identity, rows.conversation, rows.fts, rows.candidate],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _canonical_sql(sql: str | None) -> tuple[str, ...] | None:
    if sql is None:
        return None
    # Keep token boundaries and quoted literals. The FTS options are literal.
    tokens = re.findall(r"'(?:''|[^'])*'|[\w]+|[^\s]", sql)
    return tuple(token if token.startswith("'") else token.lower() for token in tokens)


def _validate_schema(db: sqlite3.Connection) -> None:
    if not db.in_transaction:
        raise SearchCleanupBlocked("cursor_cleanup_search_transaction_required")
    tables = {**_TABLES, **_OPTIONAL_TABLES}
    observed = set()
    for kind, name, sql in db.execute("SELECT type, name, sql FROM main.sqlite_schema"):
        if kind == "table" and name in tables and _canonical_sql(sql) == _canonical_sql(tables[name]):
            observed.add(name)
        elif kind == "index" and name in _INDEXES and _canonical_sql(sql) == _canonical_sql(_INDEXES[name]):
            continue
        elif kind == "table" and name in {"sqlite_stat1", "sqlite_stat4"}:
            continue
        else:
            raise SearchCleanupBlocked("cursor_cleanup_search_schema_unverified")
    if not _TABLES.keys() <= observed:
        raise SearchCleanupBlocked("cursor_cleanup_search_schema_unverified")
    # An unqualified virtual-table module is intentionally never used below.
    # Temporary triggers can still fire for main tables, so reject those too.
    if db.execute("SELECT 1 FROM temp.sqlite_schema WHERE type='trigger' LIMIT 1").fetchone():
        raise SearchCleanupBlocked("cursor_cleanup_search_schema_unverified")


def _fts_footprint(db: sqlite3.Connection, rowid: int) -> tuple[bool, bool]:
    return (
        db.execute("SELECT 1 FROM main.conversation_fts_content WHERE id=?", (rowid,)).fetchone() is not None,
        db.execute("SELECT 1 FROM main.conversation_fts_docsize WHERE id=?", (rowid,)).fetchone() is not None,
    )


def select_search_rows(db: sqlite3.Connection, identity: str) -> SearchRows | None:
    """Read the exact archived local document and its one search candidate."""
    _validate_schema(db)
    conversations = db.execute(
        f"SELECT {_CONVERSATION_COLUMNS} FROM main.conversations WHERE id COLLATE BINARY=?", (identity,),
    ).fetchall()
    candidates = db.execute(
        "SELECT id, updated_at FROM main.conversation_search_candidates WHERE id COLLATE BINARY=?", (identity,),
    ).fetchall()
    if not conversations and not candidates:
        return None
    if len(conversations) != 1 or len(candidates) != 1:
        raise SearchCleanupBlocked("cursor_cleanup_search_identity_unverified")
    conversation, candidate = tuple(conversations[0]), tuple(candidates[0])
    rowid, source, scope, found_id, title, branches, updated_at, archived, root, cache = conversation
    if (
        type(rowid) is not int or rowid <= 0 or (source, scope, found_id) != ("local", "", identity)
        or type(archived) is not int or archived != 1 or type(updated_at) is not int
        or not isinstance(title, str) or not isinstance(branches, str)
        or not isinstance(root, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", root) or cache is not None
        or candidate[0] != identity or type(candidate[1]) is not int
    ):
        raise SearchCleanupBlocked("cursor_cleanup_search_archive_unverified")
    owners = db.execute("SELECT id FROM main.conversations WHERE fts_rowid=?", (rowid,)).fetchall()
    fts_rows = db.execute(
        "SELECT rowid, title, body, branches FROM main.conversation_fts WHERE rowid=?", (rowid,),
    ).fetchall()
    if [tuple(owner) for owner in owners] != [(identity,)] or len(fts_rows) != 1:
        raise SearchCleanupBlocked("cursor_cleanup_search_fts_unverified")
    fts = tuple(fts_rows[0])
    if (
        fts[0] != rowid or fts[1] != title or fts[3] != branches or not isinstance(fts[2], str)
        or _fts_footprint(db, rowid) != (True, True)
    ):
        raise SearchCleanupBlocked("cursor_cleanup_search_fts_unverified")
    return SearchRows(identity, conversation, fts, candidate)


def search_rows_absent(db: sqlite3.Connection, rows: SearchRows) -> bool:
    """Check the exact witness, including FTS rowid after its owner is gone."""
    return search_receipt_absent(db, rows.identity, rows.fts_rowid)


def search_receipt_absent(db: sqlite3.Connection, identity: str, rowid: int) -> bool:
    _validate_schema(db)
    return (
        db.execute(
            "SELECT 1 FROM main.conversations WHERE id COLLATE BINARY=? OR fts_rowid=?",
            (identity, rowid),
        ).fetchone() is None
        and db.execute(
            "SELECT 1 FROM main.conversation_search_candidates WHERE id COLLATE BINARY=?", (identity,),
        ).fetchone() is None
        and _fts_footprint(db, rowid) == (False, False)
    )


def delete_search_rows(db: sqlite3.Connection, rows: SearchRows) -> None:
    """Verify the preimage again, then delete only the selected logical rows."""
    if select_search_rows(db, rows.identity) != rows:
        raise SearchCleanupBlocked("cursor_cleanup_search_source_changed")
    removed_fts = db.execute("DELETE FROM main.conversation_fts WHERE rowid=?", (rows.fts_rowid,))
    removed_conversation = db.execute(
        "DELETE FROM main.conversations WHERE fts_rowid=? AND id COLLATE BINARY=? AND source='local' AND scope=''",
        (rows.fts_rowid, rows.identity),
    )
    removed_candidate = db.execute(
        "DELETE FROM main.conversation_search_candidates WHERE id COLLATE BINARY=?", (rows.identity,),
    )
    if any(result.rowcount != 1 for result in (removed_fts, removed_conversation, removed_candidate)):
        raise SearchCleanupBlocked("cursor_cleanup_search_delete_unverified")
    if not search_rows_absent(db, rows):
        raise SearchCleanupBlocked("cursor_cleanup_search_delete_unverified")


def restore_search_rows(db: sqlite3.Connection, rows: SearchRows) -> None:
    """Restore the recorded preimage if the exact IDs and FTS rowid are free."""
    if select_search_rows(db, rows.identity) == rows:
        return
    if not search_rows_absent(db, rows):
        raise SearchCleanupBlocked("cursor_cleanup_search_restore_conflict")
    db.execute(
        f"INSERT INTO main.conversations ({_CONVERSATION_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows.conversation,
    )
    db.execute("INSERT INTO main.conversation_fts (rowid, title, body, branches) VALUES (?, ?, ?, ?)", rows.fts)
    db.execute("INSERT INTO main.conversation_search_candidates (id, updated_at) VALUES (?, ?)", rows.candidate)
    if select_search_rows(db, rows.identity) != rows:
        raise SearchCleanupBlocked("cursor_cleanup_search_restore_unverified")
