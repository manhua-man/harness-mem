"""Explicit cleanup for a proven single-store Cursor archive."""
from __future__ import annotations

from base64 import b64encode
from contextlib import closing
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

from harness_mem.adapters.cursor import adapter as cursor_adapter
from harness_mem.adapters.cursor.sqlite_history import (
    CursorHistoryError, _read_db, _validate_disk_schema, cursor_profile_roots, cursor_transcript_bytes,
    discover_sqlite_databases, prefix_rows, workspace_owner,
)
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.native_source_cleanup import NativeCleanupAction, path_from_local_file_uri


class CursorCleanupBlocked(ValueError):
    pass


@dataclass(frozen=True)
class CursorCleanupPlan:
    locator_sha256: str
    session_id: str
    database: Path | None = None
    project_root: Path | None = None
    transcript_sha256: str = ""
    workspace_id: str = ""
    keys: tuple[str, ...] = ()
    primary_sha256: str = ""
    search_database: Path | None = None
    search_sha256: str = ""
    search_rowid: int | None = None
    reason_codes: tuple[str, ...] = ()

    @property
    def retained(self) -> bool:
        return bool(self.reason_codes)

    @property
    def supported(self) -> bool:
        return self.database is not None

    @property
    def actions(self) -> tuple[NativeCleanupAction, ...]:
        # Used only to check whether handoffs still depend on the raw source.
        return tuple(NativeCleanupAction("file", path, path.parent)
                     for path in (self.database, self.search_database) if path is not None)

    def to_preview(self) -> dict:
        return {"supported": self.supported, "retained": self.retained,
                "reason_codes": list(self.reason_codes), "locator_sha256": self.locator_sha256,
                "counts": {"planned": len(self.keys) + 1 + (3 if self.search_database else 0) if self.keys else 0}}


def is_cursor_sqlite_source(source: TranscriptSource) -> bool:
    return source.client == "cursor" and str(source.metadata.get("native_source_uri", source.source_uri)).startswith(
        "cursor-sqlite:",
    )


def _locator(source: TranscriptSource) -> tuple[str, Path]:
    locator = str(source.metadata.get("native_source_uri", source.source_uri))
    file_uri, separator, identity = locator.removeprefix("cursor-sqlite:").partition("#")
    if not separator or unquote(identity) != source.session_id or not re.fullmatch(r"[\w-]+", source.session_id):
        raise CursorCleanupBlocked("cursor_cleanup_locator_unverified")
    parsed = urlsplit(file_uri)
    if parsed.query or parsed.netloc not in {"", "localhost"}:
        raise CursorCleanupBlocked("cursor_cleanup_locator_unverified")
    database = path_from_local_file_uri(file_uri).absolute()
    if (database.name != "state.vscdb" or database.parent.name != "globalStorage"
            or database.resolve() != database or database not in discover_sqlite_databases()):
        raise CursorCleanupBlocked("cursor_cleanup_global_store_unverified")
    return locator, database


def _table_columns(db: sqlite3.Connection, table: str) -> set[str]:
    row = db.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
    if row is None:
        return set()
    if row != ("table",):
        raise CursorCleanupBlocked("cursor_cleanup_schema_unsupported")
    # These names are fixed internal schema identifiers.
    return {column[1] for column in db.execute(f'PRAGMA table_info("{table}")')}


def _itemtable_reference(db: sqlite3.Connection, identity: str) -> bool:
    columns = _table_columns(db, "ItemTable")
    if not columns:
        return False
    if not {"key", "value"} <= columns:
        raise CursorCleanupBlocked("cursor_cleanup_schema_unsupported")
    values = db.execute(
        "SELECT key,value FROM ItemTable WHERE key IN ('composer.composerHeaders','composer.composerData')",
    )
    for key, raw in values:
        try:
            document = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise CursorCleanupBlocked("cursor_cleanup_index_unverified") from exc
        headers = document.get("allComposers") if isinstance(document, dict) else None
        focus_fields = {"lastFocusedComposerIds", "selectedComposerIds"}
        migration_fields = {"hasMigratedComposerData", "hasMigratedMultipleComposers"}
        if (key == "composer.composerData" and isinstance(document, dict)
                and set(document) == focus_fields | migration_fields
                and all(type(document[name]) is bool for name in migration_fields)
                and all(isinstance(document[name], list) and all(isinstance(value, str) for value in document[name])
                        for name in focus_fields)):
            if any(identity in document[name] for name in focus_fields):
                return True
            continue
        if not isinstance(headers, list) or any(not isinstance(row, dict) for row in headers):
            raise CursorCleanupBlocked("cursor_cleanup_index_unverified")
        if any(identity in (row.get("composerId"), row.get("id")) for row in headers):
            return True
    return False


def _disk_keys(db: sqlite3.Connection, identity: str) -> set[str]:
    """Detect exact session segments without treating an ID substring as ownership."""
    return {key for (key,) in db.execute("SELECT key FROM cursorDiskKV")
            if isinstance(key, str) and identity in key.split(":")[1:]}


def _search_has_id(db: sqlite3.Connection, identity: str) -> bool:
    if not all("id" in _table_columns(db, table)
               for table in ("conversations", "conversation_search_candidates")):
        raise CursorCleanupBlocked("cursor_cleanup_search_schema_unverified")
    return any(db.execute(f'SELECT 1 FROM "{table}" WHERE id=?', (identity,)).fetchone()
               for table in ("conversations", "conversation_search_candidates"))


def _verify_no_companions(plan: CursorCleanupPlan, *, allow_selected_search: bool = False) -> None:
    assert plan.database is not None
    identity = plan.session_id
    storage = plan.database.parent.parent / "workspaceStorage"
    databases = {plan.database, *discover_sqlite_databases(), *storage.glob("*/state.vscdb")}
    search_locations = {path.parent if path.parent.name == "globalStorage"
                        else path.parent.parent.parent / "globalStorage" for path in databases}
    search_locations.update(profile / "globalStorage" for profile in cursor_profile_roots())
    for companion in sorted(databases - {plan.database}):
        with _read_db(companion) as db:
            columns = _table_columns(db, "composerHeaders")
            if columns and "composerId" not in columns:
                raise CursorCleanupBlocked("cursor_cleanup_companion_schema_unverified")
            if ((columns and db.execute("SELECT 1 FROM composerHeaders WHERE composerId=?", (identity,)).fetchone())
                    or (_table_columns(db, "cursorDiskKV") and _disk_keys(db, identity))
                    or _itemtable_reference(db, identity)):
                raise CursorCleanupBlocked("cursor_cleanup_other_store_copy_retained")
    for location in sorted(search_locations):
        index = location / "conversation-search.db"
        if not index.exists():
            continue
        if allow_selected_search and index == plan.search_database:
            continue
        with _read_db(index) as db:
            if _search_has_id(db, identity):
                raise CursorCleanupBlocked("cursor_cleanup_search_copy_retained")
    for transcripts in cursor_adapter.DEFAULT_PROJECTS_DIR.glob("*/agent-transcripts"):
        if (transcripts / identity).exists() or any(transcripts.glob(f"*/{identity}.jsonl")):
            raise CursorCleanupBlocked("cursor_cleanup_jsonl_copy_retained")


def _select_rows(db: sqlite3.Connection, identity: str) -> tuple[str, list[tuple[str, str]], tuple[str, ...]]:
    _validate_disk_schema(db)
    if not {"composerId", "workspaceId", "isArchived"} <= _table_columns(db, "composerHeaders"):
        raise CursorCleanupBlocked("cursor_cleanup_schema_unsupported")
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('composerHeaders','cursorDiskKV')",
    ).fetchone():
        raise CursorCleanupBlocked("cursor_cleanup_schema_unsupported")
    headers = db.execute(
        "SELECT workspaceId, isArchived FROM composerHeaders WHERE composerId COLLATE BINARY=?", (identity,),
    ).fetchall()
    if not headers:
        raise CursorCleanupBlocked("cursor_cleanup_source_absent")
    if len(headers) != 1 or type(headers[0][1]) is not int or headers[0][1] != 1:
        raise CursorCleanupBlocked("cursor_cleanup_archive_unverified")
    workspace = headers[0][0]
    if not isinstance(workspace, str) or not re.fullmatch(r"[\w-]+", workspace):
        raise CursorCleanupBlocked("cursor_cleanup_workspace_unverified")
    composer = db.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key COLLATE BINARY=?", ("composerData:" + identity,),
    ).fetchall()
    if len(composer) != 1:
        raise CursorCleanupBlocked("cursor_cleanup_source_unavailable")
    bubbles = prefix_rows(db, f"bubbleId:{identity}:")
    records = [*composer, *bubbles]
    extra = _disk_keys(db, identity) - {key for key, _ in records}
    checkpoint = re.compile(r"checkpointId:" + re.escape(identity) + r":[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
    if (any(len(key.split(":")) != 3 for key, _ in bubbles)
            or any(checkpoint.fullmatch(key) is None for key in extra)
            or _itemtable_reference(db, identity)):
        raise CursorCleanupBlocked("cursor_cleanup_additional_records_unverified")
    for key in extra:
        (raw,) = db.execute("SELECT value FROM cursorDiskKV WHERE key COLLATE BINARY=?", (key,)).fetchone()
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise CursorCleanupBlocked("cursor_cleanup_checkpoint_unverified") from exc
        lists = {"files", "nonExistentFiles", "newlyCreatedFolders", "activeInlineDiffs"}
        objects = {"inlineDiffNewlyCreatedResources"}
        if (not isinstance(value, dict) or set(value) != lists | objects
                or not all(isinstance(value[name], list) for name in lists)
                or not all(isinstance(value[name], dict) for name in objects)):
            raise CursorCleanupBlocked("cursor_cleanup_checkpoint_unverified")
    return workspace, records, tuple(key for key, _ in records) + tuple(sorted(extra))


def _verified_rows(db: sqlite3.Connection, plan: CursorCleanupPlan) -> tuple[str, tuple[str, ...]]:
    assert plan.database is not None
    workspace, records, keys = _select_rows(db, plan.session_id)
    owner_file = plan.database.parent.parent / "workspaceStorage" / workspace / "workspace.json"
    if owner_file.resolve() != owner_file or workspace_owner(owner_file) != plan.project_root:
        raise CursorCleanupBlocked("cursor_cleanup_workspace_unverified")
    if sha256(cursor_transcript_bytes(records)).hexdigest() != plan.transcript_sha256:
        raise CursorCleanupBlocked("cursor_cleanup_source_changed")
    return workspace, keys


def _primary_witness(db: sqlite3.Connection, identity: str, workspace: str, keys: tuple[str, ...]) -> str:
    header = db.execute("SELECT * FROM composerHeaders WHERE composerId COLLATE BINARY=?",
                        (identity,)).fetchone()
    values = [db.execute("SELECT key,value FROM cursorDiskKV WHERE key COLLATE BINARY=?", (key,)).fetchone()
              for key in keys]
    witness = json.dumps([workspace, header, values], ensure_ascii=False, separators=(",", ":"),
                         default=lambda value: {"bytes": b64encode(value).decode("ascii")})
    return sha256(witness.encode()).hexdigest()


def capture_primary_witness(db: sqlite3.Connection, identity: str) -> str:
    """Seal the archived header and owned rows in the transcript read transaction."""
    workspace, _records, keys = _select_rows(db, identity)
    return _primary_witness(db, identity, workspace, keys)


def primary_witness(db: sqlite3.Connection, plan: CursorCleanupPlan) -> str:
    workspace, keys = _verified_rows(db, plan)
    return _primary_witness(db, plan.session_id, workspace, keys)


def primary_absent(db: sqlite3.Connection, plan: CursorCleanupPlan) -> bool:
    _validate_disk_schema(db)
    return ("composerId" in _table_columns(db, "composerHeaders")
            and not db.execute("SELECT 1 FROM composerHeaders WHERE composerId=?", (plan.session_id,)).fetchone()
            and not _disk_keys(db, plan.session_id) and not _itemtable_reference(db, plan.session_id))


def delete_primary_rows(db: sqlite3.Connection, plan: CursorCleanupPlan) -> None:
    before = db.total_changes
    db.executemany("DELETE FROM cursorDiskKV WHERE key COLLATE BINARY=?", [(key,) for key in plan.keys])
    db.execute("DELETE FROM composerHeaders WHERE composerId COLLATE BINARY=? AND workspaceId=? AND isArchived=1",
               (plan.session_id, plan.workspace_id))
    if db.total_changes - before != len(plan.keys) + 1 or not primary_absent(db, plan):
        raise CursorCleanupBlocked("cursor_cleanup_row_set_changed")


def cursor_cleanup_target(source: TranscriptSource) -> CursorCleanupPlan:
    locator, database = _locator(source)
    digest = source.metadata.get("native_input_sha256")
    root = Path(source.project_root)
    if not root.is_absolute() or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CursorCleanupBlocked("cursor_cleanup_frozen_source_unverified")
    return CursorCleanupPlan(sha256(locator.encode()).hexdigest(), source.session_id,
                             database=database, project_root=root.resolve(), transcript_sha256=digest,
                             primary_sha256=str(source.metadata.get("cursor_cleanup_primary_sha256") or ""),
                             search_sha256=str(source.metadata.get("cursor_cleanup_search_sha256") or ""))


def plan_cursor_cleanup(source: TranscriptSource) -> CursorCleanupPlan:
    locator = str(source.metadata.get("native_source_uri", source.source_uri))
    plan = CursorCleanupPlan(sha256(locator.encode()).hexdigest(), source.session_id)
    try:
        plan = cursor_cleanup_target(source)
        database = plan.database
        assert database is not None
        with _read_db(database) as db:
            workspace, keys = _verified_rows(db, plan)
            primary_digest = primary_witness(db, plan)
        index = database.with_name("conversation-search.db")
        if index.exists():
            from harness_mem.adapters.cursor.search_cleanup import SearchCleanupBlocked, search_rows_sha256, select_search_rows
            with _read_db(index) as db:
                if _search_has_id(db, source.session_id):
                    if index.resolve() != index:
                        raise CursorCleanupBlocked("cursor_cleanup_search_copy_retained")
                    try:
                        selection = select_search_rows(db, source.session_id)
                    except SearchCleanupBlocked as exc:
                        raise CursorCleanupBlocked("cursor_cleanup_search_copy_retained") from exc
                    if selection is None:
                        raise CursorCleanupBlocked("cursor_cleanup_search_copy_retained")
                    if search_rows_sha256(selection) != plan.search_sha256:
                        raise CursorCleanupBlocked("cursor_cleanup_search_witness_changed_or_missing")
                    plan = replace(plan, search_database=index)
        if plan.search_sha256 and plan.search_database is None:
            raise CursorCleanupBlocked("cursor_cleanup_search_witness_changed_or_missing")
        if (plan.search_database is not None or any(key.startswith("checkpointId:") for key in keys)
                or plan.primary_sha256) and plan.primary_sha256 != primary_digest:
            raise CursorCleanupBlocked("cursor_cleanup_primary_witness_changed_or_missing")
        _verify_no_companions(plan, allow_selected_search=True)
        return replace(plan, workspace_id=workspace, keys=keys)
    except CursorCleanupBlocked as exc:
        return replace(plan, reason_codes=(str(exc),))
    except (CursorHistoryError, OSError, ValueError, sqlite3.Error):
        return replace(plan, reason_codes=("cursor_cleanup_database_unverified",))


def cursor_source_absence_verified(source: TranscriptSource, *, search_rowid: int | None = None) -> bool:
    """Verify absence for a receipt that already proves a native commit."""
    try:
        locator, database = _locator(source)
        plan = CursorCleanupPlan(sha256(locator.encode()).hexdigest(), source.session_id, database,
                                 search_database=database.with_name("conversation-search.db") if search_rowid is not None else None,
                                 search_rowid=search_rowid)
        return _absence_verified(plan)
    except (OSError, ValueError, sqlite3.Error):
        return False


def cursor_receipt_absence_verified(locator_sha256: str, session_id: str, *, search_rowid: int | None = None) -> bool:
    """Find only the exact store bound to a content-free completed receipt."""
    if not re.fullmatch(r"[\w-]+", session_id):
        return False
    try:
        databases = []
        for path in discover_sqlite_databases():
            if path.name != "state.vscdb" or path.parent.name != "globalStorage" or path.resolve() != path:
                continue
            locator = "cursor-sqlite:" + path.as_uri() + "#" + quote(session_id, safe="")
            if sha256(locator.encode()).hexdigest() == locator_sha256:
                databases.append(path)
        if len(databases) != 1:
            return False
        database = databases[0]
        return _absence_verified(CursorCleanupPlan(
            locator_sha256, session_id, database,
            search_database=database.with_name("conversation-search.db") if search_rowid is not None else None,
            search_rowid=search_rowid,
        ))
    except (OSError, ValueError, sqlite3.Error):
        return False


def _absence_verified(plan: CursorCleanupPlan) -> bool:
    assert plan.database is not None
    _verify_no_companions(plan)
    if plan.search_database is not None:
        from harness_mem.adapters.cursor.search_cleanup import search_receipt_absent
        if (plan.search_database.resolve() != plan.search_database
                or type(plan.search_rowid) is not int or plan.search_rowid < 1):
            return False
        with _read_db(plan.search_database) as search:
            if not search_receipt_absent(search, plan.session_id, plan.search_rowid):
                return False
    with _read_db(plan.database) as db:
        return primary_absent(db, plan)


def apply_cursor_cleanup(plan: CursorCleanupPlan, *, data_dir: Path, receipt_id: str) -> dict:
    """Delete an exact set of rows under one SQLite transaction and reopen it."""
    if plan.retained or not plan.supported or not plan.keys or plan.database is None:
        return {"status": "retained", "reason_codes": list(plan.reason_codes or ("cursor_cleanup_invalid_plan",))}
    backup = None
    committed = verified = False
    reason = "cursor_cleanup_rows_deleted"
    try:
        if plan.database.resolve() != plan.database:
            raise CursorCleanupBlocked("cursor_cleanup_global_store_unverified")
        _verify_no_companions(plan)
        with closing(sqlite3.connect(plan.database.as_uri() + "?mode=rw", uri=True, timeout=0.1)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            if _verified_rows(db, plan) != (plan.workspace_id, plan.keys):
                raise CursorCleanupBlocked("cursor_cleanup_source_changed")
            if plan.primary_sha256 and primary_witness(db, plan) != plan.primary_sha256:
                raise CursorCleanupBlocked("cursor_cleanup_primary_witness_changed_or_missing")
            target = _backup_path(data_dir, receipt_id)
            target.parent.mkdir(exist_ok=True)
            with target.open("xb"):
                pass
            backup = target
            # A second read connection sees the locked pre-transaction state.
            # Calling backup on the writer itself would block on its transaction.
            with _read_db(plan.database) as source, closing(sqlite3.connect(backup)) as copy:
                source.backup(copy, pages=256, progress=_backup_progress)
                if _verified_rows(copy, plan) != (plan.workspace_id, plan.keys):
                    raise CursorCleanupBlocked("cursor_cleanup_backup_unverified")
            _verify_no_companions(plan)
            if plan.database.resolve() != plan.database or _verified_rows(db, plan) != (plan.workspace_id, plan.keys):
                raise CursorCleanupBlocked("cursor_cleanup_source_changed")
            delete_primary_rows(db, plan)
            db.commit()
            committed = True
        verified = _absence_verified(plan)
        if not verified:
            raise CursorCleanupBlocked("cursor_cleanup_post_commit_unverified")
    except (OSError, ValueError, sqlite3.Error) as exc:
        reason = str(exc) if isinstance(exc, CursorCleanupBlocked) else "cursor_cleanup_transaction_unavailable"
    finally:
        # The caller removes the pre-image only after storing the verified
        # native commit. An interruption before that point leaves the copy.
        if backup is not None and not committed:
            try:
                backup.unlink()
            except OSError:
                verified = False
                reason = "cursor_cleanup_backup_retained"
    status = "deleted" if verified else "partial_failure" if committed else "retained"
    return {"status": status, "reason_codes": [reason]}


def _backup_path(data_dir: Path, receipt_id: str, *, kind: str = "") -> Path:
    if str(UUID(receipt_id)) != receipt_id:
        raise CursorCleanupBlocked("cursor_cleanup_invalid_receipt")
    directory = data_dir.resolve() / "cursor-cleanup-backups"
    if kind not in {"", ".primary", ".search"}:
        raise CursorCleanupBlocked("cursor_cleanup_invalid_receipt")
    path = directory / f"{receipt_id}{kind}.sqlite"
    if path.resolve() != path:
        raise CursorCleanupBlocked("cursor_cleanup_backup_path_unverified")
    return path


def discard_cursor_cleanup_backup(data_dir: Path, receipt_id: str) -> bool:
    try:
        for kind in ("", ".primary", ".search"):
            _backup_path(data_dir, receipt_id, kind=kind).unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        return False


def _backup_progress(status: int, _remaining: int, _total: int) -> None:
    if status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        raise CursorCleanupBlocked("cursor_cleanup_backup_busy")
