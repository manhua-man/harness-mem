"""SQLiteIndex — SQLite FTS wrapper for harness-mem.

Provides full-text search and metadata indexing for all memory entities.
Each entity type gets its own table + FTS virtual table.
"""

from __future__ import annotations
import json
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
        metadata TEXT NOT NULL DEFAULT '{}'
    """,
    "memory_entries": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.8,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]'
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
        tags TEXT NOT NULL DEFAULT '[]'
    """,
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
            cursor = conn.execute(
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
        return self._row_to_dict(dict(row))

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
        return [self._row_to_dict(dict(r)) for r in rows]

    def search(
        self,
        table: str,
        query: str,
        limit: int = 20,
        extra_where: str | None = None,
        extra_params: tuple = (),
    ) -> list[dict]:
        """Full-text search using FTS5."""
        fts_table = f"{table}_fts"
        conn = self._conn_write()

        # Determine which column to search
        fts_col = "raw_content" if table == "observations" else (
            "content" if table == "memory_entries" else
            "pattern" if table in ("rule_candidates", "confirmed_rules") else
            "summary"
        )

        sql = f"""
            SELECT {table}.* FROM {table}
            JOIN {fts_table} ON {table}.rowid = {fts_table}.rowid
            WHERE {fts_table} MATCH ?
        """
        params: tuple = (f'"{query}"',)
        if extra_where:
            sql += f" AND {extra_where}"
            params = (*params, *extra_params)
        sql += " LIMIT ?"
        params = (*params, limit)

        with self._fts_lock:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(dict(r)) for r in rows]

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

    def _row_to_dict(self, row: dict) -> dict:
        """Deserialize JSON fields back to Python objects."""
        json_fields = {
            "observations": ["tags", "metadata"],
            "memory_entries": ["tags"],
            "task_handoffs": ["next_steps", "blockers", "context"],
            "rule_candidates": ["examples"],
            "confirmed_rules": ["examples", "tags"],
        }
        table = None
        for t, cols in json_fields.items():
            if all(c in row for c in cols):
                table = t
                break
        if table:
            for col in json_fields[table]:
                if row.get(col) and isinstance(row[col], str):
                    try:
                        row[col] = json.loads(row[col])
                    except json.JSONDecodeError:
                        pass
        return row
