"""SQLiteIndex — SQLite FTS wrapper for harness-mem.

Provides full-text search and metadata indexing for all memory entities.
Each entity type gets its own table + FTS virtual table.
"""

from __future__ import annotations
import builtins
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

_TABLE_SCHEMAS = {
    "observations": """
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        client TEXT NOT NULL,
        content_type TEXT NOT NULL,
        raw_content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        metadata TEXT NOT NULL DEFAULT '{}',
        compacted INTEGER NOT NULL DEFAULT 0
    """,
    "memory_entries": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.8,
        status TEXT NOT NULL DEFAULT 'accepted',
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        compacted INTEGER NOT NULL DEFAULT 0,
        usage_count INTEGER NOT NULL DEFAULT 0,
        last_accessed_at TEXT
    """,
    "task_handoffs": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        task_id TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'in_progress',
        last_activity TEXT NOT NULL,
        next_steps TEXT NOT NULL DEFAULT '[]',
        blockers TEXT NOT NULL DEFAULT '[]',
        context TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    """,
    "rule_candidates": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        session_id TEXT NOT NULL,
        pattern TEXT NOT NULL,
        trigger TEXT NOT NULL,
        examples TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    """,
    "confirmed_rules": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        pattern TEXT NOT NULL,
        trigger TEXT NOT NULL,
        examples TEXT NOT NULL DEFAULT '[]',
        confirmed_at TEXT NOT NULL,
        source_candidate_id TEXT NOT NULL,
        source_session_id TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]'
    """,
    "relation_facts": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        source_entity TEXT NOT NULL,
        target_entity TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.7,
        status TEXT NOT NULL DEFAULT 'accepted',
        evidence TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]'
    """,
}

_COLUMN_MIGRATIONS = {
    "observations": {
        "compacted": "INTEGER NOT NULL DEFAULT 0",
    },
    "memory_entries": {
        "status": "TEXT NOT NULL DEFAULT 'accepted'",
        "compacted": "INTEGER NOT NULL DEFAULT 0",
        "usage_count": "INTEGER NOT NULL DEFAULT 0",
        "last_accessed_at": "TEXT",
    },
    "relation_facts": {
        "status": "TEXT NOT NULL DEFAULT 'accepted'",
    },
    "confirmed_rules": {
        "source_session_id": "TEXT NOT NULL DEFAULT ''",
    },
}

_STOP_WORDS = {
    "what", "when", "where", "who", "how", "which", "did", "do", "was", "were",
    "have", "has", "had", "is", "are", "the", "a", "an", "my", "me", "i", "you",
    "your", "their", "it", "its", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "ago", "last", "that", "this", "there", "about", "get", "got",
    "give", "gave", "buy", "bought", "made", "make", "said",
}


class SQLiteIndex:
    """Thread-safe SQLite wrapper with FTS5 full-text search.

    Data layout per table:
    - Main table: all columns as TEXT (JSON-serialized)
    - FTS5 virtual table: content column for full-text search
    - Tag/id indexes for fast lookups

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._fts_lock = threading.Lock()

    def init_db(self) -> None:
        """Create all tables and FTS virtual tables if they don't exist."""
        conn = self._conn_write()
        for table_name, columns in _TABLE_SCHEMAS.items():
            # Main table
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} ({columns})"
            )
            # FTS virtual table for full-text search on 'content' or 'raw_content' field
            fts_col = "raw_content" if table_name == "observations" else (
                "content" if table_name == "memory_entries" else
                "pattern" if table_name in ("rule_candidates", "confirmed_rules") else
                "evidence" if table_name == "relation_facts" else
                "summary"
            )
            fts_table = f"{table_name}_fts"
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} USING fts5(
                    {fts_col}, content='{table_name}', content_rowid='rowid'
                )
            """)
            # Triggers to keep FTS in sync
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {table_name}_ai AFTER INSERT ON {table_name} BEGIN
                    INSERT INTO {fts_table}(rowid, {fts_col})
                    VALUES (NEW.rowid, NEW.{fts_col});
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {table_name}_ad AFTER DELETE ON {table_name} BEGIN
                    INSERT INTO {fts_table}({fts_table}, rowid, {fts_col})
                    VALUES ('delete', OLD.rowid, OLD.{fts_col});
                END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {table_name}_au AFTER UPDATE ON {table_name} BEGIN
                    INSERT INTO {fts_table}({fts_table}, rowid, {fts_col})
                    VALUES ('delete', OLD.rowid, OLD.{fts_col});
                    INSERT INTO {fts_table}(rowid, {fts_col})
                    VALUES (NEW.rowid, NEW.{fts_col});
                END
            """)
            self._ensure_columns(conn, table_name)
        conn.commit()

    def _conn_write(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=10, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def insert(self, table: str, data: dict[str, Any]) -> str:
        """Insert a row into table. Returns the row id."""
        conn = self._conn_write()
        # Serialize complex fields
        row = dict(data)
        for key, value in list(row.items()):
            if isinstance(value, (list, dict)):
                row[key] = json.dumps(value)
            elif hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            elif value is None:
                row[key] = ""
        cols = list(row.keys())
        placeholders = ",".join(["?"] * len(cols))
        with self._lock:
            conn.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
            conn.commit()
        return data["id"]

    def get(self, table: str, id: str) -> dict | None:
        """Get a single row by id."""
        conn = self._conn_write()
        with self._lock:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE id = ?", (id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(dict(row), table)

    def list(
        self,
        table: str,
        where: str | None = None,
        where_params: tuple = (),
        order_by: str = "created_at DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List rows with optional WHERE clause."""
        conn = self._conn_write()
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        with self._lock:
            rows = conn.execute(
                sql, (*where_params, limit, offset)
            ).fetchall()
        return [self._row_to_dict(dict(r), table) for r in rows]

    def search(
        self,
        table: str,
        query: str,
        limit: int = 20,
        extra_where: str | None = None,
        extra_params: tuple = (),
    ) -> builtins.list[dict[str, Any]]:
        """Full-text search using tokenized FTS5 queries."""
        fts_table = f"{table}_fts"
        conn = self._conn_write()
        tokens = self._tokenize_query(query)
        if not tokens:
            stripped = query.strip()
            if not stripped:
                return []
            tokens = [self._escape_match_token(stripped)]

        candidate_limit = max(limit * 3, 10)
        scored_rows: dict[str, tuple[float, dict]] = {}

        sql = f"""
            SELECT {table}.*, bm25({fts_table}) AS score FROM {table}
            JOIN {fts_table} ON {table}.rowid = {fts_table}.rowid
            WHERE {fts_table} MATCH ?
        """
        if extra_where:
            sql += f" AND {extra_where}"
        sql += " ORDER BY score LIMIT ?"

        with self._fts_lock:
            for token in tokens:
                params: tuple = (token,)
                if extra_where:
                    params = (*params, *extra_params)
                params = (*params, candidate_limit)
                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    row_dict = dict(row)
                    row_id = row_dict["id"]
                    score = float(row_dict.pop("score"))
                    best = scored_rows.get(row_id)
                    if best is None or score < best[0]:
                        scored_rows[row_id] = (score, row_dict)

        sorted_rows = []
        for score, row in sorted(scored_rows.values(), key=lambda item: item[0])[:limit]:
            row["_fts_score"] = score
            sorted_rows.append(row)
        return [self._row_to_dict(row, table) for row in sorted_rows]

    def update(self, table: str, id: str, data: dict[str, Any]) -> bool:
        """Update a row. Returns True if updated."""
        conn = self._conn_write()
        row = dict(data)
        for key, value in list(row.items()):
            if isinstance(value, (list, dict)):
                row[key] = json.dumps(value)
            elif hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        set_clause = ",".join([f"{k}=?" for k in row.keys()])
        with self._lock:
            cursor = conn.execute(
                f"UPDATE {table} SET {set_clause} WHERE id=?",
                [*row.values(), id],
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, table: str, id: str) -> bool:
        """Delete a row. Returns True if deleted."""
        conn = self._conn_write()
        with self._lock:
            cursor = conn.execute(f"DELETE FROM {table} WHERE id=?", (id,))
            conn.commit()
            return cursor.rowcount > 0

    def count(self, table: str, where: str | None = None, where_params: tuple = ()) -> int:
        """Count rows matching the WHERE clause."""
        conn = self._conn_write()
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        with self._lock:
            result = conn.execute(sql, where_params).fetchone()
        return result[0] if result else 0

    def _row_to_dict(self, row: dict, table: str) -> dict:
        """Deserialize JSON fields back to Python objects."""
        json_fields = {
            "observations": ["tags", "metadata"],
            "memory_entries": ["tags"],
            "task_handoffs": ["next_steps", "blockers", "context"],
            "rule_candidates": ["examples"],
            "confirmed_rules": ["examples", "tags"],
            "relation_facts": ["tags"],
        }
        fields = json_fields.get(table, [])
        for col in fields:
            if row.get(col) and isinstance(row[col], str):
                try:
                    row[col] = json.loads(row[col])
                except json.JSONDecodeError:
                    pass
        if "compacted" in row:
            row["compacted"] = self._coerce_bool(row["compacted"])
        return row

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"", "0", "false", "no"}:
                return False
            if lowered in {"1", "true", "yes"}:
                return True
        return bool(value)

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}

    def _ensure_columns(self, conn: sqlite3.Connection, table: str) -> None:
        migrations = _COLUMN_MIGRATIONS.get(table, {})
        if not migrations:
            return

        existing = self._table_columns(conn, table)
        for column_name, column_def in migrations.items():
            if column_name in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")

    @staticmethod
    def _escape_match_token(token: str) -> str:
        escaped = token.replace('"', ' ')
        return " ".join(escaped.split())

    @classmethod
    def _tokenize_query(cls, query: str) -> builtins.list[str]:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        tokens = []
        seen = set()
        for raw_token in cleaned.split():
            token = raw_token.lower()
            if token in _STOP_WORDS:
                continue
            token = cls._escape_match_token(token)
            if len(token) >= 3:
                token = f"{token}*"
            if token not in seen:
                seen.add(token)
                tokens.append(token)
        return [token for token in tokens if token]
