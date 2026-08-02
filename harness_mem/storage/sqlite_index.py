"""SQLiteIndex — SQLite FTS wrapper for harness-mem.

Provides full-text search and metadata indexing for all memory entities.
Each entity type gets its own table + FTS virtual table.
"""

from __future__ import annotations
import builtins
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from uuid import uuid4

from harness_mem.storage.sqlite_vec_index import SqliteVecIndex

logger = logging.getLogger(__name__)

# Write-path embeddings are optional. If the first encode blocks on a cold
# model download or a broken torch install, MCP write tools must still return
# promptly and leave vec row recovery to maintenance rebuild-vector-index / FTS fallback.
# Cold-but-healthy local loads on Windows can spend tens of seconds importing
# and initializing sentence-transformers even when the model snapshot is already
# cached. Keep the write path finite against broken / fresh-download hangs, but
# do not cut off a normal cached model initialization.
EMBEDDING_WRITE_TIMEOUT_SECONDS = 60.0
_EMBEDDING_WRITE_TIMED_OUT_MODELS: set[str] = set()
_EMBEDDING_WRITE_UNCACHED_MODELS: set[str] = set()

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
        status TEXT NOT NULL DEFAULT 'pending',
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
        scope TEXT NOT NULL DEFAULT 'project',
        origin_project TEXT NOT NULL DEFAULT '',
        source_ids TEXT NOT NULL DEFAULT '[]',
        portability_notes TEXT NOT NULL DEFAULT '',
        disabled_assumptions TEXT NOT NULL DEFAULT '[]',
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
        status TEXT NOT NULL DEFAULT 'pending',
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
    "derived_index_manifests": """
        generation_id TEXT PRIMARY KEY,
        index_name TEXT NOT NULL,
        source_generation TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        id_hash TEXT NOT NULL,
        model_id TEXT,
        model_version TEXT,
        dimensions INTEGER,
        status TEXT NOT NULL DEFAULT 'staged',
        created_at TEXT NOT NULL,
        activated_at TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
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
    "dream_runs": """
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL DEFAULT 'completed',
        trigger_source TEXT NOT NULL DEFAULT 'agent',
        reflection_job_id TEXT,
        policy_version TEXT NOT NULL DEFAULT 'v3.1',
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
        "status": "TEXT NOT NULL DEFAULT 'pending'",
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
        "status": "TEXT NOT NULL DEFAULT 'pending'",
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
    "skills": {
        "scope": "TEXT NOT NULL DEFAULT 'project'",
        "origin_project": "TEXT NOT NULL DEFAULT ''",
        "source_ids": "TEXT NOT NULL DEFAULT '[]'",
        "portability_notes": "TEXT NOT NULL DEFAULT ''",
        "disabled_assumptions": "TEXT NOT NULL DEFAULT '[]'",
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
        self._vec_index = SqliteVecIndex()

    def init_db(self) -> None:
        """Create all tables and FTS virtual tables if they don't exist."""
        conn = self._conn_write()
        for table_name, columns in _TABLE_SCHEMAS.items():
            # Main table
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} ({columns})"
            )
            # Skip FTS for vec_embeddings (vector table doesn't need full-text search)
            if table_name in {"vec_embeddings", "derived_index_manifests"}:
                continue
            # Skip FTS for metabolism_runs / dream_runs / retrieval_signals / reflection_jobs —
            # they index structured rows, not full-text content.
            if table_name in ("metabolism_runs", "dream_runs", "retrieval_signals", "reflection_jobs"):
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

    def record_index_generation(
        self,
        *,
        index_name: str,
        source_generation: str,
        row_count: int,
        id_hash: str,
        model_id: str | None = None,
        model_version: str | None = None,
        dimensions: int | None = None,
        metadata: dict[str, Any] | None = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        """Persist a derived-index generation and optionally publish it.

        The manifest lives beside the existing derived tables. It is a
        verification contract, not a second source of truth: canonical rows
        remain authoritative and only an explicit activation changes the
        active pointer.
        """

        if not index_name.strip() or not source_generation.strip() or not id_hash.strip():
            raise ValueError("index_name, source_generation, and id_hash are required")
        conn = self._conn_write()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                payload = self._insert_index_generation(
                    conn,
                    index_name=index_name,
                    source_generation=source_generation,
                    row_count=row_count,
                    id_hash=id_hash,
                    model_id=model_id,
                    model_version=model_version,
                    dimensions=dimensions,
                    metadata=metadata,
                    activate=activate,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return payload

    def _insert_index_generation(
        self,
        conn: sqlite3.Connection,
        *,
        index_name: str,
        source_generation: str,
        row_count: int,
        id_hash: str,
        model_id: str | None = None,
        model_version: str | None = None,
        dimensions: int | None = None,
        metadata: dict[str, Any] | None = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        """Write one manifest inside the caller-owned transaction."""

        if not index_name.strip() or not source_generation.strip() or not id_hash.strip():
            raise ValueError(
                "index_name, source_generation, and id_hash are required"
            )
        generation_id = uuid4().hex
        created_at = datetime.now(timezone.utc)
        payload = {
            "generation_id": generation_id,
            "index_name": index_name,
            "source_generation": source_generation,
            "row_count": max(0, int(row_count)),
            "id_hash": id_hash,
            "model_id": model_id,
            "model_version": model_version,
            "dimensions": dimensions,
            "status": "active" if activate else "staged",
            "created_at": created_at.isoformat(),
            "activated_at": created_at.isoformat() if activate else None,
            "metadata": dict(metadata or {}),
        }
        conn.execute(
            """
            INSERT INTO derived_index_manifests (
                generation_id, index_name, source_generation, row_count,
                id_hash, model_id, model_version, dimensions, status,
                created_at, activated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id, index_name, source_generation, payload["row_count"],
                id_hash, model_id, model_version, dimensions, payload["status"],
                payload["created_at"], payload["activated_at"],
                json.dumps(payload["metadata"], ensure_ascii=False),
            ),
        )
        if activate:
            conn.execute(
                """
                UPDATE derived_index_manifests
                SET status = 'superseded'
                WHERE index_name = ? AND generation_id != ?
                """,
                (index_name, generation_id),
            )
        return payload

    def get_active_index_generation(self, index_name: str) -> dict[str, Any] | None:
        conn = self._conn_write()
        with self._lock:
            row = conn.execute(
                """
                SELECT generation_id, index_name, source_generation, row_count,
                       id_hash, model_id, model_version, dimensions, status,
                       created_at, activated_at, metadata
                FROM derived_index_manifests
                WHERE index_name = ? AND status = 'active'
                ORDER BY activated_at DESC LIMIT 1
                """,
                (index_name,),
            ).fetchone()
        if row is None:
            return None
        return self._manifest_row_to_dict(row)

    def validate_index_generation(
        self,
        index_name: str,
        *,
        row_count: int,
        id_hash: str,
        source_generation: str | None = None,
        model_id: str | None = None,
        dimensions: int | None = None,
    ) -> dict[str, Any]:
        """Compare observed derived-index identity with its active manifest."""

        active = self.get_active_index_generation(index_name)
        if active is None:
            return {
                "has_issue": True,
                "reason": "missing_active_generation",
                "active": None,
            }
        mismatches: list[str] = []
        if int(active["row_count"]) != int(row_count):
            mismatches.append("row_count")
        if str(active["id_hash"]) != str(id_hash):
            mismatches.append("id_hash")
        if (
            source_generation is not None
            and str(active["source_generation"]) != str(source_generation)
        ):
            mismatches.append("source_generation")
        if model_id is not None and active.get("model_id") != model_id:
            mismatches.append("model_id")
        if dimensions is not None and active.get("dimensions") != dimensions:
            mismatches.append("dimensions")
        return {
            "has_issue": bool(mismatches),
            "reason": "manifest_mismatch" if mismatches else "ok",
            "mismatches": mismatches,
            "active": active,
        }

    @staticmethod
    def stable_id_hash(ids: Iterable[str]) -> str:
        """Return an order-independent hash for canonical membership checks."""

        normalized = sorted({str(item) for item in ids if str(item)})
        return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()

    @staticmethod
    def _manifest_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        try:
            payload["metadata"] = json.loads(payload.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload["metadata"] = {}
        return payload

    def _conn_write(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path), timeout=10, check_same_thread=False
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.row_factory = sqlite3.Row
            # Load sqlite-vec extension for vector storage (Windows-compatible)
            try:
                import sqlite_vec  # type: ignore[import-not-found, import-untyped]
            except ImportError:
                # sqlite-vec not installed, skip (will fallback to FTS in hybrid search)
                return self._conn

            enable_load_extension = getattr(self._conn, "enable_load_extension", None)
            if enable_load_extension is None:
                raise RuntimeError(
                    "HM-202: SQLite extension loading disabled. "
                    "This SQLite build does not expose loadable extension support. "
                    "Either recompile sqlite with loadable extensions enabled, "
                    "or use FTS mode (set mode=fts in search commands)."
                )

            try:
                enable_load_extension(True)
                try:
                    sqlite_vec.load(self._conn)
                    self._vec_index.mark_extension_loaded()
                finally:
                    enable_load_extension(False)
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

    @contextmanager
    def locked_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield the shared SQLite connection under the index write lock.

        This is the public boundary for maintenance, migration, and companion
        stores that need atomic SQL not covered by the higher-level index
        helpers. Callers must not reach into ``_conn_write`` or ``_lock``.
        """

        conn = self._conn_write()
        with self._lock:
            yield conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def flush_sensitive_deletes(self) -> None:
        """Commit secure deletes and truncate this derived index WAL."""

        conn = self._conn_write()
        with self._lock:
            conn.commit()
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row is not None and int(row[0] or 0) != 0:
                raise RuntimeError("derived index WAL checkpoint remained busy")

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
            from harness_mem.embedding import (
                embeddings_disabled,
                get_model_loader,
                has_local_model_snapshot,
            )
            import numpy as np
        except ImportError:
            # Embedding dependencies not installed, skip silently
            return

        if embeddings_disabled():
            # Opt-out escape hatch (HARNESS_MEM_DISABLE_EMBEDDINGS): skip model
            # loading entirely so environments with a broken/hanging embedding
            # stack can still persist entries without a vector row.
            return

        if model_id in _EMBEDDING_WRITE_TIMED_OUT_MODELS:
            return

        if model_id in _EMBEDDING_WRITE_UNCACHED_MODELS:
            return

        if not has_local_model_snapshot(model_id):
            _EMBEDDING_WRITE_UNCACHED_MODELS.add(model_id)
            logger.warning(
                "Embedding model %s is not cached locally; skipping write-path "
                "vec generation until process restart instead of triggering a "
                "cold download on the interactive write path.",
                model_id,
            )
            return

        loader = get_model_loader(model_id)
        embedding: Any | None = None
        encode_error: BaseException | None = None
        done = threading.Event()

        def _encode_worker() -> None:
            nonlocal embedding, encode_error
            try:
                embedding = loader.encode(text)
            except BaseException as exc:  # pragma: no cover - re-raised below
                encode_error = exc
            finally:
                done.set()

        threading.Thread(
            target=_encode_worker,
            name=f"harness-mem-embed-{model_id}",
            daemon=True,
        ).start()

        if not done.wait(EMBEDDING_WRITE_TIMEOUT_SECONDS):
            _EMBEDDING_WRITE_TIMED_OUT_MODELS.add(model_id)
            logger.warning(
                "Embedding encode timed out after %.1fs for model %s; "
                "skipping vec write and disabling write-path embeddings for this "
                "model until process restart.",
                EMBEDDING_WRITE_TIMEOUT_SECONDS,
                model_id,
            )
            return

        if encode_error is not None:
            raise encode_error
        if embedding is None:
            return

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
            self._vec_index.upsert_row(
                conn,
                entry_id=entry_id,
                model_id=model_id,
                embedding_blob=embedding_blob,
                dimensions=len(embedding_array),
            )

    def replace_embeddings_batch(
        self,
        records: Iterable[tuple[str, str]],
        *,
        model_id: str,
        batch_size: int = 32,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Encode into staging rows and atomically replace persisted embeddings."""

        from harness_mem.embedding import embeddings_disabled, get_model_loader
        import numpy as np
        import time

        items = list(records)
        total = len(items)
        if embeddings_disabled():
            return {
                "status": "disabled",
                "total": total,
                "encoded": 0,
                "batch_size": max(1, int(batch_size)),
                "model_id": model_id,
            }
        loader = get_model_loader(model_id)
        size = max(1, int(batch_size))
        entry_ids = [str(entry_id) for entry_id, _text in items]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("embedding batch entry ids must be unique")
        staging = f"vec_embeddings_staging_{uuid4().hex}"
        conn = self._conn_write()
        with self._lock:
            source_fingerprint = self._embedding_target_fingerprint(conn, entry_ids)
            conn.execute(
                f"""
                CREATE TABLE {staging} (
                    entry_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        processed = 0
        last_rows: list[tuple[Any, ...]] = []
        try:
            for start in range(0, total, size):
                batch = items[start : start + size]
                vectors = np.asarray(
                    loader.encode([text for _entry_id, text in batch]),
                    dtype=np.float32,
                )
                if vectors.ndim == 1:
                    vectors = vectors.reshape(1, -1)
                if len(vectors) != len(batch):
                    raise ValueError(
                        f"embedding batch size mismatch: {len(vectors)} != {len(batch)}"
                    )
                created_at = int(time.time())
                stored_model_version = loader.model_version
                rows = [
                    (
                        entry_id,
                        model_id,
                        stored_model_version,
                        np.asarray(vector, dtype=np.float32).ravel().tobytes(),
                        created_at,
                    )
                    for (entry_id, _text), vector in zip(batch, vectors)
                ]
                last_rows = rows
                with self._lock:
                    conn.executemany(
                        f"""
                        INSERT OR REPLACE INTO {staging}
                        (entry_id, model_id, model_version, embedding, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    conn.commit()
                processed += len(batch)
                if progress is not None:
                    progress(processed, total)

            with self._lock:
                staged_rows = conn.execute(
                    f"""
                    SELECT entry_id, model_id, model_version, embedding, created_at
                    FROM {staging} ORDER BY entry_id
                    """
                ).fetchall()
                staged = len(staged_rows)
                if staged != total:
                    raise ValueError(f"embedding staging row mismatch: {staged} != {total}")
                staged_fingerprint = self.stable_embedding_rows_hash(staged_rows)
                conn.execute("BEGIN IMMEDIATE")
                if self._embedding_target_fingerprint(conn, entry_ids) != source_fingerprint:
                    raise sqlite3.IntegrityError(
                        "embedding targets changed during batch rebuild"
                    )
                publish_rows = conn.execute(
                    f"""
                    SELECT entry_id, model_id, model_version, embedding, created_at
                    FROM {staging} ORDER BY entry_id
                    """
                ).fetchall()
                if self.stable_embedding_rows_hash(publish_rows) != staged_fingerprint:
                    raise sqlite3.IntegrityError(
                        "embedding staging content changed before publish"
                    )
                old_count = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM vec_embeddings "
                        f"WHERE entry_id IN (SELECT entry_id FROM {staging})"
                    ).fetchone()[0]
                )
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO vec_embeddings
                    (entry_id, model_id, model_version, embedding, created_at)
                    SELECT entry_id, model_id, model_version, embedding, created_at
                    FROM {staging}
                    """
                )
                conn.execute(f"DROP TABLE {staging}")
                new_count = int(
                    conn.execute("SELECT COUNT(*) FROM vec_embeddings").fetchone()[0]
                )
                id_hash = self.stable_id_hash(entry_id for entry_id, _ in items)
                generation = self._insert_index_generation(
                    conn,
                    index_name="embeddings",
                    source_generation=f"canonical-ids:{id_hash}",
                    row_count=processed,
                    id_hash=id_hash,
                    model_id=model_id,
                    model_version=loader.model_version,
                    dimensions=(len(last_rows[0][3]) // 4 if last_rows else None),
                    metadata={
                        "batch_size": size,
                        "new_count": new_count,
                        "content_hash": staged_fingerprint,
                    },
                    activate=True,
                )
                conn.commit()
            return {
                "status": "replaced",
                "total": total,
                "encoded": processed,
                "old_count": old_count,
                "new_count": new_count,
                "batch_size": size,
                "model_id": model_id,
                "model_version": loader.model_version,
                "generation_id": generation["generation_id"],
            }
        except Exception:
            with self._lock:
                conn.rollback()
                conn.execute(f"DROP TABLE IF EXISTS {staging}")
                conn.commit()
            raise

    def _embedding_target_fingerprint(
        self,
        conn: sqlite3.Connection,
        entry_ids: Iterable[str],
    ) -> str:
        """Hash current target rows, including explicit markers for missing ids."""

        normalized = sorted({str(entry_id) for entry_id in entry_ids})
        rows_by_id: dict[str, tuple[Any, ...]] = {}
        for start in range(0, len(normalized), 500):
            batch = normalized[start : start + 500]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"""
                SELECT entry_id, model_id, model_version, embedding, created_at
                FROM vec_embeddings WHERE entry_id IN ({placeholders})
                """,
                batch,
            ).fetchall()
            rows_by_id.update({str(row[0]): tuple(row) for row in rows})
        fingerprint_rows = [
            rows_by_id.get(entry_id, (entry_id, "<missing>", "", b"", -1))
            for entry_id in normalized
        ]
        return self.stable_embedding_rows_hash(fingerprint_rows)

    @staticmethod
    def stable_embedding_rows_hash(rows: Iterable[tuple[Any, ...]]) -> str:
        """Return a stable content identity for persisted embedding rows."""

        digest = hashlib.sha256()
        normalized = sorted((tuple(row) for row in rows), key=lambda row: str(row[0]))
        for entry_id, model_id, model_version, embedding, created_at in normalized:
            for value in (entry_id, model_id, model_version, created_at):
                encoded = str(value).encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            blob = bytes(embedding or b"")
            digest.update(len(blob).to_bytes(8, "big"))
            digest.update(blob)
        return digest.hexdigest()

    def knn_vec_embeddings(
        self,
        query_blob: bytes,
        *,
        model_id: str,
        limit: int,
        entry_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]] | None:
        """Return cosine-like scores via sqlite-vec KNN when vec0 is available."""

        conn = self._conn_write()
        with self._lock:
            return self._vec_index.knn_vec_embeddings(
                conn,
                query_blob,
                model_id=model_id,
                limit=limit,
                entry_ids=entry_ids,
            )

    def drop_vec0_index(self) -> None:
        conn = self._conn_write()
        with self._lock:
            self._vec_index.drop(conn)

    def vec0_coverage_report(self, *, model_id: str) -> dict[str, int]:
        conn = self._conn_write()
        with self._lock:
            return self._vec_index.vec0_coverage_report(conn, model_id=model_id)

    def vec0_content_identity(self, *, model_id: str) -> dict[str, Any]:
        """Return active vec0 membership and vector-byte identity."""

        conn = self._conn_write()
        with self._lock:
            try:
                rows = conn.execute(
                    """
                    SELECT entry_id, embedding, model_id
                    FROM vec_embeddings_vec0 WHERE model_id = ?
                    """,
                    (model_id,),
                ).fetchall()
            except sqlite3.Error:
                rows = []
        normalized = [
            (str(row[0]), bytes(row[1]), str(row[2])) for row in rows
        ]
        return {
            "row_count": len(normalized),
            "id_hash": self.stable_id_hash(row[0] for row in normalized),
            "content_hash": SqliteVecIndex.stable_vector_fingerprint(normalized),
        }

    def embedding_source_identity(self, *, model_id: str) -> dict[str, Any]:
        """Return canonical persisted-embedding identity for vec0 validation."""

        conn = self._conn_write()
        with self._lock:
            rows = conn.execute(
                """
                SELECT entry_id, embedding, model_id
                FROM vec_embeddings WHERE model_id = ?
                """,
                (model_id,),
            ).fetchall()
        normalized = [
            (str(row[0]), bytes(row[1]), str(row[2])) for row in rows if row[1]
        ]
        return {
            "row_count": len(normalized),
            "id_hash": self.stable_id_hash(row[0] for row in normalized),
            "content_hash": SqliteVecIndex.stable_vector_fingerprint(normalized),
        }

    def rebuild_vec0_index(self, *, model_id: str) -> int:
        """Backfill vec0 from persisted ``vec_embeddings`` rows."""

        conn = self._conn_write()
        with self._lock:
            rows = conn.execute(
                """
                SELECT entry_id, embedding, model_version
                FROM vec_embeddings WHERE model_id = ?
                """,
                (model_id,),
            ).fetchall()
            ids = [str(row[0]) for row in rows]
            dimensions = len(bytes(rows[0][1])) // 4 if rows and rows[0][1] else None
            model_version = str(rows[0][2]) if rows else None
            source_hash = self.stable_id_hash(ids)
            source_content_hash = SqliteVecIndex.stable_vector_fingerprint(
                (str(row[0]), bytes(row[1]), model_id) for row in rows if row[1]
            )

            def publish_generation(
                publish_conn: sqlite3.Connection,
                indexed: int,
                published_ids: tuple[str, ...],
                published_dimensions: int,
                published_content_hash: str,
            ) -> None:
                published_hash = self.stable_id_hash(published_ids)
                if (
                    published_hash != source_hash
                    or published_dimensions != dimensions
                    or published_content_hash != source_content_hash
                ):
                    raise sqlite3.IntegrityError(
                        "vec0 source identity changed before generation publish"
                    )
                self._insert_index_generation(
                    publish_conn,
                    index_name="vec0",
                    source_generation=f"embeddings-content:{published_content_hash}",
                    row_count=indexed,
                    id_hash=published_hash,
                    model_id=model_id,
                    model_version=model_version,
                    dimensions=published_dimensions,
                    metadata={
                        "vec0_indexed": indexed,
                        "content_hash": published_content_hash,
                    },
                    activate=True,
                )

            return self._vec_index.rebuild_from_embeddings(
                conn,
                model_id=model_id,
                publish_generation=publish_generation,
            )

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

    def upsert(self, table: str, data: dict[str, Any]) -> str:
        """Insert or replace one complete entity row by its stable id."""

        conn = self._conn_write()
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
        updates = ",".join(
            f"{column}=excluded.{column}" for column in cols if column != "id"
        )
        with self._lock:
            conn.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                [row[column] for column in cols],
            )
            conn.commit()
        return str(data["id"])

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

    def bulk_upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        """Upsert a homogeneous batch in one transaction (benchmark/repair path)."""

        normalized: list[dict[str, Any]] = []
        for data in rows:
            row = dict(data)
            for key, value in list(row.items()):
                if isinstance(value, (list, dict)):
                    row[key] = json.dumps(value)
                elif hasattr(value, "isoformat"):
                    row[key] = value.isoformat()
                elif value is None:
                    row[key] = ""
            normalized.append(row)
        if not normalized:
            return 0
        columns = list(normalized[0])
        if any(list(row) != columns for row in normalized):
            raise ValueError("bulk_upsert rows must have identical ordered columns")
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(
            f"{column}=excluded.{column}" for column in columns if column != "id"
        )
        conn = self._conn_write()
        with self._lock:
            conn.executemany(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                [[row[column] for column in columns] for row in normalized],
            )
            conn.commit()
        return len(normalized)

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
        """Delete a row and every embedding read-model row for its id."""
        conn = self._conn_write()
        with self._lock:
            cursor = conn.execute(f"DELETE FROM {table} WHERE id=?", (id,))
            conn.execute("DELETE FROM vec_embeddings WHERE entry_id = ?", (id,))
            try:
                conn.execute("DELETE FROM vec_embeddings_vec0 WHERE entry_id = ?", (id,))
            except sqlite3.Error:
                # sqlite-vec is optional and the virtual table may not exist.
                pass
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

    def rebuild_observation_trigrams(
        self,
        records: Iterable[tuple[str, str]],
        *,
        source_generation: str,
        source_id_hash: str,
        verify_source: Callable[[], bool] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Stage and atomically publish a complete observation trigram generation."""

        items = [(str(observation_id), str(text)) for observation_id, text in records]
        observed_id_hash = self.stable_id_hash(observation_id for observation_id, _ in items)
        if observed_id_hash != source_id_hash:
            raise ValueError("trigram source id hash does not match staged records")
        staging = f"observation_trigrams_staging_{uuid4().hex}"
        conn = self._conn_write()
        with self._lock:
            try:
                conn.execute(
                    f"""
                    CREATE TABLE {staging} (
                        ngram TEXT NOT NULL,
                        observation_id TEXT NOT NULL,
                        PRIMARY KEY (ngram, observation_id)
                    )
                    """
                )
                postings = [
                    (ngram, observation_id)
                    for observation_id, text in items
                    for ngram in sorted(_trigrams(text))
                ]
                conn.executemany(
                    f"INSERT OR IGNORE INTO {staging} (ngram, observation_id) VALUES (?, ?)",
                    postings,
                )
                staged_ids = {
                    str(row[0])
                    for row in conn.execute(
                        f"SELECT DISTINCT observation_id FROM {staging}"
                    ).fetchall()
                }
                expected_ids = {observation_id for observation_id, text in items if _trigrams(text)}
                if staged_ids != expected_ids:
                    raise sqlite3.IntegrityError("staged trigram membership mismatch")
                postings_hash = self.stable_trigram_postings_hash(postings)
                staged_identity = self._trigram_table_identity(conn, staging)
                if staged_identity != (len(postings), postings_hash):
                    raise sqlite3.IntegrityError("staged trigram content mismatch")
                conn.commit()
                if failpoint is not None:
                    failpoint("after_staging_validation")
                conn.execute("BEGIN IMMEDIATE")
                if verify_source is not None and not verify_source():
                    raise sqlite3.IntegrityError(
                        "observation source changed during trigram rebuild"
                    )
                if self._trigram_table_identity(conn, staging) != (
                    len(postings),
                    postings_hash,
                ):
                    raise sqlite3.IntegrityError(
                        "trigram staging content changed before publish"
                    )
                conn.execute("DELETE FROM observation_trigrams")
                if failpoint is not None:
                    failpoint("after_active_clear")
                conn.execute(
                    f"""
                    INSERT INTO observation_trigrams (ngram, observation_id)
                    SELECT ngram, observation_id FROM {staging}
                    """
                )
                if self._trigram_table_identity(
                    conn, "observation_trigrams"
                ) != (len(postings), postings_hash):
                    raise sqlite3.IntegrityError(
                        "published trigram content does not match staging"
                    )
                generation = self._insert_index_generation(
                    conn,
                    index_name="trigram:observations",
                    source_generation=source_generation,
                    row_count=len(items),
                    id_hash=source_id_hash,
                    metadata={
                        "indexed_observations": len(items),
                        "posting_count": len(postings),
                        "postings_hash": postings_hash,
                    },
                    activate=True,
                )
                if failpoint is not None:
                    failpoint("before_publish_commit")
                conn.execute(f"DROP TABLE {staging}")
                conn.commit()
                return {
                    "status": "published",
                    "indexed_observations": len(items),
                    "postings": len(postings),
                    "generation_id": generation["generation_id"],
                }
            except Exception:
                conn.rollback()
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {staging}")
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                raise

    @staticmethod
    def stable_trigram_postings_hash(
        postings: Iterable[tuple[str, str]],
    ) -> str:
        """Return a stable content identity for exact-index postings."""

        digest = hashlib.sha256()
        for ngram, observation_id in sorted(
            {(str(ngram), str(observation_id)) for ngram, observation_id in postings}
        ):
            for value in (ngram, observation_id):
                encoded = value.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
        return digest.hexdigest()

    def _trigram_table_identity(
        self,
        conn: sqlite3.Connection,
        table_name: str,
    ) -> tuple[int, str]:
        rows = conn.execute(
            f"SELECT ngram, observation_id FROM {table_name}"
        ).fetchall()
        postings = [(str(row[0]), str(row[1])) for row in rows]
        return len(postings), self.stable_trigram_postings_hash(postings)

    def observation_trigram_identity(self) -> dict[str, Any]:
        """Return exact posting count and content hash for health verification."""

        conn = self._conn_write()
        with self._lock:
            posting_count, postings_hash = self._trigram_table_identity(
                conn, "observation_trigrams"
            )
        return {"posting_count": posting_count, "postings_hash": postings_hash}

    def observation_ids_with_trigrams(self) -> set[str]:
        """Return observations that already have exact-search postings."""

        conn = self._conn_write()
        rows = conn.execute(
            "SELECT DISTINCT observation_id FROM observation_trigrams"
        ).fetchall()
        return {str(row[0]) for row in rows}

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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dream_runs_project
            ON dream_runs(project_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dream_runs_started_at
            ON dream_runs(started_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dream_runs_status
            ON dream_runs(status)
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
