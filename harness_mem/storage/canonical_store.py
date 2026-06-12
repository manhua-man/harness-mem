"""Canonical Storage v2 entity store helpers.

v4.0.1 turns the v4.0.0 migration artifact into a real, queryable canonical
SQLite shape while keeping the legacy JSON runtime path compatible.  The
canonical store is explicit: callers opt in through migration/export/health or
the experimental dual-write helper.  Generated indexes and sidecars remain
rebuildable; payload rows here are the durable truth projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from harness_mem.storage.store_v2_migration import (
    LegacyPayloadRow,
    StorageV2MigrationError,
    canonical_db_path,
    logical_checksum,
    scan_legacy_payloads,
)


CANONICAL_STORE_SCHEMA_VERSION = 2
CANONICAL_STORE_CONTRACT_VERSION = "canonical-store-v4.0.1"
DUAL_WRITE_ENV = "HARNESS_MEM_STORAGE_V2_DUAL_WRITE"

CANONICAL_ENTITY_TABLES: tuple[str, ...] = (
    "observations",
    "memory_entries",
    "rules",
    "skills",
    "relations",
    "candidates",
    "signals",
    "task_handoffs",
)

_COLLECTION_TO_TABLE: dict[str, str] = {
    "observations": "observations",
    "memory_entries": "memory_entries",
    "confirmed_rules": "rules",
    "skills": "skills",
    "relation_facts": "relations",
    "retrieval_signals": "signals",
    "task_handoffs": "task_handoffs",
}

_CANONICAL_COLUMNS = """
    row_key TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    project_id TEXT,
    corpus_id TEXT NOT NULL DEFAULT 'default',
    type TEXT NOT NULL,
    truth_status TEXT NOT NULL DEFAULT 'unknown',
    confidence REAL,
    created_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    tier TEXT NOT NULL DEFAULT 'hot',
    last_accessed_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    decay_score REAL NOT NULL DEFAULT 0.0,
    source_relpath TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    migrated_at TEXT NOT NULL
"""


@dataclass(frozen=True)
class CanonicalEntityRow:
    """One canonical entity row normalized for query, export, and checksum."""

    row_key: str
    table_name: str
    collection: str
    entity_id: str
    project_id: str | None
    corpus_id: str
    type: str
    truth_status: str
    confidence: float | None
    created_at: str | None
    valid_from: str | None
    valid_to: str | None
    tier: str
    last_accessed_at: str | None
    access_count: int
    decay_score: float
    source_relpath: str
    payload_json: str
    payload_sha256: str
    size_bytes: int
    migrated_at: str

    def to_legacy_payload_row(self) -> LegacyPayloadRow:
        return LegacyPayloadRow(
            row_key=self.row_key,
            collection=self.collection,
            entity_id=self.entity_id,
            project_name=self.project_id,
            source_relpath=self.source_relpath,
            payload_json=self.payload_json,
            payload_sha256=self.payload_sha256,
            size_bytes=self.size_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_key": self.row_key,
            "table_name": self.table_name,
            "collection": self.collection,
            "entity_id": self.entity_id,
            "project_id": self.project_id,
            "corpus_id": self.corpus_id,
            "type": self.type,
            "truth_status": self.truth_status,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "tier": self.tier,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
            "decay_score": self.decay_score,
            "source_relpath": self.source_relpath,
            "payload_sha256": self.payload_sha256,
            "size_bytes": self.size_bytes,
            "migrated_at": self.migrated_at,
        }


def canonical_store_path(data_dir: Path) -> Path:
    """Return the Storage v2 canonical SQLite path."""

    return canonical_db_path(data_dir)


def storage_v2_dual_write_enabled(environ: dict[str, str] | None = None) -> bool:
    """Return whether the experimental Storage v2 dual-write gate is on."""

    env = environ if environ is not None else os.environ
    return env.get(DUAL_WRITE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def initialize_canonical_schema(conn: sqlite3.Connection) -> None:
    """Create canonical entity tables and metadata indexes idempotently."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_store_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO canonical_store_meta(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(CANONICAL_STORE_SCHEMA_VERSION),),
    )
    conn.execute(
        """
        INSERT INTO canonical_store_meta(key, value)
        VALUES ('contract_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (CANONICAL_STORE_CONTRACT_VERSION,),
    )
    for table in CANONICAL_ENTITY_TABLES:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({_CANONICAL_COLUMNS})")
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_metadata
            ON {table}(project_id, corpus_id, type, truth_status, tier)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_validity
            ON {table}(valid_from, valid_to, created_at)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_payload_sha
            ON {table}(payload_sha256)
            """
        )


def build_canonical_store(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Import legacy JSON blobs into v4.0.1 canonical entity tables."""

    data_dir = Path(data_dir)
    db_path = canonical_path or canonical_store_path(data_dir)
    rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    if invalid:
        raise StorageV2MigrationError(
            f"Cannot build canonical store with invalid JSON files: {len(invalid)}"
        )

    before_checksum = logical_checksum(rows)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrated_at = _utc_now()
    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        _clear_project_rows(conn, project_name=project_name)
        for legacy in rows:
            payload = json.loads(legacy.payload_json)
            canonical = canonical_row_from_legacy(legacy, payload, migrated_at=migrated_at)
            _upsert_canonical_row(conn, canonical)
        conn.commit()
        canonical_rows = list_canonical_rows(conn, project_name=project_name)
    finally:
        conn.close()

    after_checksum = logical_checksum(
        [row.to_legacy_payload_row() for row in canonical_rows]
    )
    return {
        "contract_version": CANONICAL_STORE_CONTRACT_VERSION,
        "schema_version": CANONICAL_STORE_SCHEMA_VERSION,
        "project_name": project_name,
        "data_dir": str(data_dir),
        "canonical_db_path": str(db_path),
        "imported_row_count": len(rows),
        "canonical_row_count": len(canonical_rows),
        "before_checksum": before_checksum,
        "after_checksum": after_checksum,
        "checksum_match": before_checksum == after_checksum,
        "entity_tables": {
            table: sum(1 for row in canonical_rows if row.table_name == table)
            for table in CANONICAL_ENTITY_TABLES
        },
        "metadata_indexes": sorted(_expected_index_names()),
        "dual_write_gate": {
            "env": DUAL_WRITE_ENV,
            "enabled": storage_v2_dual_write_enabled(),
        },
    }


def read_compatible_payloads(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> list[CanonicalEntityRow]:
    """Read canonical rows if present, otherwise project-scoped legacy JSON."""

    db_path = canonical_path or canonical_store_path(data_dir)
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            initialize_canonical_schema(conn)
            rows = list_canonical_rows(conn, project_name=project_name)
            if rows:
                return rows
        finally:
            conn.close()

    legacy_rows, invalid = scan_legacy_payloads(Path(data_dir), project_name=project_name)
    if invalid:
        raise StorageV2MigrationError(
            f"Compatibility reader found invalid JSON files: {len(invalid)}"
        )
    migrated_at = _utc_now()
    return [
        canonical_row_from_legacy(
            row,
            json.loads(row.payload_json),
            migrated_at=migrated_at,
        )
        for row in legacy_rows
    ]


def canonical_row_from_legacy(
    row: LegacyPayloadRow,
    payload: dict[str, Any],
    *,
    migrated_at: str,
) -> CanonicalEntityRow:
    table_name = canonical_table_for_collection(row.collection)
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    lifecycle = payload.get("lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    tier = str(payload.get("tier") or lifecycle.get("tier") or "hot")
    if tier not in {"hot", "warm", "cold", "archive"}:
        tier = "hot"
    return CanonicalEntityRow(
        row_key=row.row_key,
        table_name=table_name,
        collection=row.collection,
        entity_id=row.entity_id,
        project_id=row.project_name,
        corpus_id=str(payload.get("corpus_id") or metadata.get("corpus_id") or "default"),
        type=_entity_type(row.collection, payload),
        truth_status=_truth_status(row.collection, payload),
        confidence=_float_or_none(payload.get("confidence")),
        created_at=_string_or_none(
            payload.get("created_at")
            or payload.get("confirmed_at")
            or payload.get("timestamp")
            or payload.get("recorded_at")
        ),
        valid_from=_string_or_none(payload.get("valid_from")),
        valid_to=_string_or_none(payload.get("valid_to")),
        tier=tier,
        last_accessed_at=_string_or_none(
            payload.get("last_accessed_at")
            or payload.get("last_surfaced_at")
            or lifecycle.get("last_accessed_at")
        ),
        access_count=int(
            payload.get("access_count")
            or payload.get("usage_count")
            or lifecycle.get("access_count")
            or 0
        ),
        decay_score=float(payload.get("decay_score") or lifecycle.get("decay_score") or 0.0),
        source_relpath=row.source_relpath,
        payload_json=row.payload_json,
        payload_sha256=row.payload_sha256,
        size_bytes=row.size_bytes,
        migrated_at=migrated_at,
    )


def canonical_table_for_collection(collection: str) -> str:
    if collection in _COLLECTION_TO_TABLE:
        return _COLLECTION_TO_TABLE[collection]
    if collection.endswith("_candidates") or "candidate" in collection:
        return "candidates"
    return "memory_entries"


def list_canonical_rows(
    conn: sqlite3.Connection,
    *,
    project_name: str | None = None,
    table_names: Iterable[str] = CANONICAL_ENTITY_TABLES,
) -> list[CanonicalEntityRow]:
    rows: list[CanonicalEntityRow] = []
    for table in table_names:
        if not _table_exists(conn, table):
            continue
        sql = f"""
            SELECT row_key, collection, entity_id, project_id, corpus_id, type,
                   truth_status, confidence, created_at, valid_from, valid_to,
                   tier, last_accessed_at, access_count, decay_score,
                   source_relpath, payload_json, payload_sha256, size_bytes,
                   migrated_at
            FROM {table}
        """
        params: tuple[Any, ...] = ()
        if project_name is not None:
            sql += " WHERE project_id = ?"
            params = (project_name,)
        sql += " ORDER BY collection, COALESCE(project_id, ''), entity_id"
        for row in conn.execute(sql, params).fetchall():
            rows.append(
                CanonicalEntityRow(
                    row_key=str(row[0]),
                    table_name=table,
                    collection=str(row[1]),
                    entity_id=str(row[2]),
                    project_id=row[3],
                    corpus_id=str(row[4]),
                    type=str(row[5]),
                    truth_status=str(row[6]),
                    confidence=_float_or_none(row[7]),
                    created_at=row[8],
                    valid_from=row[9],
                    valid_to=row[10],
                    tier=str(row[11]),
                    last_accessed_at=row[12],
                    access_count=int(row[13] or 0),
                    decay_score=float(row[14] or 0.0),
                    source_relpath=str(row[15]),
                    payload_json=str(row[16]),
                    payload_sha256=str(row[17]),
                    size_bytes=int(row[18] or 0),
                    migrated_at=str(row[19]),
                )
            )
    rows.sort(key=lambda item: (item.collection, item.project_id or "", item.entity_id))
    return rows


def export_json_snapshot(
    data_dir: Path,
    export_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    """Export canonical rows into human-readable v3-compatible JSON blobs."""

    data_dir = Path(data_dir)
    export_dir = Path(export_dir)
    rows = read_compatible_payloads(
        data_dir,
        project_name=project_name,
        canonical_path=canonical_path,
    )
    checksum = logical_checksum([row.to_legacy_payload_row() for row in rows])
    if apply:
        export_dir.mkdir(parents=True, exist_ok=True)
        for row in rows:
            out_path = export_dir / Path(row.source_relpath)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.loads(row.payload_json)
            out_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
        exported_rows, invalid = scan_legacy_payloads(export_dir, project_name=project_name)
        exported_checksum = logical_checksum(exported_rows)
        checksum_match = exported_checksum == checksum and not invalid
    else:
        exported_checksum = checksum
        checksum_match = True
        invalid = []
    return {
        "contract_version": CANONICAL_STORE_CONTRACT_VERSION,
        "schema_version": CANONICAL_STORE_SCHEMA_VERSION,
        "action": "export_json_snapshot",
        "dry_run": not apply,
        "project_name": project_name,
        "data_dir": str(data_dir),
        "canonical_db_path": str(canonical_path or canonical_store_path(data_dir)),
        "export_dir": str(export_dir),
        "would_export_json_file_count": len(rows),
        "exported_json_file_count": len(rows) if apply else 0,
        "source_checksum": checksum,
        "export_checksum": exported_checksum,
        "snapshot_checksum_match": checksum_match,
        "invalid_json_count": len(invalid),
        "claim_readiness": {
            "ready": checksum_match,
            "source": "canonical export logical checksum",
            "blocking": [] if checksum_match else ["snapshot_checksum_mismatch"],
        },
    }


def canonical_store_health(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
    wal_size_warning_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Return read-only Storage v2 health for doctor and MCP surfaces."""

    data_dir = Path(data_dir)
    db_path = canonical_path or canonical_store_path(data_dir)
    legacy_rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    legacy_checksum = logical_checksum(legacy_rows)
    if not db_path.exists():
        return {
            "status": "not_migrated",
            "project_name": project_name,
            "canonical_db_path": str(db_path),
            "legacy_json_file_count": len(legacy_rows),
            "canonical_row_count": 0,
            "invalid_json_count": len(invalid),
            "checksum_match": False,
            "partial_migration": bool(legacy_rows),
            "checksum_drift": False,
            "wal_size_bytes": 0,
            "wal_warning": False,
            "index_drift": [],
            "fix_command": "harness-mem maintenance migrate-store-v2 --apply",
        }

    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        canonical_rows = list_canonical_rows(conn, project_name=project_name)
        canonical_checksum = logical_checksum(
            [row.to_legacy_payload_row() for row in canonical_rows]
        )
        missing_indexes = _missing_indexes(conn)
    finally:
        conn.close()

    wal_path = Path(f"{db_path}-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    partial = len(canonical_rows) < len(legacy_rows)
    drift = bool(legacy_rows) and canonical_checksum != legacy_checksum
    status = "healthy"
    if invalid:
        status = "invalid_legacy_json"
    elif partial:
        status = "partial_migration"
    elif drift:
        status = "checksum_drift"
    elif missing_indexes:
        status = "index_drift"
    return {
        "status": status,
        "project_name": project_name,
        "canonical_db_path": str(db_path),
        "legacy_json_file_count": len(legacy_rows),
        "canonical_row_count": len(canonical_rows),
        "invalid_json_count": len(invalid),
        "legacy_checksum": legacy_checksum,
        "canonical_checksum": canonical_checksum,
        "checksum_match": canonical_checksum == legacy_checksum,
        "partial_migration": partial,
        "checksum_drift": drift,
        "wal_size_bytes": wal_size,
        "wal_warning": wal_size > wal_size_warning_bytes,
        "index_drift": missing_indexes,
        "entity_tables": {
            table: sum(1 for row in canonical_rows if row.table_name == table)
            for table in CANONICAL_ENTITY_TABLES
        },
        "dual_write_gate": {
            "env": DUAL_WRITE_ENV,
            "enabled": storage_v2_dual_write_enabled(),
        },
        "fix_command": (
            "harness-mem maintenance migrate-store-v2 --apply"
            if status != "healthy"
            else ""
        ),
    }


def mirror_payload_to_canonical(
    data_dir: Path,
    *,
    collection: str,
    source_relpath: str,
    payload: dict[str, Any],
    require_gate: bool = True,
) -> dict[str, Any]:
    """Mirror one legacy JSON payload to canonical SQLite when gate permits."""

    if require_gate and not storage_v2_dual_write_enabled():
        return {
            "mirrored": False,
            "reason": "dual_write_gate_off",
            "env": DUAL_WRITE_ENV,
        }
    data_dir = Path(data_dir)
    payload_json = _stable_json(payload)
    payload_sha = _sha256_text(payload_json)
    project = _payload_project_id(payload)
    entity_id = str(payload.get("id") or Path(source_relpath).stem)
    legacy = LegacyPayloadRow(
        row_key=_row_key(collection, project, entity_id),
        collection=collection,
        entity_id=entity_id,
        project_name=project,
        source_relpath=source_relpath,
        payload_json=payload_json,
        payload_sha256=payload_sha,
        size_bytes=len(payload_json.encode("utf-8")),
    )
    canonical = canonical_row_from_legacy(
        legacy,
        payload,
        migrated_at=_utc_now(),
    )
    db_path = canonical_store_path(data_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        _upsert_canonical_row(conn, canonical)
        conn.commit()
    finally:
        conn.close()
    return {
        "mirrored": True,
        "canonical_db_path": str(db_path),
        "table_name": canonical.table_name,
        "row_key": canonical.row_key,
        "payload_sha256": canonical.payload_sha256,
    }


def _upsert_canonical_row(conn: sqlite3.Connection, row: CanonicalEntityRow) -> None:
    conn.execute(
        f"""
        INSERT INTO {row.table_name} (
            row_key, collection, entity_id, project_id, corpus_id, type,
            truth_status, confidence, created_at, valid_from, valid_to,
            tier, last_accessed_at, access_count, decay_score, source_relpath,
            payload_json, payload_sha256, size_bytes, migrated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(row_key) DO UPDATE SET
            collection=excluded.collection,
            entity_id=excluded.entity_id,
            project_id=excluded.project_id,
            corpus_id=excluded.corpus_id,
            type=excluded.type,
            truth_status=excluded.truth_status,
            confidence=excluded.confidence,
            created_at=excluded.created_at,
            valid_from=excluded.valid_from,
            valid_to=excluded.valid_to,
            tier=excluded.tier,
            last_accessed_at=excluded.last_accessed_at,
            access_count=excluded.access_count,
            decay_score=excluded.decay_score,
            source_relpath=excluded.source_relpath,
            payload_json=excluded.payload_json,
            payload_sha256=excluded.payload_sha256,
            size_bytes=excluded.size_bytes,
            migrated_at=excluded.migrated_at
        """,
        (
            row.row_key,
            row.collection,
            row.entity_id,
            row.project_id,
            row.corpus_id,
            row.type,
            row.truth_status,
            row.confidence,
            row.created_at,
            row.valid_from,
            row.valid_to,
            row.tier,
            row.last_accessed_at,
            row.access_count,
            row.decay_score,
            row.source_relpath,
            row.payload_json,
            row.payload_sha256,
            row.size_bytes,
            row.migrated_at,
        ),
    )


def _clear_project_rows(conn: sqlite3.Connection, *, project_name: str | None) -> None:
    for table in CANONICAL_ENTITY_TABLES:
        if not _table_exists(conn, table):
            continue
        if project_name is None:
            conn.execute(f"DELETE FROM {table}")
        else:
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_name,))


def _missing_indexes(conn: sqlite3.Connection) -> list[str]:
    existing: set[str] = set()
    for table in CANONICAL_ENTITY_TABLES:
        if not _table_exists(conn, table):
            continue
        for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
            existing.add(str(row[1]))
    return sorted(_expected_index_names() - existing)


def _expected_index_names() -> set[str]:
    names: set[str] = set()
    for table in CANONICAL_ENTITY_TABLES:
        names.add(f"idx_{table}_metadata")
        names.add(f"idx_{table}_validity")
        names.add(f"idx_{table}_payload_sha")
    return names


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _entity_type(collection: str, payload: dict[str, Any]) -> str:
    if collection == "memory_entries":
        return str(payload.get("memory_type") or payload.get("category") or "memory_entry")
    if collection == "observations":
        return str(payload.get("content_type") or "observation")
    if collection == "confirmed_rules":
        return "confirmed_rule"
    if collection == "relation_facts":
        return str(payload.get("relation_type") or "relation_fact")
    if collection == "skills":
        return "skill"
    if collection == "retrieval_signals":
        return str(payload.get("signal_type") or "retrieval_signal")
    if "candidate" in collection:
        return collection
    return collection


def _truth_status(collection: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    valid_to = payload.get("valid_to")
    if valid_to:
        return "historical"
    if status in {"pending", "accepted", "rejected", "active"}:
        if status == "accepted" or status == "active":
            return "confirmed_current"
        return status
    if collection in {"memory_entries", "confirmed_rules", "relation_facts", "skills"}:
        return "confirmed_current"
    if "candidate" in collection:
        return "pending"
    return "raw"


def _payload_project_id(payload: dict[str, Any]) -> str | None:
    project = payload.get("project_name")
    if isinstance(project, str) and project:
        return project
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        project = metadata.get("project_name")
        if isinstance(project, str) and project:
            return project
    return None


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row_key(collection: str, project_name: str | None, entity_id: str) -> str:
    return _sha256_text(f"{collection}\0{project_name or ''}\0{entity_id}")


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    return text or None


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
