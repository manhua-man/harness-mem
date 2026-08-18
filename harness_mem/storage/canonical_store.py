"""Canonical Storage v2 entity store helpers.

Canonical SQLite is the default runtime truth store. Legacy JSON remains a
supported fallback through the 0.9.x line, but existing data changes authority
only through explicit preview/apply migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable
from uuid import uuid4

from harness_mem.storage.store_v2_migration import (
    LegacyPayloadRow,
    StorageV2MigrationError,
    canonical_db_path,
    apply_store_v2_migration,
    logical_checksum,
    scan_legacy_payloads,
)
from harness_mem.version import legacy_storage_support_policy


CANONICAL_STORE_SCHEMA_VERSION = 6
CANONICAL_STORE_CONTRACT_VERSION = "canonical-store-v6.0.0"
DUAL_WRITE_ENV = "HARNESS_MEM_STORAGE_V2_DUAL_WRITE"
RUNTIME_STATE_FILE_NAME = "runtime_state.json"
MIGRATION_RECEIPT_DIR_NAME = "migration_receipts"
MIGRATION_RECEIPT_SCHEMA_VERSION = 1
RUNTIME_STATES: tuple[str, ...] = (
    "canonical",
    "bootstrapped_from_legacy",
    "degraded_fallback",
)

CANONICAL_ENTITY_TABLES: tuple[str, ...] = (
    "observations",
    "memory_entries",
    "knowledge_entries",
    "knowledge_sources",
    "knowledge_versions",
    "knowledge_mutations",
    "rules",
    "skills",
    "relations",
    "candidates",
    "signals",
    "task_handoffs",
    "metabolism_runs",
    "dream_runs",
)

_COLLECTION_TO_TABLE: dict[str, str] = {
    "observations": "observations",
    "memory_entries": "memory_entries",
    "knowledge_entries": "knowledge_entries",
    "knowledge_sources": "knowledge_sources",
    "knowledge_versions": "knowledge_versions",
    "knowledge_mutations": "knowledge_mutations",
    "confirmed_rules": "rules",
    "skills": "skills",
    "relation_facts": "relations",
    "retrieval_signals": "signals",
    "task_handoffs": "task_handoffs",
    "rule_candidates": "candidates",
    "supersede_candidates": "candidates",
    "merge_suggestion_candidates": "candidates",
    "stale_truth_suggestion_candidates": "candidates",
    "procedural_candidates": "candidates",
    "metabolism_runs": "metabolism_runs",
    "dream_runs": "dream_runs",
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


@dataclass(frozen=True)
class StorageRuntimeState:
    """Persisted runtime-truth state for doctor/status/maintenance surfaces."""

    mode: str
    canonical_db_path: str
    updated_at: str
    legacy_payload_count: int = 0
    error: str | None = None
    recovery_hint: str | None = None
    default_storage_changed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "canonical_db_path": self.canonical_db_path,
            "updated_at": self.updated_at,
            "legacy_payload_count": self.legacy_payload_count,
            "error": self.error,
            "recovery_hint": self.recovery_hint,
            "default_storage_changed": self.default_storage_changed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageRuntimeState":
        return cls(
            mode=str(payload.get("mode") or "canonical"),
            canonical_db_path=str(payload.get("canonical_db_path") or ""),
            updated_at=str(payload.get("updated_at") or _utc_now()),
            legacy_payload_count=int(payload.get("legacy_payload_count") or 0),
            error=_string_or_none(payload.get("error")),
            recovery_hint=_string_or_none(payload.get("recovery_hint")),
            default_storage_changed=bool(payload.get("default_storage_changed", True)),
        )


class CanonicalTransactionError(RuntimeError):
    """Base error for an in-place canonical SQLite mutation transaction."""


class CanonicalTransactionPreconditionError(CanonicalTransactionError):
    """A mutation's expected payload SHA did not match current truth."""


class CanonicalTransactionIdempotencyError(CanonicalTransactionError):
    """An idempotency key was reused for a different mutation request."""


class CanonicalStoreRuntime:
    """Thin runtime CRUD helper over canonical SQLite payload rows."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.db_path = canonical_store_path(self.data_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA secure_delete=ON")
        initialize_canonical_schema(self._conn)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def flush_sensitive_deletes(self) -> None:
        """Commit secure deletes and truncate the canonical-store WAL."""

        with self._lock:
            self._conn.commit()
            row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0] or 0) != 0:
            raise RuntimeError("canonical store WAL checkpoint remained busy")

    def payload_exists(self, collection: str, entity_id: str) -> bool:
        return self.get_row(collection, entity_id) is not None

    def get_payload_json(self, collection: str, entity_id: str) -> str | None:
        row = self.get_row(collection, entity_id)
        return row.payload_json if row else None

    def get_payload(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        payload_json = self.get_payload_json(collection, entity_id)
        if payload_json is None:
            return None
        return json.loads(payload_json)

    def get_row(self, collection: str, entity_id: str) -> CanonicalEntityRow | None:
        with self._lock:
            table_name = canonical_table_for_collection(collection)
            if not _table_exists(self._conn, table_name):
                return None
            row = self._conn.execute(
                f"""
                SELECT row_key, collection, entity_id, project_id, corpus_id, type,
                       truth_status, confidence, created_at, valid_from, valid_to,
                       tier, last_accessed_at, access_count, decay_score,
                       source_relpath, payload_json, payload_sha256, size_bytes,
                       migrated_at
                FROM {table_name}
                WHERE collection = ? AND entity_id = ?
                ORDER BY COALESCE(project_id, ''), entity_id
                LIMIT 1
                """,
                (collection, entity_id),
            ).fetchone()
        if row is None:
            return None
        return CanonicalEntityRow(
            row_key=str(row[0]),
            table_name=table_name,
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

    def list_rows(
        self,
        collection: str,
        *,
        project_name: str | None = None,
    ) -> list[CanonicalEntityRow]:
        table_name = canonical_table_for_collection(collection)
        with self._lock:
            rows = list_canonical_rows(
                self._conn,
                project_name=project_name,
                table_names=(table_name,),
            )
        return [row for row in rows if row.collection == collection]

    def list_payloads(
        self,
        collection: str,
        *,
        project_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            json.loads(row.payload_json)
            for row in self.list_rows(collection, project_name=project_name)
        ]

    def count(
        self,
        collection: str,
        *,
        project_name: str | None = None,
    ) -> int:
        table_name = canonical_table_for_collection(collection)
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE collection = ?"
        params: list[Any] = [collection]
        if project_name is not None:
            sql += " AND project_id = ?"
            params.append(project_name)
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return int(row[0] or 0) if row else 0

    def upsert_payload(
        self,
        collection: str,
        entity_id: str,
        payload: dict[str, Any],
        *,
        source_relpath: str | None = None,
    ) -> CanonicalEntityRow:
        payload_json = _stable_json(payload)
        payload_sha = _sha256_text(payload_json)
        project_name = _payload_project_id(payload)
        legacy = LegacyPayloadRow(
            row_key=_row_key(collection, project_name, entity_id),
            collection=collection,
            entity_id=entity_id,
            project_name=project_name,
            source_relpath=source_relpath
            or _default_source_relpath(collection, entity_id),
            payload_json=payload_json,
            payload_sha256=payload_sha,
            size_bytes=len(payload_json.encode("utf-8")),
        )
        canonical = canonical_row_from_legacy(
            legacy,
            payload,
            migrated_at=_utc_now(),
        )
        with self._lock:
            with self._conn:
                _upsert_canonical_row(self._conn, canonical)
            stored = self.get_row(collection, entity_id)
        if stored is None:
            raise StorageV2MigrationError(
                f"Canonical upsert failed for {collection}:{entity_id}"
            )
        return stored

    def delete_payload(self, collection: str, entity_id: str) -> bool:
        table_name = canonical_table_for_collection(collection)
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    f"DELETE FROM {table_name} WHERE collection = ? AND entity_id = ?",
                    (collection, entity_id),
                )
        return int(cursor.rowcount or 0) > 0

    def apply_payload_transaction(
        self,
        *,
        idempotency_key: str,
        mutations: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Atomically apply canonical payload mutations on the existing DB inode.

        Each mutation has ``operation`` (``upsert`` or ``delete``), ``collection``,
        and ``entity_id``. Upserts also require ``payload`` and may provide
        ``source_relpath``. If ``expected_sha256`` is present, its value must
        match current canonical truth; ``None`` explicitly requires absence.

        The idempotency record commits in the same SQLite transaction as every
        payload mutation. Replaying the same key and request is a no-op; reusing
        the key for different work fails closed.
        """

        key = str(idempotency_key).strip()
        if not key:
            raise ValueError("idempotency_key must be non-empty")
        normalized = [_normalize_payload_mutation(item) for item in mutations]
        if not normalized:
            raise ValueError("mutations must contain at least one operation")
        targets = [
            (str(item["collection"]), str(item["entity_id"]))
            for item in normalized
        ]
        if len(set(targets)) != len(targets):
            raise ValueError("one transaction cannot mutate the same target twice")
        request_sha256 = _sha256_text(_stable_json_value(normalized))

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                replay = self._conn.execute(
                    """
                    SELECT request_sha256, result_json
                    FROM canonical_transaction_records
                    WHERE idempotency_key = ?
                    """,
                    (key,),
                ).fetchone()
                if replay is not None:
                    if str(replay[0]) != request_sha256:
                        raise CanonicalTransactionIdempotencyError(
                            "idempotency key was already committed for a different request"
                        )
                    replay_result = json.loads(str(replay[1]))
                    self._conn.rollback()
                    replay_result["replayed"] = True
                    return replay_result

                for item in normalized:
                    if "expected_sha256" not in item:
                        continue
                    current = self.get_row(
                        str(item["collection"]), str(item["entity_id"])
                    )
                    actual = current.payload_sha256 if current is not None else None
                    expected = item["expected_sha256"]
                    if actual != expected:
                        raise CanonicalTransactionPreconditionError(
                            f"payload SHA precondition failed for "
                            f"{item['collection']}:{item['entity_id']}: "
                            f"expected {expected!r}, found {actual!r}"
                        )

                applied: list[dict[str, Any]] = []
                for item in normalized:
                    collection = str(item["collection"])
                    entity_id = str(item["entity_id"])
                    table_name = canonical_table_for_collection(collection)
                    if item["operation"] == "delete":
                        cursor = self._conn.execute(
                            f"DELETE FROM {table_name} "
                            "WHERE collection = ? AND entity_id = ?",
                            (collection, entity_id),
                        )
                        applied.append(
                            {
                                "operation": "delete",
                                "collection": collection,
                                "entity_id": entity_id,
                                "deleted": int(cursor.rowcount or 0) > 0,
                            }
                        )
                        continue

                    payload = dict(item["payload"])
                    payload_json = _stable_json(payload)
                    project_name = _payload_project_id(payload)
                    legacy = LegacyPayloadRow(
                        row_key=_row_key(collection, project_name, entity_id),
                        collection=collection,
                        entity_id=entity_id,
                        project_name=project_name,
                        source_relpath=str(
                            item.get("source_relpath")
                            or _default_source_relpath(collection, entity_id)
                        ),
                        payload_json=payload_json,
                        payload_sha256=_sha256_text(payload_json),
                        size_bytes=len(payload_json.encode("utf-8")),
                    )
                    row = canonical_row_from_legacy(
                        legacy, payload, migrated_at=_utc_now()
                    )
                    _upsert_canonical_row(self._conn, row)
                    applied.append(
                        {
                            "operation": "upsert",
                            "collection": collection,
                            "entity_id": entity_id,
                            "payload_sha256": row.payload_sha256,
                        }
                    )

                result: dict[str, Any] = {
                    "idempotency_key": key,
                    "request_sha256": request_sha256,
                    "mutation_count": len(applied),
                    "mutations": applied,
                    "replayed": False,
                }
                committed_at = _utc_now()
                self._conn.execute(
                    """
                    INSERT INTO canonical_transaction_records (
                        idempotency_key, request_sha256, result_json, committed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (key, request_sha256, _stable_json_value(result), committed_at),
                )
                self._conn.commit()
                return result
            except Exception:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise


def count_managed_backup_observations(
    data_dir: Path,
    *,
    project_name: str,
    transcript_source_id: str,
) -> int:
    """Count raw observations for one source in managed migration backups.

    Processed-source cleanup cannot mutate a rollback snapshot without also
    changing its integrity contract.  Callers use this read-only probe to fail
    closed before deleting the native source.
    """

    backup_dir = canonical_store_path(Path(data_dir)).parent / "backups"
    matches = 0
    for backup in sorted(backup_dir.glob("canonical-*.sqlite")):
        connection = sqlite3.connect(
            f"file:{backup.resolve().as_posix()}?mode=ro",
            uri=True,
        )
        try:
            for table in CANONICAL_ENTITY_TABLES:
                if not _table_exists(connection, table):
                    continue
                quoted_table = _quote_sqlite_identifier(table)
                rows = connection.execute(
                    f"SELECT payload_json FROM {quoted_table} "
                    "WHERE collection = 'observations' AND project_id = ?",
                    (project_name,),
                ).fetchall()
                for row in rows:
                    payload = json.loads(str(row[0]))
                    metadata = payload.get("metadata")
                    if (
                        isinstance(metadata, dict)
                        and str(metadata.get("transcript_source_id") or "")
                        == transcript_source_id
                    ):
                        matches += 1
        finally:
            connection.close()
    return matches


def canonical_store_path(data_dir: Path) -> Path:
    """Return the Storage v2 canonical SQLite path."""

    return canonical_db_path(data_dir)


def runtime_state_path(data_dir: Path) -> Path:
    return Path(data_dir) / "store_v2" / RUNTIME_STATE_FILE_NAME


def migration_receipt_path(data_dir: Path, migration_id: str) -> Path:
    """Return the content-free receipt path for one explicit migration."""

    return (
        Path(data_dir)
        / "store_v2"
        / MIGRATION_RECEIPT_DIR_NAME
        / f"{migration_id}.json"
    )


def _write_migration_receipt(data_dir: Path, receipt: dict[str, Any]) -> Path:
    """Atomically persist a content-free migration receipt."""

    migration_id = str(receipt.get("migration_id") or "")
    if not migration_id:
        raise StorageV2MigrationError("migration receipt requires migration_id")
    path = migration_receipt_path(data_dir, migration_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def read_runtime_state(data_dir: Path) -> StorageRuntimeState | None:
    path = runtime_state_path(Path(data_dir))
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return StorageRuntimeState.from_dict(payload)


def write_runtime_state(
    data_dir: Path,
    state: StorageRuntimeState,
) -> StorageRuntimeState:
    path = runtime_state_path(Path(data_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return state


def migrate_canonical_store_atomically(
    data_dir: Path,
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Build and validate a global staging DB, then activate it with rollback.

    ``project_name`` is retained as request/reporting context only. Runtime
    authority is global for one ``data_dir``, so an activation must cover every
    project before the runtime state can safely point at canonical SQLite.
    """

    data_dir = Path(data_dir)
    target = canonical_store_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    migration_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid4().hex[:8]}"
    )
    staging = target.with_name(f".{target.name}.{uuid4().hex}.staging")
    backup_dir = target.parent / "backups"
    backup = backup_dir / f"canonical-{migration_id}.sqlite"
    runtime_path = runtime_state_path(data_dir)
    runtime_before = runtime_path.read_bytes() if runtime_path.exists() else None
    runtime_before_state = read_runtime_state(data_dir)
    had_target = target.exists()
    live_fingerprint_before = _sqlite_logical_fingerprint(target)
    legacy_rows, invalid_legacy = scan_legacy_payloads(data_dir)
    receipt: dict[str, Any] = {
        "schema_version": MIGRATION_RECEIPT_SCHEMA_VERSION,
        "kind": "storage_v2_migration",
        "migration_id": migration_id,
        "status": "in_progress",
        "started_at": _utc_now(),
        "completed_at": None,
        "requested_project_name": project_name,
        "activation_scope": "all_projects",
        "legacy_row_count": len(legacy_rows),
        "legacy_invalid_count": len(invalid_legacy),
        "legacy_logical_checksum": logical_checksum(legacy_rows),
        "canonical_row_count": None,
        "canonical_logical_fingerprint": live_fingerprint_before,
        "checksum_relation": None,
        "sqlite_integrity": None,
        "backup_created": False,
        "backup_path_sha256": None,
        "runtime_state_before": (
            runtime_before_state.mode if runtime_before_state is not None else None
        ),
        "runtime_state_after": None,
        "failure_stage": None,
        "error_code": None,
    }
    # Receipt-first: if this write fails, no snapshot, staging DB, activation,
    # or runtime-state mutation has started.
    receipt_path = _write_migration_receipt(data_dir, receipt)

    activated = False
    activated_fingerprint: str | None = None
    failure_stage = "snapshot_live_store"
    try:
        if had_target:
            backup_dir.mkdir(parents=True, exist_ok=True)
            _backup_sqlite(target, backup)
            _backup_sqlite(target, staging)
            receipt["backup_created"] = True
            receipt["backup_path_sha256"] = hashlib.sha256(
                str(backup).encode("utf-8")
            ).hexdigest()
            _write_migration_receipt(data_dir, receipt)

        failure_stage = "build_staging"
        payload_result = apply_store_v2_migration(
            data_dir,
            project_name=None,
            canonical_path=staging,
        )
        canonical_result = build_canonical_store(
            data_dir,
            project_name=None,
            canonical_path=staging,
        )
        failure_stage = "validate_staging"
        integrity = _sqlite_integrity_check(staging)
        relation = canonical_checksum_relation(
            data_dir,
            project_name=None,
            canonical_path=staging,
        )
        if not payload_result["checksum_match"]:
            raise StorageV2MigrationError("staging payload checksum mismatch")
        if not canonical_result["checksum_match"]:
            raise StorageV2MigrationError("staging canonical coverage is incomplete")
        if integrity != "ok":
            raise StorageV2MigrationError(
                f"staging SQLite integrity check failed: {integrity}"
            )
        if relation["relation"] in {
            "invalid_legacy",
            "legacy_missing_in_canonical",
            "content_conflict",
        }:
            raise StorageV2MigrationError(
                f"staging checksum relation is unsafe: {relation['relation']}"
            )
        activated_fingerprint = _sqlite_logical_fingerprint(staging)
        if activated_fingerprint is None:
            raise StorageV2MigrationError("validated staging SQLite disappeared")

        failure_stage = "compare_before_swap"
        live_fingerprint_before_activation = _sqlite_logical_fingerprint(target)
        if live_fingerprint_before_activation != live_fingerprint_before:
            raise StorageV2MigrationError(
                "Canonical SQLite changed while migration staging was built; "
                "activation aborted to preserve concurrent writes. Retry the migration."
            )

        failure_stage = "activate_staging"
        if had_target:
            _activate_staging_transactionally(
                staging,
                target,
                expected_live_fingerprint=live_fingerprint_before,
            )
        else:
            # A hard link is an atomic create-if-absent operation. Unlike
            # ``os.replace``, it can never overwrite a canonical DB created by
            # a concurrent runtime after staging began.
            try:
                os.link(staging, target)
            except FileExistsError as exc:
                raise StorageV2MigrationError(
                    "Canonical SQLite appeared while migration staging was built; "
                    "activation aborted to preserve concurrent writes. Retry the migration."
                ) from exc
        activated = True
        state = StorageRuntimeState(
            mode="canonical",
            canonical_db_path=str(target),
            updated_at=_utc_now(),
            legacy_payload_count=int(payload_result["migrated_row_count"]),
            recovery_hint=(
                f"Pre-migration SQLite snapshot: {backup}"
                if had_target
                else "Canonical SQLite was created from validated staging; no prior DB existed."
            ),
        )
        failure_stage = "activate_runtime_state"
        write_runtime_state(data_dir, state)
        result = {
            "migration_id": migration_id,
            "requested_project_name": project_name,
            "activation_scope": "all_projects",
            "canonical_db_path": str(target),
            "staging_db_path": str(staging),
            "backup_db_path": str(backup) if had_target else None,
            "backup_created": had_target and backup.exists(),
            "activated_atomically": True,
            "runtime_state_updated_last": True,
            "live_store_unchanged_before_activation": True,
            "sqlite_integrity": integrity,
            "checksum_relation": relation,
            "payload_migration": payload_result,
            "canonical_store": canonical_result,
            "receipt": {
                "id": migration_id,
                "status": "succeeded",
                "path": str(receipt_path),
            },
        }
        failure_stage = "finalize_receipt"
        receipt.update(
            {
                "status": "succeeded",
                "completed_at": _utc_now(),
                "canonical_row_count": int(
                    canonical_result.get("canonical_row_count") or 0
                ),
                "canonical_logical_fingerprint": _sqlite_logical_fingerprint(target),
                "checksum_relation": relation.get("relation"),
                "sqlite_integrity": integrity,
                "runtime_state_after": "canonical",
                "failure_stage": None,
                "error_code": None,
            }
        )
        _write_migration_receipt(data_dir, receipt)
        return result
    except Exception as exc:
        rollback_status = "not_required"
        rollback_quarantine_path_sha256: str | None = None
        if activated:
            if had_target and backup.exists():
                try:
                    _activate_staging_transactionally(
                        backup,
                        target,
                        expected_live_fingerprint=activated_fingerprint,
                    )
                    rollback_status = "restored"
                except StorageV2MigrationError:
                    # A writer committed after activation. Never replace its
                    # live rows with the pre-migration snapshot.
                    rollback_status = "aborted_concurrent_write"
            elif target.exists():
                current_fingerprint = _sqlite_logical_fingerprint(target)
                if current_fingerprint != activated_fingerprint:
                    rollback_status = "aborted_concurrent_write"
                else:
                    quarantine = (
                        target.parent
                        / "failed_activations"
                        / f"canonical-{migration_id}.sqlite"
                    )
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.replace(target, quarantine)
                    except OSError:
                        rollback_status = "aborted_concurrent_write"
                    else:
                        rollback_status = "quarantined_new_store"
                        rollback_quarantine_path_sha256 = hashlib.sha256(
                            str(quarantine).encode("utf-8")
                        ).hexdigest()
        if rollback_status != "aborted_concurrent_write":
            if runtime_before is not None:
                runtime_path.parent.mkdir(parents=True, exist_ok=True)
                runtime_path.write_bytes(runtime_before)
            elif runtime_path.exists():
                runtime_path.unlink()
        runtime_after_failure = read_runtime_state(data_dir)
        receipt.update(
            {
                "status": "failed",
                "completed_at": _utc_now(),
                "runtime_state_after": (
                    runtime_after_failure.mode
                    if runtime_after_failure is not None
                    else None
                ),
                "failure_stage": failure_stage,
                "error_code": type(exc).__name__,
                "rollback_status": rollback_status,
                "rollback_quarantine_path_sha256": (rollback_quarantine_path_sha256),
            }
        )
        try:
            _write_migration_receipt(data_dir, receipt)
        except Exception:
            # The initial in_progress receipt remains durable and cannot be
            # mistaken for a successful migration.
            pass
        raise
    finally:
        if staging.exists():
            staging.unlink()


def canonical_checksum_relation(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Explain legacy/canonical checksum differences without treating additions as drift."""

    legacy_rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    if invalid:
        return {
            "relation": "invalid_legacy",
            "explanation": "Legacy JSON contains invalid payloads and cannot be compared safely.",
            "invalid_legacy_count": len(invalid),
            "legacy_only_count": 0,
            "canonical_only_count": 0,
            "changed_in_canonical_count": 0,
        }
    db_path = canonical_path or canonical_store_path(data_dir)
    if not db_path.exists():
        return {
            "relation": "legacy_missing_in_canonical" if legacy_rows else "exact_match",
            "explanation": "Canonical SQLite is absent."
            if legacy_rows
            else "Both stores are empty.",
            "invalid_legacy_count": 0,
            "legacy_only_count": len(legacy_rows),
            "canonical_only_count": 0,
            "changed_in_canonical_count": 0,
        }
    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        canonical_rows = list_canonical_rows(conn, project_name=project_name)
    finally:
        conn.close()
    legacy = {
        (row.collection, row.project_name or "", row.entity_id): row.payload_sha256
        for row in legacy_rows
    }
    canonical = {
        (row.collection, row.project_id or "", row.entity_id): row.payload_sha256
        for row in canonical_rows
    }
    legacy_only = sorted(set(legacy) - set(canonical))
    canonical_only = sorted(set(canonical) - set(legacy))
    changed = sorted(
        key for key in set(legacy) & set(canonical) if legacy[key] != canonical[key]
    )
    runtime = read_runtime_state(data_dir)
    if legacy_only:
        relation = "legacy_missing_in_canonical"
        explanation = (
            "Canonical SQLite is missing legacy identities; migration is incomplete."
        )
    elif changed and (runtime is None or runtime.mode != "canonical"):
        relation = "content_conflict"
        explanation = "Legacy and canonical payloads disagree while canonical authority is not established."
    elif canonical_only or changed:
        relation = "canonical_superset_expected"
        explanation = (
            "Canonical SQLite contains additional or newer authoritative data; "
            "legacy JSON is a lagging compatibility snapshot."
        )
    else:
        relation = "exact_match"
        explanation = "Canonical and legacy logical payloads match exactly."
    return {
        "relation": relation,
        "explanation": explanation,
        "invalid_legacy_count": 0,
        "legacy_only_count": len(legacy_only),
        "canonical_only_count": len(canonical_only),
        "changed_in_canonical_count": len(changed),
        "legacy_only_sample": [list(key) for key in legacy_only[:5]],
        "canonical_only_sample": [list(key) for key in canonical_only[:5]],
        "changed_in_canonical_sample": [list(key) for key in changed[:5]],
    }


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    source_conn = sqlite3.connect(source)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        source_conn.backup(destination_conn)
        destination_conn.commit()
    finally:
        destination_conn.close()
        source_conn.close()


def _sqlite_logical_fingerprint(path: Path) -> str | None:
    """Hash one consistent SQLite snapshot, independent of page layout.

    SQLite backup files can differ at the byte level even when their logical
    contents match. This fingerprint covers schema objects and every user-table
    row, allowing migration activation to fail closed when the live database
    changes after staging starts.
    """

    if not path.exists():
        return None

    conn = sqlite3.connect(path)
    try:
        conn.execute("BEGIN")
        fingerprint = _sqlite_connection_logical_fingerprint(conn)
        conn.rollback()
    finally:
        conn.close()
    return fingerprint


def _sqlite_connection_logical_fingerprint(
    conn: sqlite3.Connection,
    *,
    schema: str = "main",
) -> str:
    """Hash one connection snapshot without opening a second race window."""

    quoted_schema = _quote_sqlite_identifier(schema)
    digest = hashlib.sha256()
    schema_rows = conn.execute(
        f"""
        SELECT type, name, tbl_name, COALESCE(sql, '')
        FROM {quoted_schema}.sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    digest.update(
        json.dumps(schema_rows, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    for object_type, table_name, _owner, _sql in schema_rows:
        if object_type != "table":
            continue
        quoted_table = _quote_sqlite_identifier(str(table_name))
        rows = conn.execute(f"SELECT * FROM {quoted_schema}.{quoted_table}").fetchall()
        encoded_rows = sorted(_encode_sqlite_fingerprint_row(row) for row in rows)
        digest.update(str(table_name).encode("utf-8"))
        digest.update(b"\0")
        for encoded_row in encoded_rows:
            digest.update(encoded_row)
            digest.update(b"\n")
    return digest.hexdigest()


def _activate_staging_transactionally(
    staging: Path,
    target: Path,
    *,
    expected_live_fingerprint: str | None,
) -> None:
    """Copy validated staging state into the live SQLite file atomically.

    Keeping the live inode avoids stranding already-open runtime connections
    on an unlinked database. ``BEGIN IMMEDIATE`` closes the fingerprint-to-
    commit write window: other writers either commit before the fingerprint
    check (and cause a fail-closed abort) or wait until activation completes.
    """

    conn = sqlite3.connect(target, timeout=30.0)
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS staged", (str(staging),))
        attached = True
        conn.execute("BEGIN IMMEDIATE")
        live_fingerprint = _sqlite_connection_logical_fingerprint(conn)
        if live_fingerprint != expected_live_fingerprint:
            raise StorageV2MigrationError(
                "Canonical SQLite changed while migration staging was built; "
                "activation aborted to preserve concurrent writes. Retry the migration."
            )

        staging_objects = conn.execute(
            """
            SELECT type, name, COALESCE(sql, '')
            FROM staged.sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
              AND type IN ('table', 'index', 'trigger', 'view')
            ORDER BY CASE type
                WHEN 'table' THEN 0
                WHEN 'index' THEN 1
                WHEN 'trigger' THEN 2
                ELSE 3
            END, name
            """
        ).fetchall()
        main_objects = {
            (str(object_type), str(name))
            for object_type, name in conn.execute(
                """
                SELECT type, name
                FROM main.sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        for object_type, name, create_sql in staging_objects:
            key = (str(object_type), str(name))
            if key not in main_objects and create_sql:
                conn.execute(str(create_sql))
                main_objects.add(key)

        for object_type, table_name, _create_sql in staging_objects:
            if object_type != "table":
                continue
            quoted_table = _quote_sqlite_identifier(str(table_name))
            conn.execute(f"DELETE FROM main.{quoted_table}")
            conn.execute(
                f"INSERT INTO main.{quoted_table} SELECT * FROM staged.{quoted_table}"
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if attached:
            try:
                conn.execute("DETACH DATABASE staged")
            except sqlite3.Error:
                pass
        conn.close()


def _encode_sqlite_fingerprint_row(row: tuple[Any, ...]) -> bytes:
    encoded: list[dict[str, Any]] = []
    for value in row:
        if value is None:
            encoded.append({"type": "null", "value": None})
        elif isinstance(value, bytes):
            encoded.append({"type": "blob", "value": value.hex()})
        else:
            encoded.append(
                {
                    "type": type(value).__name__,
                    "value": value,
                }
            )
    return json.dumps(
        encoded,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _clear_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _sqlite_integrity_check(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "no result"
    finally:
        conn.close()


def bootstrap_canonical_runtime(data_dir: Path) -> StorageRuntimeState:
    """Bootstrap canonical runtime truth and persist the chosen runtime state."""

    data_dir = Path(data_dir)
    db_path = canonical_store_path(data_dir)
    legacy_rows, invalid = scan_legacy_payloads(data_dir)
    prior_state = read_runtime_state(data_dir)

    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            try:
                initialize_canonical_schema(conn)
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return write_runtime_state(
                data_dir,
                StorageRuntimeState(
                    mode="degraded_fallback",
                    canonical_db_path=str(db_path),
                    updated_at=_utc_now(),
                    legacy_payload_count=len(legacy_rows),
                    error=str(exc),
                    recovery_hint=_runtime_recovery_hint("degraded_fallback"),
                ),
            )

        mode = (
            prior_state.mode
            if prior_state
            and prior_state.mode in {"canonical", "bootstrapped_from_legacy"}
            else "canonical"
        )
        return write_runtime_state(
            data_dir,
            StorageRuntimeState(
                mode=mode,
                canonical_db_path=str(db_path),
                updated_at=_utc_now(),
                legacy_payload_count=len(legacy_rows),
                recovery_hint=_runtime_recovery_hint(mode),
            ),
        )

    if invalid:
        return write_runtime_state(
            data_dir,
            StorageRuntimeState(
                mode="degraded_fallback",
                canonical_db_path=str(db_path),
                updated_at=_utc_now(),
                legacy_payload_count=len(legacy_rows),
                error=f"invalid legacy JSON files: {len(invalid)}",
                recovery_hint=_runtime_recovery_hint("degraded_fallback"),
            ),
        )

    if legacy_rows:
        # Existing data never changes authority during ordinary startup.
        # Keep the lossless legacy fallback active until an operator previews
        # and explicitly applies the global migration.
        return write_runtime_state(
            data_dir,
            StorageRuntimeState(
                mode="degraded_fallback",
                canonical_db_path=str(db_path),
                updated_at=_utc_now(),
                legacy_payload_count=len(legacy_rows),
                error="legacy_migration_required",
                recovery_hint=(
                    "Legacy JSON remains authoritative. Preview with "
                    "`harness-mem maintenance migrate-store-v2 --project "
                    "<PROJECT_NAME> --dry-run`, then explicitly apply after review."
                ),
            ),
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return write_runtime_state(
        data_dir,
        StorageRuntimeState(
            mode="canonical",
            canonical_db_path=str(db_path),
            updated_at=_utc_now(),
            legacy_payload_count=0,
            recovery_hint=_runtime_recovery_hint("canonical"),
        ),
    )


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_transaction_records (
            idempotency_key TEXT PRIMARY KEY,
            request_sha256 TEXT NOT NULL,
            result_json TEXT NOT NULL,
            committed_at TEXT NOT NULL
        )
        """
    )


def build_canonical_store(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Import legacy JSON blobs into canonical entity tables."""

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
    rule_candidate_sessions = _rule_candidate_session_map(rows)
    imported_row_count = 0
    preserved_canonical_row_count = 0
    conn = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(conn)
        for legacy in rows:
            payload = json.loads(legacy.payload_json)
            if legacy.collection == "confirmed_rules":
                source_candidate_id = str(
                    payload.get("source_candidate_id") or ""
                ).strip()
                if (
                    source_candidate_id
                    and not str(payload.get("source_session_id") or "").strip()
                ):
                    source_session_id = rule_candidate_sessions.get(source_candidate_id)
                    if source_session_id:
                        payload["source_session_id"] = source_session_id
            canonical = canonical_row_from_legacy(
                legacy, payload, migrated_at=migrated_at
            )
            existing = conn.execute(
                f"SELECT 1 FROM {canonical.table_name} WHERE entity_id = ?",
                (canonical.entity_id,),
            ).fetchone()
            if existing is not None:
                # Canonical is the active truth runtime. Legacy JSON may lag
                # when dual-write is disabled, so an explicit migration must
                # never erase or overwrite canonical-only/current records.
                preserved_canonical_row_count += 1
                continue
            _upsert_canonical_row(conn, canonical)
            imported_row_count += 1
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
        "legacy_row_count": len(rows),
        "imported_row_count": imported_row_count,
        "preserved_canonical_row_count": preserved_canonical_row_count,
        "canonical_row_count": len(canonical_rows),
        "before_checksum": before_checksum,
        "after_checksum": after_checksum,
        # Compatibility field: every legacy row was either imported or was
        # already represented by canonical truth. Extra canonical rows are
        # expected and must not be treated as migration drift.
        "checksum_match": (
            imported_row_count + preserved_canonical_row_count == len(rows)
        ),
        "checksum_scope": "legacy_rows_accounted_for",
        "entity_tables": {
            table: sum(1 for row in canonical_rows if row.table_name == table)
            for table in CANONICAL_ENTITY_TABLES
        },
        "metadata_indexes": sorted(_expected_index_names()),
        "default_storage_changed": True,
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

    legacy_rows, invalid = scan_legacy_payloads(
        Path(data_dir), project_name=project_name
    )
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
        corpus_id=str(
            payload.get("corpus_id") or metadata.get("corpus_id") or "default"
        ),
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
        decay_score=float(
            payload.get("decay_score") or lifecycle.get("decay_score") or 0.0
        ),
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
        exported_rows, invalid = scan_legacy_payloads(
            export_dir, project_name=project_name
        )
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
    runtime = read_runtime_state(data_dir)
    legacy_rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    legacy_checksum = logical_checksum(legacy_rows)
    if not db_path.exists():
        relation = canonical_checksum_relation(
            data_dir,
            project_name=project_name,
            canonical_path=db_path,
        )
        relation_name = str(relation["relation"])
        return {
            "status": "degraded"
            if runtime and runtime.mode == "degraded_fallback"
            else "not_migrated",
            "project_name": project_name,
            "canonical_db_path": str(db_path),
            "runtime_state": runtime.mode
            if runtime
            else "degraded_fallback"
            if invalid
            else "canonical",
            "legacy_json_file_count": len(legacy_rows),
            "canonical_row_count": 0,
            "invalid_json_count": len(invalid),
            "legacy_invalid_json_count": len(invalid),
            "checksum_match": False,
            "partial_migration": bool(legacy_rows),
            "checksum_drift": False,
            "checksum_relation": relation["relation"],
            "checksum_relation_explanation": relation["explanation"],
            "checksum_relation_details": relation,
            "legacy_reader_policy": _legacy_reader_policy_payload(
                legacy_row_count=len(legacy_rows),
                invalid_count=len(invalid),
                canonical_row_count=0,
                checksum_relation=relation_name,
            ),
            "wal_size_bytes": 0,
            "wal_warning": False,
            "index_drift": [],
            "default_storage_changed": True,
            "runtime_error": runtime.error if runtime else None,
            "recovery_hint": (
                runtime.recovery_hint
                if runtime and runtime.recovery_hint
                else _runtime_recovery_hint(
                    "degraded_fallback" if invalid else "canonical"
                )
            ),
            "fix_command": (
                "harness-mem maintenance migrate-store-v2 "
                "--project <PROJECT_NAME> --dry-run"
            ),
            "apply_command": (
                ""
                if relation_name in {"invalid_legacy", "content_conflict"}
                else "harness-mem maintenance migrate-store-v2 "
                "--project <PROJECT_NAME> --apply"
            ),
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
    relation = canonical_checksum_relation(
        data_dir,
        project_name=project_name,
        canonical_path=db_path,
    )
    partial = relation["relation"] == "legacy_missing_in_canonical"
    runtime_mode = runtime.mode if runtime else "canonical"
    drift = relation["relation"] in {"content_conflict", "invalid_legacy"}
    status = "healthy"
    if runtime_mode == "degraded_fallback":
        status = "degraded"
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
        "runtime_state": runtime_mode,
        "legacy_json_file_count": len(legacy_rows),
        "canonical_row_count": len(canonical_rows),
        "invalid_json_count": len(invalid),
        "legacy_invalid_json_count": len(invalid),
        "legacy_checksum": legacy_checksum,
        "canonical_checksum": canonical_checksum,
        "checksum_match": canonical_checksum == legacy_checksum,
        "partial_migration": partial,
        "checksum_drift": drift,
        "checksum_relation": relation["relation"],
        "checksum_relation_explanation": relation["explanation"],
        "checksum_relation_details": relation,
        "legacy_reader_policy": _legacy_reader_policy_payload(
            legacy_row_count=len(legacy_rows),
            invalid_count=len(invalid),
            canonical_row_count=len(canonical_rows),
            checksum_relation=str(relation["relation"]),
        ),
        "wal_size_bytes": wal_size,
        "wal_warning": wal_size > wal_size_warning_bytes,
        "index_drift": missing_indexes,
        "entity_tables": {
            table: sum(1 for row in canonical_rows if row.table_name == table)
            for table in CANONICAL_ENTITY_TABLES
        },
        "default_storage_changed": True,
        "runtime_error": runtime.error if runtime else None,
        "recovery_hint": (
            runtime.recovery_hint
            if runtime and runtime.recovery_hint
            else _runtime_recovery_hint(runtime_mode)
        ),
        "dual_write_gate": {
            "env": DUAL_WRITE_ENV,
            "enabled": storage_v2_dual_write_enabled(),
        },
        "fix_command": (
            "harness-mem maintenance migrate-store-v2 "
            "--project <PROJECT_NAME> --dry-run"
            if status in {"degraded", "partial_migration", "checksum_drift"}
            else ""
        ),
        "apply_command": (
            "harness-mem maintenance migrate-store-v2 --project <PROJECT_NAME> --apply"
            if status in {"degraded", "partial_migration", "checksum_drift"}
            and relation["relation"] not in {"invalid_legacy", "content_conflict"}
            else ""
        ),
    }


def _legacy_reader_policy_payload(
    *,
    legacy_row_count: int,
    invalid_count: int,
    canonical_row_count: int,
    checksum_relation: str,
) -> dict[str, Any]:
    """Describe the explicit legacy-reader exit gate without mutating data."""

    policy: dict[str, Any] = dict(legacy_storage_support_policy())
    if invalid_count or checksum_relation in {"invalid_legacy", "content_conflict"}:
        conversion_status = "manual_review_required"
    elif legacy_row_count == 0:
        conversion_status = "no_legacy_data"
    elif canonical_row_count == 0 or checksum_relation == "legacy_missing_in_canonical":
        conversion_status = "migration_required"
    else:
        conversion_status = "canonical_verified"
    policy.update(
        {
            "conversion_status": conversion_status,
            "legacy_row_count": legacy_row_count,
            "canonical_row_count": canonical_row_count,
            "reader_removal_allowed": False,
            "migration_preview_command": (
                "harness-mem maintenance migrate-store-v2 "
                "--project <PROJECT_NAME> --dry-run"
            ),
            "migration_apply_command": (
                None
                if conversion_status == "manual_review_required"
                else "harness-mem maintenance migrate-store-v2 "
                "--project <PROJECT_NAME> --apply"
            ),
            "removal_gates": [
                "version_at_least_1.0.0",
                "date_on_or_after_2027-01-31",
                "explicit_converter_shipped",
                "canonical_verified_without_conflict",
                "release_notes_announce_removal",
            ],
        }
    )
    return policy


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
    if collection == "knowledge_entries":
        return "knowledge_entry"
    if collection == "knowledge_sources":
        return "knowledge_source"
    if collection == "knowledge_versions":
        return "knowledge_version"
    if collection == "knowledge_mutations":
        return "knowledge_mutation"
    if collection == "memory_entries":
        return str(
            payload.get("memory_type") or payload.get("category") or "memory_entry"
        )
    if collection == "observations":
        return str(payload.get("content_type") or "observation")
    if collection == "confirmed_rules":
        return "confirmed_rule"
    if collection == "relation_facts":
        return str(payload.get("relation_type") or "relation_fact")
    if collection == "skills":
        return "skill"
    if collection == "task_handoffs":
        return "task_handoff"
    if collection == "retrieval_signals":
        return str(payload.get("signal_type") or "retrieval_signal")
    if collection == "metabolism_runs":
        return str(payload.get("kind") or "metabolism_run")
    if collection == "dream_runs":
        return "dream_run"
    if "candidate" in collection:
        return collection
    return collection


def _truth_status(collection: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    valid_to = payload.get("valid_to")
    if valid_to:
        return "historical"
    if status in {"pending", "deferred", "rejected"}:
        return status
    if status in {"auto_confirmed", "provisional", "user_confirmed", "active"}:
        return "confirmed_current"
    if status == "superseded":
        return "historical"
    if collection == "knowledge_entries":
        return "confirmed_current"
    if collection in {"knowledge_sources", "knowledge_versions", "knowledge_mutations"}:
        return "supporting"
    if collection in {"memory_entries", "confirmed_rules", "relation_facts", "skills"}:
        return "confirmed_current"
    if collection in {"task_handoffs", "metabolism_runs", "dream_runs"}:
        return str(payload.get("status") or "ledger")
    if "candidate" in collection:
        return "pending"
    return "raw"


def _default_source_relpath(collection: str, entity_id: str) -> str:
    if collection == "observations":
        return f"verbatim/{entity_id}.json"
    return f"structured/{collection}/{entity_id}.json"


def _rule_candidate_session_map(rows: Iterable[LegacyPayloadRow]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        if row.collection != "rule_candidates":
            continue
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            continue
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            mapping[row.entity_id] = session_id
    return mapping


def _runtime_recovery_hint(mode: str) -> str:
    if mode == "bootstrapped_from_legacy":
        return (
            "Canonical SQLite is now the default truth store; use "
            "`harness-mem maintenance export-json-snapshot --apply` to create "
            "a rollback-compatible snapshot."
        )
    if mode == "degraded_fallback":
        return (
            "Canonical runtime is degraded. Preview with "
            "`harness-mem maintenance migrate-store-v2 --project "
            "<PROJECT_NAME> --dry-run`, then explicitly apply after review; once healthy, "
            "use `harness-mem maintenance export-json-snapshot --apply` for a "
            "rollback snapshot."
        )
    return "Canonical SQLite is the active truth runtime."


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


def _stable_json_value(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    )


def _normalize_payload_mutation(mutation: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(mutation, dict):
        raise TypeError("each mutation must be a dictionary")
    operation = str(mutation.get("operation") or "").strip().lower()
    if operation not in {"upsert", "delete"}:
        raise ValueError("mutation operation must be 'upsert' or 'delete'")
    collection = str(mutation.get("collection") or "").strip()
    entity_id = str(mutation.get("entity_id") or "").strip()
    if not collection or not entity_id:
        raise ValueError("mutation collection and entity_id must be non-empty")
    if collection not in _COLLECTION_TO_TABLE:
        raise ValueError(f"unsupported canonical collection: {collection}")

    allowed = {"operation", "collection", "entity_id", "expected_sha256"}
    normalized: dict[str, Any] = {
        "operation": operation,
        "collection": collection,
        "entity_id": entity_id,
    }
    if "expected_sha256" in mutation:
        expected = mutation["expected_sha256"]
        if expected is not None:
            expected = str(expected).strip().lower()
            if len(expected) != 64 or any(
                character not in "0123456789abcdef" for character in expected
            ):
                raise ValueError("expected_sha256 must be a lowercase SHA-256 or None")
        normalized["expected_sha256"] = expected

    if operation == "upsert":
        allowed.update({"payload", "source_relpath"})
        payload = mutation.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("upsert mutation payload must be a dictionary")
        # Freeze caller-owned data before hashing and applying it so request
        # identity and committed bytes cannot diverge under concurrent mutation.
        normalized["payload"] = json.loads(_stable_json(payload))
        if mutation.get("source_relpath") is not None:
            normalized["source_relpath"] = str(mutation["source_relpath"])
    elif "payload" in mutation or "source_relpath" in mutation:
        raise ValueError("delete mutation cannot include payload or source_relpath")

    unexpected = set(mutation) - allowed
    if unexpected:
        raise ValueError(
            "unsupported mutation fields: " + ", ".join(sorted(unexpected))
        )
    return normalized


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
