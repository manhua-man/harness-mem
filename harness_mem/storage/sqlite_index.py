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
        last_accessed_at TEXT,
        memory_type TEXT NOT NULL DEFAULT 'semantic',
        valid_from TEXT,
        valid_to TEXT,
        recorded_at TEXT,
        supersedes TEXT NOT NULL DEFAULT '[]',
        superseded_by TEXT NOT NULL DEFAULT '[]'
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
    "supersede_candidates": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        replacement_type TEXT NOT NULL,
        replacement_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.7,
        status TEXT NOT NULL DEFAULT 'pending',
        source TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewer_id TEXT
    """,
    "procedural_candidates": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        activation_condition TEXT NOT NULL,
        steps TEXT NOT NULL DEFAULT '[]',
        termination_condition TEXT NOT NULL,
        success_examples TEXT NOT NULL DEFAULT '[]',
        source_session_id TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        search_text TEXT NOT NULL
    """,
    "skills": """
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
        tags TEXT NOT NULL DEFAULT '[]',
        usage_count INTEGER NOT NULL DEFAULT 0,
        last_surfaced_at TEXT,
        valid_from TEXT,
        valid_to TEXT,
        recorded_at TEXT,
        supersedes TEXT NOT NULL DEFAULT '[]',
        superseded_by TEXT NOT NULL DEFAULT '[]'
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
        tags TEXT NOT NULL DEFAULT '[]',
        valid_from TEXT,
        valid_to TEXT,
        recorded_at TEXT,
        supersedes TEXT NOT NULL DEFAULT '[]',
        superseded_by TEXT NOT NULL DEFAULT '[]'
    """,
    "vec_embeddings": """
        entry_id TEXT PRIMARY KEY,
        model_id TEXT NOT NULL,
        model_version TEXT NOT NULL,
        embedding BLOB NOT NULL,
        created_at INTEGER NOT NULL
    """,
    "metabolism_runs": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'preview',
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL DEFAULT 'preview',
        duration_ms INTEGER NOT NULL DEFAULT 0
    """,
    "retrieval_signals": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        value REAL
    """,
    "merge_suggestion_candidates": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        target_a_id TEXT NOT NULL,
        target_a_kind TEXT NOT NULL,
        target_b_id TEXT NOT NULL,
        target_b_kind TEXT NOT NULL,
        similarity_score REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        metabolism_run_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    """,
    "stale_truth_suggestion_candidates": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        target_id TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        last_surfaced_at TEXT,
        days_since_last_surface INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        metabolism_run_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    """,
    "reflection_jobs": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'reflection',
        phase TEXT NOT NULL DEFAULT 'ingest',
        status TEXT NOT NULL DEFAULT 'pending',
        source TEXT NOT NULL,
        idempotency_key TEXT,
        data TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        lease_owner TEXT,
        lease_until TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0
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
        "memory_type": "TEXT NOT NULL DEFAULT 'semantic'",
        "valid_from": "TEXT",
        "valid_to": "TEXT",
        "recorded_at": "TEXT",
        "supersedes": "TEXT NOT NULL DEFAULT '[]'",
        "superseded_by": "TEXT NOT NULL DEFAULT '[]'",
    },
    "relation_facts": {
        "status": "TEXT NOT NULL DEFAULT 'accepted'",
        "valid_from": "TEXT",
        "valid_to": "TEXT",
        "recorded_at": "TEXT",
        "supersedes": "TEXT NOT NULL DEFAULT '[]'",
        "superseded_by": "TEXT NOT NULL DEFAULT '[]'",
    },
    "confirmed_rules": {
        "source_session_id": "TEXT NOT NULL DEFAULT ''",
        "usage_count": "INTEGER NOT NULL DEFAULT 0",
        "last_surfaced_at": "TEXT",
        "valid_from": "TEXT",
        "valid_to": "TEXT",
        "recorded_at": "TEXT",
        "supersedes": "TEXT NOT NULL DEFAULT '[]'",
        "superseded_by": "TEXT NOT NULL DEFAULT '[]'",
    },
}

_STOP_WORDS = {
    "what", "when", "where", "who", "how", "which", "did", "do", "was", "were",
    "have", "has", "had", "is", "are", "the", "a", "an", "my", "me", "i", "you",
    "your", "their", "it", "its", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "ago", "last", "that", "this", "there", "about", "get", "got",
    "give", "gave", "buy", "bought", "made", "make", "said",
}

_PORTER_STEMMER: Any | None = None
_PORTER_STEMMER_LOADED = False


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
            # Skip FTS for vec_embeddings (vector table doesn't need full-text search)
            if table_name == "vec_embeddings":
                continue
            # Skip FTS for metabolism_runs / retrieval_signals / reflection_jobs —
            # they index structured rows, not full-text content.
            if table_name in ("metabolism_runs", "retrieval_signals", "reflection_jobs"):
                # structured signal rows, queried by (project, time, type) not by
                # free text. Avoids a no-op FTS table and unused triggers.
                continue
            # Skip FTS for the v2.3.1 suggestion candidate tables — they are
            # filter/sort indexes only; full content (proposed_content,
            # evidence_signal_ids) lives in the JSON blob.
            if table_name in (
                "merge_suggestion_candidates",
                "stale_truth_suggestion_candidates",
            ):
                continue
            # FTS virtual table for full-text search on 'content' or 'raw_content' field
            fts_col = "raw_content" if table_name == "observations" else (
                "content" if table_name == "memory_entries" else
                "search_text" if table_name in ("procedural_candidates", "skills") else
                "pattern" if table_name in ("rule_candidates", "confirmed_rules") else
                "evidence" if table_name == "supersede_candidates" else
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
        self._ensure_verbatim_exact_index(conn)
        self._ensure_suggestion_candidate_indexes(conn)
        conn.commit()

    def _conn_write(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=10, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
            # Load sqlite-vec extension for vector storage (Windows-compatible)
            try:
                self._conn.enable_load_extension(True)
                try:
                    import sqlite_vec  # type: ignore[import-not-found]
                    sqlite_vec.load(self._conn)
                except ImportError:
                    # sqlite-vec not installed, skip (will fallback to FTS in hybrid search)
                    pass
                self._conn.enable_load_extension(False)
            except sqlite3.OperationalError as e:
                # Extension loading disabled in this SQLite build
                # Raise HM-202 error with clear guidance
                raise RuntimeError(
                    "HM-202: SQLite extension loading disabled. "
                    "This SQLite build does not support loading extensions. "
                    "Either recompile sqlite with SQLITE_OMIT_LOAD_EXTENSION undefined, "
                    "or use FTS mode (set mode=fts in search commands)."
                ) from e
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def persist_embedding(
        self,
        entry_id: str,
        text: str,
        model_id: str,
        model_version: str | None = None,
    ) -> None:
        """Persist embedding vector for an entry.

        Args:
            entry_id: Entry identifier (observation id or memory entry id)
            text: Text content to encode
            model_id: Embedding model identifier
            model_version: Model version string. If omitted, the active
                loader's version is recorded after the first encode.
        """
        try:
            from harness_mem.embedding import embeddings_disabled, get_model_loader
            import numpy as np
        except ImportError:
            # Embedding dependencies not installed, skip silently
            return

        if embeddings_disabled():
            # Opt-out escape hatch (HARNESS_MEM_DISABLE_EMBEDDINGS): skip model
            # loading entirely so environments with a broken/hanging embedding
            # stack can still persist entries without a vector row.
            return

        loader = get_model_loader(model_id)
        embedding = loader.encode(text)

        embedding_array = np.asarray(embedding, dtype=np.float32).ravel()
        embedding_blob = embedding_array.tobytes()
        stored_model_version = model_version or loader.model_version

        import time
        conn = self._conn_write()
        with self._lock:
            conn.execute(
                """
                INSERT OR REPLACE INTO vec_embeddings
                (entry_id, model_id, model_version, embedding, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    model_id,
                    stored_model_version,
                    embedding_blob,
                    int(time.time()),
                ),
            )
            conn.commit()

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
        primary_tokens, fallback_tokens = self._expand_query_tokens(query)
        if not primary_tokens:
            stripped = query.strip()
            if not stripped:
                return []
            primary_tokens = [self._escape_match_token(stripped)]

        candidate_limit = max(limit * 3, 10)
        scored_rows: dict[str, dict[str, Any]] = {}

        sql = f"""
            SELECT {table}.*, bm25({fts_table}) AS score FROM {table}
            JOIN {fts_table} ON {table}.rowid = {fts_table}.rowid
            WHERE {fts_table} MATCH ?
        """
        if extra_where:
            sql += f" AND {extra_where}"
        sql += " ORDER BY score LIMIT ?"

        with self._fts_lock:
            self._accumulate_token_matches(
                conn,
                sql,
                primary_tokens,
                scored_rows,
                candidate_limit,
                extra_where=extra_where,
                extra_params=extra_params,
            )
            if len(scored_rows) < limit and fallback_tokens:
                self._accumulate_token_matches(
                    conn,
                    sql,
                    fallback_tokens,
                    scored_rows,
                    candidate_limit,
                    extra_where=extra_where,
                    extra_params=extra_params,
                )

        sorted_rows = []
        ranked_rows = sorted(
            scored_rows.values(),
            key=lambda item: (
                -len(set(item["matched_tokens"])),
                -float(item["score_total"]),
                float(item["best_score"]),
            ),
        )[:limit]
        for item in ranked_rows:
            row = dict(item["row"])
            row["_fts_score"] = float(item["best_score"])
            row["_fts_score_total"] = float(item["score_total"])
            row["_fts_match_count"] = len(set(item["matched_tokens"]))
            sorted_rows.append(row)
        return [self._row_to_dict(row, table) for row in sorted_rows]

    def _accumulate_token_matches(
        self,
        conn: sqlite3.Connection,
        sql: str,
        tokens: builtins.list[str],
        scored_rows: dict[str, dict[str, Any]],
        candidate_limit: int,
        *,
        extra_where: str | None,
        extra_params: tuple,
    ) -> None:
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
                if best is None:
                    scored_rows[row_id] = {
                        "best_score": score,
                        "score_total": abs(score),
                        "matched_tokens": {token},
                        "row": row_dict,
                    }
                    continue

                if score < float(best["best_score"]):
                    best["best_score"] = score
                    best["row"] = row_dict
                best["score_total"] = float(best["score_total"]) + abs(score)
                matched_tokens = set(best["matched_tokens"])
                matched_tokens.add(token)
                best["matched_tokens"] = matched_tokens

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

    def replace_observation_trigrams(self, observation_id: str, text: str) -> int:
        """Replace trigram postings for one observation raw_content blob."""
        trigrams = sorted(_trigrams(text))
        conn = self._conn_write()
        with self._lock:
            conn.execute(
                "DELETE FROM observation_trigrams WHERE observation_id = ?",
                (observation_id,),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO observation_trigrams (ngram, observation_id)
                VALUES (?, ?)
                """,
                [(ngram, observation_id) for ngram in trigrams],
            )
            conn.commit()
        return len(trigrams)

    def delete_observation_trigrams(self, observation_id: str) -> None:
        """Delete exact-search postings for one observation."""
        conn = self._conn_write()
        with self._lock:
            conn.execute(
                "DELETE FROM observation_trigrams WHERE observation_id = ?",
                (observation_id,),
            )
            conn.commit()

    def candidate_observation_ids_for_trigrams(
        self,
        trigrams: set[str],
        *,
        limit: int = 1000,
    ) -> builtins.list[str]:
        """Return observation ids containing every requested trigram."""
        if not trigrams:
            return []
        conn = self._conn_write()
        ordered = sorted(trigrams)
        placeholders = ",".join(["?"] * len(ordered))
        sql = f"""
            SELECT observation_id
            FROM observation_trigrams
            WHERE ngram IN ({placeholders})
            GROUP BY observation_id
            HAVING COUNT(DISTINCT ngram) = ?
            LIMIT ?
        """
        with self._lock:
            rows = conn.execute(sql, (*ordered, len(ordered), limit)).fetchall()
        return [str(row["observation_id"]) for row in rows]

    def observation_trigram_stats(self) -> dict[str, int]:
        """Return small health counters for the exact evidence index."""
        conn = self._conn_write()
        with self._lock:
            posting_count = conn.execute(
                "SELECT COUNT(*) FROM observation_trigrams"
            ).fetchone()[0]
            indexed_count = conn.execute(
                "SELECT COUNT(DISTINCT observation_id) FROM observation_trigrams"
            ).fetchone()[0]
        return {
            "posting_count": int(posting_count),
            "indexed_observation_count": int(indexed_count),
        }

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
            "memory_entries": ["tags", "supersedes", "superseded_by"],
            "task_handoffs": ["next_steps", "blockers", "context"],
            "rule_candidates": ["examples"],
            "procedural_candidates": ["steps", "success_examples"],
            "skills": ["steps", "success_examples"],
            "confirmed_rules": ["examples", "tags", "supersedes", "superseded_by"],
            "relation_facts": ["tags", "supersedes", "superseded_by"],
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

    def _ensure_verbatim_exact_index(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS observation_trigrams (
                ngram TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                PRIMARY KEY (ngram, observation_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_observation_trigrams_observation
            ON observation_trigrams(observation_id)
        """)

    def _ensure_suggestion_candidate_indexes(self, conn: sqlite3.Connection) -> None:
        """Secondary indexes for v2.3.1 suggestion candidate tables.

        Mirrors the existing approach in :meth:`_ensure_verbatim_exact_index`:
        keep auxiliary indexes out of ``_TABLE_SCHEMAS`` and create them with
        ``CREATE INDEX IF NOT EXISTS`` so they are idempotent.

        The composite ``(target_a_id, target_b_id)`` index on
        ``merge_suggestion_candidates`` powers the dedupe lookup the metabolism
        proposer uses to skip pairs it has already proposed (the pair is
        normalized to ``target_a_id < target_b_id`` at construction time, so
        the natural key matches exactly).
        """
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_suggestion_candidates_project
            ON merge_suggestion_candidates(project_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_suggestion_candidates_status
            ON merge_suggestion_candidates(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_suggestion_candidates_run
            ON merge_suggestion_candidates(metabolism_run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_suggestion_candidates_pair
            ON merge_suggestion_candidates(target_a_id, target_b_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_stale_truth_suggestion_candidates_project
            ON stale_truth_suggestion_candidates(project_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_stale_truth_suggestion_candidates_status
            ON stale_truth_suggestion_candidates(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_stale_truth_suggestion_candidates_run
            ON stale_truth_suggestion_candidates(metabolism_run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_stale_truth_suggestion_candidates_target
            ON stale_truth_suggestion_candidates(target_id)
        """)

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

    @classmethod
    def _expand_query_tokens(
        cls,
        query: str,
    ) -> tuple[builtins.list[str], builtins.list[str]]:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        primary: builtins.list[str] = []
        fallback: builtins.list[str] = []
        seen_primary: set[str] = set()
        seen_fallback: set[str] = set()

        for raw_token in cleaned.split():
            token = raw_token.lower()
            if token in _STOP_WORDS:
                continue

            primary_token = cls._format_match_token(token)
            if primary_token and primary_token not in seen_primary:
                seen_primary.add(primary_token)
                primary.append(primary_token)

            stemmed = cls._porter_stem(token)
            if not stemmed or stemmed == token:
                continue
            fallback_token = cls._format_match_token(stemmed)
            if (
                fallback_token
                and fallback_token not in seen_primary
                and fallback_token not in seen_fallback
            ):
                seen_fallback.add(fallback_token)
                fallback.append(fallback_token)

        return primary, fallback

    @classmethod
    def _format_match_token(cls, token: str) -> str:
        token = cls._escape_match_token(token)
        if not token:
            return ""
        if len(token) >= 3:
            return f"{token}*"
        return token

    @classmethod
    def _porter_stem(cls, token: str) -> str:
        global _PORTER_STEMMER, _PORTER_STEMMER_LOADED
        if not _PORTER_STEMMER_LOADED:
            _PORTER_STEMMER_LOADED = True
            try:
                import Stemmer  # type: ignore[import-not-found]

                _PORTER_STEMMER = Stemmer.Stemmer("porter")
            except Exception:
                _PORTER_STEMMER = None
        if _PORTER_STEMMER is None:
            return token
        try:
            return str(_PORTER_STEMMER.stemWord(token))
        except Exception:
            return token


def _trigrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {
        normalized[index:index + 3]
        for index in range(0, len(normalized) - 2)
    }
