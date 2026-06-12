"""Storage v2 migration contract helpers.

v4.0.0 intentionally keeps the existing JSON + SQLite v3 storage path as the
default runtime.  This module provides the explicit, reversible contract used
by ``maintenance migrate-store-v2`` and the v4 benchmark smoke suite:

* dry-run summarizes legacy JSON payloads and computes a logical checksum
* apply writes a side-by-side canonical SQLite payload table
* rollback export writes v3-compatible JSON blobs from that canonical table

The canonical table is a contract artifact for v4.0.0; normal wake/search paths
do not read from it yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


STORAGE_V2_CONTRACT_VERSION = "storage-v2-migration-contract-v4.0.0"
STORAGE_V2_SCHEMA_VERSION = 1
STORE_V2_DIR_NAME = "store_v2"
CANONICAL_DB_NAME = "canonical.sqlite"


@dataclass(frozen=True)
class LegacyPayloadRow:
    """One legacy JSON blob normalized for checksum and canonical import."""

    row_key: str
    collection: str
    entity_id: str
    project_name: str | None
    source_relpath: str
    payload_json: str
    payload_sha256: str
    size_bytes: int


def canonical_db_path(data_dir: Path) -> Path:
    """Return the side-by-side v4.0.0 canonical DB path for a data dir."""

    return Path(data_dir) / STORE_V2_DIR_NAME / CANONICAL_DB_NAME


def build_migration_plan(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Build a read-only Storage v2 migration plan for legacy JSON blobs."""

    data_dir = Path(data_dir)
    rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    checksum = logical_checksum(rows)
    collections: dict[str, int] = {}
    for row in rows:
        collections[row.collection] = collections.get(row.collection, 0) + 1

    blockers = []
    if invalid:
        blockers.append(f"invalid_json={len(invalid)}")

    return {
        "contract_version": STORAGE_V2_CONTRACT_VERSION,
        "schema_version": STORAGE_V2_SCHEMA_VERSION,
        "action": "dry_run",
        "dry_run": True,
        "project_name": project_name,
        "data_dir": str(data_dir),
        "canonical_db_path": str(canonical_path or canonical_db_path(data_dir)),
        "default_storage_changed": False,
        "legacy_json_file_count": len(rows),
        "total_payload_bytes": sum(row.size_bytes for row in rows),
        "collections": dict(sorted(collections.items())),
        "invalid_json_count": len(invalid),
        "invalid_json_files": invalid[:20],
        "logical_checksum": checksum,
        "apply_supported": True,
        "rollback_supported": True,
        "planned_actions": [
            "scan legacy v3 JSON blobs",
            "write payload_json rows into side-by-side store_v2/canonical.sqlite",
            "compare legacy logical checksum with canonical logical checksum",
            "allow v3-compatible JSON rollback export from the canonical table",
            "leave the default JSON + SQLite runtime backend unchanged",
        ],
        "claim_readiness": {
            "ready": not blockers,
            "source": "dry-run logical checksum",
            "blocking": blockers,
        },
    }


def apply_store_v2_migration(
    data_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
) -> dict[str, Any]:
    """Write the side-by-side canonical payload table and verify checksum."""

    data_dir = Path(data_dir)
    db_path = canonical_path or canonical_db_path(data_dir)
    rows, invalid = scan_legacy_payloads(data_dir, project_name=project_name)
    if invalid:
        raise StorageV2MigrationError(
            f"Cannot apply Storage v2 migration with invalid JSON files: {len(invalid)}"
        )

    before_checksum = logical_checksum(rows)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrated_at = _utc_now()
    conn = sqlite3.connect(db_path)
    try:
        _init_schema(conn)
        for row in rows:
            conn.execute(
                """
                INSERT INTO storage_v2_payloads (
                    row_key,
                    collection,
                    entity_id,
                    project_name,
                    source_relpath,
                    payload_json,
                    payload_sha256,
                    size_bytes,
                    migrated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(row_key) DO UPDATE SET
                    collection=excluded.collection,
                    entity_id=excluded.entity_id,
                    project_name=excluded.project_name,
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
                    row.project_name,
                    row.source_relpath,
                    row.payload_json,
                    row.payload_sha256,
                    row.size_bytes,
                    migrated_at,
                ),
            )
        after_rows = _canonical_rows(conn, project_name=project_name)
        after_checksum = logical_checksum(after_rows)
        conn.execute(
            """
            INSERT INTO storage_v2_migration_runs (
                run_id,
                project_name,
                migrated_at,
                row_count,
                before_checksum,
                after_checksum,
                checksum_match
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"storage-v2-{migrated_at}",
                project_name,
                migrated_at,
                len(rows),
                before_checksum,
                after_checksum,
                int(before_checksum == after_checksum),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "contract_version": STORAGE_V2_CONTRACT_VERSION,
        "schema_version": STORAGE_V2_SCHEMA_VERSION,
        "action": "apply",
        "dry_run": False,
        "project_name": project_name,
        "data_dir": str(data_dir),
        "canonical_db_path": str(db_path),
        "default_storage_changed": False,
        "migrated_row_count": len(rows),
        "before_checksum": before_checksum,
        "after_checksum": after_checksum,
        "checksum_match": before_checksum == after_checksum,
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "claim_readiness": {
            "ready": before_checksum == after_checksum,
            "source": "apply logical checksum",
            "blocking": [] if before_checksum == after_checksum else ["checksum_mismatch"],
        },
    }


def export_store_v2_json_snapshot(
    data_dir: Path,
    export_dir: Path,
    *,
    project_name: str | None = None,
    canonical_path: Path | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    """Export canonical rows back into v3-compatible JSON blob paths."""

    data_dir = Path(data_dir)
    db_path = canonical_path or canonical_db_path(data_dir)
    export_dir = Path(export_dir)
    if not db_path.exists():
        raise StorageV2MigrationError(f"Canonical Storage v2 DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        _init_schema(conn)
        rows = _canonical_rows(conn, project_name=project_name)
    finally:
        conn.close()

    source_checksum = logical_checksum(rows)
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
            export_dir,
            project_name=project_name,
        )
        export_checksum = logical_checksum(exported_rows)
        rollback_match = source_checksum == export_checksum and not invalid
    else:
        invalid = []
        export_checksum = source_checksum
        rollback_match = True
    return {
        "contract_version": STORAGE_V2_CONTRACT_VERSION,
        "schema_version": STORAGE_V2_SCHEMA_VERSION,
        "action": "export_rollback",
        "dry_run": not apply,
        "project_name": project_name,
        "data_dir": str(data_dir),
        "canonical_db_path": str(db_path),
        "export_dir": str(export_dir),
        "would_export_json_file_count": len(rows),
        "exported_json_file_count": len(rows) if apply else 0,
        "source_checksum": source_checksum,
        "export_checksum": export_checksum,
        "rollback_checksum_match": rollback_match,
        "invalid_json_count": len(invalid),
        "claim_readiness": {
            "ready": rollback_match,
            "source": "rollback export logical checksum",
            "blocking": [] if rollback_match else ["rollback_checksum_mismatch"],
        },
    }


def scan_legacy_payloads(
    data_dir: Path,
    *,
    project_name: str | None = None,
) -> tuple[list[LegacyPayloadRow], list[str]]:
    """Scan v3-compatible JSON blob paths under ``data_dir``."""

    data_dir = Path(data_dir)
    rows: list[LegacyPayloadRow] = []
    invalid: list[str] = []
    for collection, path in _legacy_json_paths(data_dir):
        relpath = _relpath(path, data_dir)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid.append(relpath)
            continue
        if not isinstance(payload, dict):
            invalid.append(relpath)
            continue
        payload_project = _payload_project_name(payload)
        if project_name is not None and payload_project != project_name:
            continue
        entity_id = str(payload.get("id") or path.stem)
        payload_json = _stable_json(payload)
        payload_sha = _sha256_text(payload_json)
        row_key = _row_key(collection, payload_project, entity_id)
        rows.append(
            LegacyPayloadRow(
                row_key=row_key,
                collection=collection,
                entity_id=entity_id,
                project_name=payload_project,
                source_relpath=relpath,
                payload_json=payload_json,
                payload_sha256=payload_sha,
                size_bytes=path.stat().st_size,
            )
        )
    rows.sort(key=lambda row: (row.collection, row.project_name or "", row.entity_id))
    return rows, invalid


def logical_checksum(rows: list[LegacyPayloadRow]) -> str:
    """Return a stable logical checksum for payload identity and content."""

    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: (item.collection, item.project_name or "", item.entity_id)):
        digest.update(row.collection.encode("utf-8"))
        digest.update(b"\t")
        digest.update((row.project_name or "").encode("utf-8"))
        digest.update(b"\t")
        digest.update(row.entity_id.encode("utf-8"))
        digest.update(b"\t")
        digest.update(row.payload_sha256.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class StorageV2MigrationError(RuntimeError):
    """Raised when the explicit Storage v2 migration contract cannot proceed."""


def _legacy_json_paths(data_dir: Path) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    verbatim_dir = data_dir / "verbatim"
    if verbatim_dir.exists():
        paths.extend(("observations", path) for path in sorted(verbatim_dir.glob("*.json")))

    structured_dir = data_dir / "structured"
    if structured_dir.exists():
        for collection_dir in sorted(path for path in structured_dir.iterdir() if path.is_dir()):
            paths.extend(
                (collection_dir.name, path)
                for path in sorted(collection_dir.glob("*.json"))
            )
    return paths


def _canonical_rows(
    conn: sqlite3.Connection,
    *,
    project_name: str | None = None,
) -> list[LegacyPayloadRow]:
    if project_name is None:
        cursor = conn.execute(
            """
            SELECT row_key, collection, entity_id, project_name, source_relpath,
                   payload_json, payload_sha256, size_bytes
            FROM storage_v2_payloads
            ORDER BY collection, COALESCE(project_name, ''), entity_id
            """
        )
    else:
        cursor = conn.execute(
            """
            SELECT row_key, collection, entity_id, project_name, source_relpath,
                   payload_json, payload_sha256, size_bytes
            FROM storage_v2_payloads
            WHERE project_name = ?
            ORDER BY collection, COALESCE(project_name, ''), entity_id
            """,
            (project_name,),
        )
    return [
        LegacyPayloadRow(
            row_key=str(row[0]),
            collection=str(row[1]),
            entity_id=str(row[2]),
            project_name=row[3],
            source_relpath=str(row[4]),
            payload_json=str(row[5]),
            payload_sha256=str(row[6]),
            size_bytes=int(row[7]),
        )
        for row in cursor.fetchall()
    ]


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_v2_payloads (
            row_key TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            project_name TEXT,
            source_relpath TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            migrated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_storage_v2_payloads_project
        ON storage_v2_payloads(project_name, collection)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_v2_migration_runs (
            run_id TEXT PRIMARY KEY,
            project_name TEXT,
            migrated_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            before_checksum TEXT NOT NULL,
            after_checksum TEXT NOT NULL,
            checksum_match INTEGER NOT NULL
        )
        """
    )


def _payload_project_name(payload: dict[str, Any]) -> str | None:
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


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
