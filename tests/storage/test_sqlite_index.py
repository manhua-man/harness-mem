"""Unit tests for SQLiteIndex — FTS search and CRUD operations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.storage.sqlite_index import SQLiteIndex

pytestmark = pytest.mark.storage


@pytest.fixture
def idx(tmp_path: Path):
    db_path = tmp_path / "test.db"
    sqldb = SQLiteIndex(db_path)
    sqldb.init_db()
    yield sqldb
    sqldb.close()


@pytest.fixture
def idx_with_data(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    obs_id = "obs-001"
    idx.insert("observations", {
        "id": obs_id,
        "session_id": "sess-001",
        "client": "claude-code",
        "content_type": "transcript",
        "raw_content": "Using SQLite FTS5 for full-text search",
        "timestamp": now.isoformat(),
        "tags": json.dumps(["search", "sqlite"]),
        "metadata": json.dumps({"project_name": "test-project"}),
    })
    entry_id = "entry-001"
    idx.insert("memory_entries", {
        "id": entry_id,
        "project_name": "test-project",
        "category": "architecture",
        "content": "SQLite FTS5 provides fast full-text search",
        "confidence": 0.9,
        "source": "manual",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "tags": json.dumps(["architecture"]),
    })
    return idx


def test_insert_and_get(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    idx.insert("observations", {
        "id": "obs-test",
        "session_id": "sess-001",
        "client": "test",
        "content_type": "transcript",
        "raw_content": "Test content",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })
    row = idx.get("observations", "obs-test")
    assert row is not None
    assert row["id"] == "obs-test"
    assert row["session_id"] == "sess-001"


def test_insert_memory_entry_roundtrip(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    entry_id = "me-roundtrip"
    idx.insert("memory_entries", {
        "id": entry_id,
        "project_name": "test-project",
        "category": "api",
        "content": "REST API endpoint for users",
        "confidence": 0.85,
        "source": "distill",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "tags": json.dumps(["api", "rest"]),
    })
    row = idx.get("memory_entries", entry_id)
    assert row is not None
    assert row["content"] == "REST API endpoint for users"
    assert row["category"] == "api"
    assert row["tags"] == ["api", "rest"]


def test_list_with_where(idx_with_data: SQLiteIndex):
    rows = idx_with_data.list("memory_entries", where="project_name = ?", where_params=("test-project",))
    assert len(rows) >= 1


def test_search_memory_entries(idx_with_data: SQLiteIndex):
    results = idx_with_data.search("memory_entries", "SQLite FTS5")
    assert len(results) >= 1
    assert "content" in results[0]


def test_search_observations(idx_with_data: SQLiteIndex):
    results = idx_with_data.search("observations", "SQLite FTS5")
    assert len(results) >= 1
    assert "raw_content" in results[0]


def test_search_prefers_rows_matching_more_query_tokens(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    idx.insert("observations", {
        "id": "obs-many-tokens",
        "session_id": "sess-many",
        "client": "claude-code",
        "content_type": "transcript",
        "raw_content": "road trip hours summary with all three concepts",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })
    idx.insert("observations", {
        "id": "obs-one-token",
        "session_id": "sess-one",
        "client": "claude-code",
        "content_type": "transcript",
        "raw_content": "road maintenance note only mentions one concept",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })

    results = idx.search("observations", "road trip hours", limit=5)

    assert results[0]["id"] == "obs-many-tokens"
    assert results[0]["_fts_match_count"] > results[1]["_fts_match_count"]


def test_search_uses_stem_fallback_when_primary_tokens_miss(idx: SQLiteIndex):
    pytest.importorskip("Stemmer")

    now = datetime.now(timezone.utc)
    idx.insert("observations", {
        "id": "obs-stem-fallback",
        "session_id": "sess-stem",
        "client": "claude-code",
        "content_type": "transcript",
        "raw_content": "I participate in a charity event every spring",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })

    results = idx.search("observations", "participated events", limit=5)

    assert any(result["id"] == "obs-stem-fallback" for result in results)


def test_search_with_project_filter(idx_with_data: SQLiteIndex):
    results = idx_with_data.search(
        "memory_entries",
        "SQLite",
        extra_where="project_name = ?",
        extra_params=("test-project",),
    )
    assert all(result["project_name"] == "test-project" for result in results)


def test_update(idx_with_data: SQLiteIndex):
    idx_with_data.update("memory_entries", "entry-001", {"content": "Updated content"})
    row = idx_with_data.get("memory_entries", "entry-001")
    assert row["content"] == "Updated content"


def test_delete(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    idx.insert("observations", {
        "id": "obs-delete",
        "session_id": "sess-001",
        "client": "test",
        "content_type": "transcript",
        "raw_content": "To be deleted",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })
    assert idx.get("observations", "obs-delete") is not None
    idx.delete("observations", "obs-delete")
    assert idx.get("observations", "obs-delete") is None


def test_count(idx_with_data: SQLiteIndex):
    total = idx_with_data.count("memory_entries")
    assert total >= 1
    filtered = idx_with_data.count("memory_entries", where="project_name = ?", where_params=("nonexistent",))
    assert filtered == 0


def test_tokenize_query():
    tokens = SQLiteIndex._tokenize_query("How do I configure SQLite FTS5")
    assert "sqlite" in tokens or any("sqlite*" in token for token in tokens)
    assert "fts5" in tokens or any("fts5*" in token for token in tokens)


def test_expand_query_tokens_adds_stemmed_fallback():
    pytest.importorskip("Stemmer")

    primary, fallback = SQLiteIndex._expand_query_tokens("participated events")

    assert "participated*" in primary
    assert "event*" in fallback or "particip*" in fallback


def test_escape_match_token():
    escaped = SQLiteIndex._escape_match_token('test"query')
    assert '"' not in escaped


def test_json_fields_deserialized(idx_with_data: SQLiteIndex):
    row = idx_with_data.get("memory_entries", "entry-001")
    tags = row.get("tags")
    assert isinstance(tags, list), f"Expected list, got {type(tags)}: {tags}"


def test_fts_sync_on_insert(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    obs_id = "obs-fts-sync"
    idx.insert("observations", {
        "id": obs_id,
        "session_id": "sess-001",
        "client": "test",
        "content_type": "transcript",
        "raw_content": "FTS sync test uniquekeyword123",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })
    results = idx.search("observations", "uniquekeyword123")
    assert len(results) >= 1
    assert results[0]["id"] == obs_id


def test_fts_sync_on_delete(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    obs_id = "obs-fts-del"
    idx.insert("observations", {
        "id": obs_id,
        "session_id": "sess-001",
        "client": "test",
        "content_type": "transcript",
        "raw_content": "FTS delete test keywordXYZ",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })
    results = idx.search("observations", "keywordXYZ")
    assert len(results) >= 1
    idx.delete("observations", obs_id)
    results_after = idx.search("observations", "keywordXYZ")
    assert not any(result["id"] == obs_id for result in results_after)


def test_fts_sync_on_update(idx: SQLiteIndex):
    now = datetime.now(timezone.utc)
    obs_id = "obs-fts-update"
    idx.insert("observations", {
        "id": obs_id,
        "session_id": "sess-001",
        "client": "test",
        "content_type": "transcript",
        "raw_content": "Before update oldkeyword",
        "timestamp": now.isoformat(),
        "tags": "[]",
        "metadata": "{}",
    })

    assert any(result["id"] == obs_id for result in idx.search("observations", "oldkeyword"))

    idx.update("observations", obs_id, {"raw_content": "After update newkeyword"})

    assert not any(result["id"] == obs_id for result in idx.search("observations", "oldkeyword"))
    assert any(result["id"] == obs_id for result in idx.search("observations", "newkeyword"))


def test_blank_search_returns_empty(idx_with_data: SQLiteIndex):
    assert idx_with_data.search("memory_entries", "   ") == []


def test_init_db_migrates_compacted_columns(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE observations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                client TEXT NOT NULL,
                content_type TEXT NOT NULL,
                raw_content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE memory_entries (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    idx = SQLiteIndex(db_path)
    try:
        idx.init_db()
        conn = sqlite3.connect(db_path)
        try:
            observation_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(observations)").fetchall()
            }
            memory_entry_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()
            }
        finally:
            conn.close()
    finally:
        idx.close()

    assert "compacted" in observation_columns
    assert "compacted" in memory_entry_columns


def test_init_db_migrates_skill_scope_columns(tmp_path: Path):
    db_path = tmp_path / "legacy-skills.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE skills (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                name TEXT NOT NULL,
                activation_condition TEXT NOT NULL,
                steps TEXT NOT NULL DEFAULT '[]',
                termination_condition TEXT NOT NULL,
                success_examples TEXT NOT NULL DEFAULT '[]',
                source_candidate_id TEXT NOT NULL DEFAULT '',
                source_session_id TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.7,
                status TEXT NOT NULL DEFAULT 'active',
                usage_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                success_rate REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                search_text TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    idx = SQLiteIndex(db_path)
    try:
        idx.init_db()
        conn = sqlite3.connect(db_path)
        try:
            skill_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(skills)").fetchall()
            }
        finally:
            conn.close()
    finally:
        idx.close()

    assert {
        "scope",
        "origin_project",
        "source_ids",
        "portability_notes",
        "disabled_assumptions",
    }.issubset(skill_columns)
