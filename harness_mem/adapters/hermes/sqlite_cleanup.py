"""Explicit cleanup of one fully reviewed conversation in Hermes state.db."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

from harness_mem.adapters.hermes.adapter import (
    _connect_readonly, _encode_sqlite_row, _export_state_session_rows, _find_state_db,
    _read_json_metadata, hermes_workspace_roots,
)
from harness_mem.adapters.source_inspection import metadata_project_root, normalized_root
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.integration.command_sync import default_hermes_home
from harness_mem.native_source_cleanup import NativeCleanupAction, path_from_local_file_uri


class HermesCleanupBlocked(ValueError):
    pass


_IDENTITY = re.compile(r"[\w-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FTS_TABLES = ("messages_fts", "messages_fts_trigram")
_DISPLAY_DELETE = (
    "createtriggermessages_display_identity_deleteafterdeleteonmessageswhenold.active=1orold.compacted=1"
    "beginupdatemessagessetdisplay_order=(selectmin(peer.id)frommessagesaspeerwherepeer.session_id=old.session_id"
    "and(peer.active=1orpeer.compacted=1)andpeer.display_identity=old.display_identity)wheresession_id=old.session_id"
    "and(active=1orcompacted=1)anddisplay_identity=old.display_identity;end"
)
_FTS_CAPPED_TOOL_CONTENT = "casewhen{row}role='tool'thensubstr(coalesce({row}content,''),1,8192)else{row}contentend"
_FTS_REBUILD_GUARD = (
    "(old.id>coalesce((selectcast(valueasinteger)fromstate_metawherekey='fts_rebuild_high_water'),-1)"
    "orold.id<=coalesce((selectcast(valueasinteger)fromstate_metawherekey='fts_rebuild_progress'),-1))"
)
_EXTERNAL_FTS_VIEWS = {
    "messages_fts": "createviewmessages_fts_srcasselectid,"
    + _FTS_CAPPED_TOOL_CONTENT.format(row="") + "ascontent,tool_name,tool_callsfrommessages",
    "messages_fts_trigram": "createviewmessages_fts_trigram_srcasselectid,role,content,tool_name,tool_calls"
    "frommessageswhererole<>'tool'",
}


@dataclass(frozen=True)
class HermesCleanupPlan:
    locator_sha256: str
    session_id: str
    database: Path | None = None
    project_root: str = ""
    transcript_sha256: str = ""
    witness: str = ""
    message_ids: tuple[int, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    @property
    def retained(self) -> bool:
        return bool(self.reason_codes)

    @property
    def supported(self) -> bool:
        return self.database is not None

    @property
    def actions(self) -> tuple[NativeCleanupAction, ...]:
        # The path is used by the shared planner to protect handoff dependencies.
        return () if self.database is None else (NativeCleanupAction("file", self.database, self.database.parent),)

    def to_preview(self) -> dict:
        return {
            "supported": self.supported, "retained": self.retained,
            "reason_codes": list(self.reason_codes), "locator_sha256": self.locator_sha256,
            "counts": {"planned": sum(self.counts.values()), **self.counts},
        }


def _locator_uri(database: Path, session_id: str) -> str:
    return f"{database.as_uri()}#session={quote(session_id, safe='')}"


def is_hermes_sqlite_source(source: TranscriptSource) -> bool:
    if source.client != "hermes":
        return False
    locator = urlsplit(str(source.metadata.get("native_source_uri") or source.source_uri))
    return locator.scheme == "file" and locator.path.endswith("/state.db") and locator.fragment.startswith("session=")


def _host_roots() -> set[Path]:
    home = Path.home()
    candidates = {home / ".hermes", home / "AppData" / "Local" / "hermes", default_hermes_home()}
    default = _find_state_db(home)
    if default is not None:
        candidates.add(default.absolute().parent)
    for root in tuple(candidates):
        profiles = root / "profiles"
        if profiles.is_dir():
            candidates.update(path for path in profiles.iterdir() if path.is_dir())
    return {path.absolute() for path in candidates}


def _verify_path(database: Path) -> None:
    selected = _find_state_db(Path.home())
    if (database.name != "state.db" or database.resolve() != database or not database.is_file()
            or selected is None or selected.absolute() != database):
        raise HermesCleanupBlocked("hermes_cleanup_store_unverified")


def _verify_no_copies(database: Path, session_id: str) -> None:
    for root in _host_roots() | {database.parent}:
        companion = root / "state.db"
        if companion != database and companion.is_file():
            with closing(_connect_readonly(companion)) as db:
                if db.execute("SELECT 1 FROM sessions WHERE id COLLATE BINARY = ?", (session_id,)).fetchone():
                    raise HermesCleanupBlocked("hermes_cleanup_other_store_copy_retained")
        sessions = root / "sessions"
        for path in (*sessions.glob(f"request_dump_{session_id}_*.json"),
                     *(sessions / f"{name}{extension}" for name in (session_id, f"session_{session_id}")
                       for extension in (".json", ".jsonl"))):
            if path.exists() or path.is_symlink():
                raise HermesCleanupBlocked("hermes_cleanup_export_copy_retained")
        for path in sessions.glob("session_*.json"):
            if path.is_file() and _read_json_metadata(path)[1].get("session_id") == session_id:
                raise HermesCleanupBlocked("hermes_cleanup_export_copy_retained")


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_tokens(sql: str) -> str:
    return re.sub(r"\s+", "", sql.lower()).rstrip(";")


def _fts_layout(objects: list[tuple], tables: dict[str, set[str]]) -> dict[str, bool]:
    """Validate the two on-device FTS layouts before trusting delete triggers."""
    definitions = {name: _sql_tokens(sql) for _, name, _, sql in objects}
    result = {}
    for name in _FTS_TABLES:
        if name not in definitions:
            continue
        trigram = name.endswith("_trigram")
        tokenizer = ",tokenize='trigram'" if trigram else ""
        prefix = f"createvirtualtable{name}usingfts5("
        delete = f"createtrigger{name}_deleteafterdeleteonmessages"
        if definitions[name] == f"{prefix}content{tokenizer})":
            expected_delete = f"{delete}begindeletefrom{name}whererowid=old.id;end"
            external = False
        elif definitions[name] == f"{prefix}content,tool_name,tool_calls,content='{name}_src',content_rowid='id'{tokenizer})":
            external = True
            if definitions.get(f"{name}_src") != _EXTERNAL_FTS_VIEWS[name]:
                raise HermesCleanupBlocked("hermes_cleanup_fts_layout_unsupported")
            guard = "old.role<>'tool'and" if trigram else ""
            content = "old.content" if trigram else _FTS_CAPPED_TOOL_CONTENT.format(row="old.")
            expected_delete = (f"{delete}when{guard}{_FTS_REBUILD_GUARD}begin"
                               f"insertinto{name}({name},rowid,content,tool_name,tool_calls)"
                               f"values('delete',old.id,{content},old.tool_name,old.tool_calls);end")
        else:
            raise HermesCleanupBlocked("hermes_cleanup_fts_layout_unsupported")
        if definitions.get(f"{name}_delete") != expected_delete or tables.get(f"{name}_docsize") != {"id", "sz"}:
            raise HermesCleanupBlocked("hermes_cleanup_delete_trigger_unverified")
        result[name] = external
    return result


def _schema(db: sqlite3.Connection) -> tuple[list[tuple], dict[str, set[str]], dict[str, bool]]:
    objects = [tuple(row) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name",
    )]
    tables = {name: {str(row[1]) for row in db.execute(f"PRAGMA table_info({_quoted(name)})")}
              for kind, name, _, _ in objects if kind == "table"}
    required = {
        "sessions": {"id", "started_at", "ended_at", "end_reason", "parent_session_id"},
        "messages": {"id", "session_id", "role", "active"},
        "session_turn_leases": {"conversation_id"}, "compression_locks": {"session_id"},
    }
    if any(not columns <= tables.get(table, set()) for table, columns in required.items()):
        raise HermesCleanupBlocked("hermes_cleanup_schema_unsupported")
    for table, column in (("sessions", "id"), ("messages", "id")):
        if [row[1] for row in db.execute(f"PRAGMA table_info({table})") if row[5]] != [column]:
            raise HermesCleanupBlocked("hermes_cleanup_schema_unsupported")
    references = {
        (table, row[2], row[3], row[4], row[6])
        for table in tables for row in db.execute(f"PRAGMA foreign_key_list({_quoted(table)})")
        if row[2] in {"sessions", "messages", "session_model_usage"}
    }
    supported = {
        ("messages", "sessions", "session_id", "id", "NO ACTION"),
        ("sessions", "sessions", "parent_session_id", "id", "NO ACTION"),
        ("session_model_usage", "sessions", "session_id", "id", "CASCADE"),
    }
    if not references <= supported or ("session_model_usage" in tables and (
        "session_id" not in tables["session_model_usage"] or not any(row[0] == "session_model_usage" for row in references)
    )):
        raise HermesCleanupBlocked("hermes_cleanup_schema_unsupported")

    fts = _fts_layout(objects, tables)
    for kind, name, table, sql in objects:
        tokens = _sql_tokens(sql)
        if kind == "trigger" and table in {"sessions", "messages", "session_model_usage", *_FTS_TABLES}:
            if tokens == _DISPLAY_DELETE or name in {f"{fts_table}_delete" for fts_table in fts}:
                continue
            header = re.split(r"\bbegin\b", sql.lower(), maxsplit=1)[0]
            if re.search(r"\b(?:before|after)\s+insert\s+on\b", header):
                continue
            update = re.search(r"\b(?:before|after)\s+update\s+of\s+([a-z_,\s]+?)\s+on\b", header)
            # The supported DELETE trigger only updates message display order.
            if not update or "display_order" in re.split(r"[\s,]+", update[1].strip()):
                raise HermesCleanupBlocked("hermes_cleanup_delete_trigger_unverified")
        elif kind == "table" and name not in fts and tokens.startswith("createvirtualtable"):
            raise HermesCleanupBlocked("hermes_cleanup_fts_layout_unsupported")
    return objects, tables, fts


def _linked(db: sqlite3.Connection, tables: dict[str, set[str]], session_id: str) -> bool:
    fields = {"session_id", "parent_session_id", "origin_session", "origin_session_id", "origin_ui_session_id", "conversation_id"}
    for table, columns in tables.items():
        if table in {"messages", "session_model_usage"}:
            continue
        for field_name in sorted(columns & fields):
            if db.execute(f"SELECT 1 FROM {_quoted(table)} WHERE {_quoted(field_name)} COLLATE BINARY = ? LIMIT 1",
                          (session_id,)).fetchone():
                return True
    for table, column, keys in (
        ("sessions", "model_config", ("_delegate_from", "_branched_from")),
        ("gateway_routing", "entry_json", ("session_id",)),
    ):
        if column not in tables.get(table, set()):
            continue
        for (raw,) in db.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"):
            payload = json.loads(raw)
            if isinstance(payload, dict) and any(payload.get(key) == session_id for key in keys):
                return True
    return False


def _positive_ids(values: object) -> bool:
    return (isinstance(values, (tuple, list)) and bool(values)
            and all(type(value) is int and value > 0 for value in values)
            and sorted(set(values)) == list(values))


def _cleanup_selection(
    db: sqlite3.Connection, exported: dict[str, Any],
) -> tuple[str, tuple[int, ...], dict[str, int]]:
    objects, tables, fts = _schema(db)
    session = exported["session"]
    identity = session["id"]
    ended, started = session.get("ended_at"), session.get("started_at")
    if (type(ended) not in (int, float) or type(started) not in (int, float)
            or not math.isfinite(ended) or not math.isfinite(started) or not 0 < started <= ended < time.time()
            or not session.get("end_reason") or session.get("end_reason") == "compression"
            or session.get("pinned") or session.get("hidden") or session.get("parent_session_id")
            or session.get("session_key") or session.get("handoff_state")):
        raise HermesCleanupBlocked("hermes_cleanup_session_protected")
    if _linked(db, tables, identity):
        raise HermesCleanupBlocked("hermes_cleanup_session_linked_or_leased")

    message_ids = tuple(row["id"] for row in exported["messages"])
    all_ids = tuple(row[0] for row in db.execute(
        "SELECT id FROM messages WHERE session_id COLLATE BINARY = ? ORDER BY id", (identity,),
    ))
    if not _positive_ids(message_ids) or message_ids != all_ids:
        raise HermesCleanupBlocked("hermes_cleanup_unreviewed_message_rows")

    usage = []
    if "session_model_usage" in tables:
        usage = sorted(json.dumps(_encode_sqlite_row(dict(row)), sort_keys=True) for row in db.execute(
            "SELECT * FROM session_model_usage WHERE session_id COLLATE BINARY = ?", (identity,),
        ))
    fts_rows = {
        table: [_encode_sqlite_row(dict(row)) for row in db.execute(
            f"SELECT d.id,d.sz,f.content FROM {table}_docsize d JOIN messages m ON d.id=m.id "
            f"JOIN {table} f ON f.rowid=d.id WHERE m.session_id COLLATE BINARY = ? ORDER BY d.id", (identity,),
        )] for table in fts
    }
    counts = {"sessions": 1, "messages": len(message_ids), **{table: len(rows) for table, rows in fts_rows.items()}}
    if "session_model_usage" in tables:
        counts["session_model_usage"] = len(usage)
    proof = json.dumps((objects, sha256(exported["raw_bytes"]).hexdigest(), usage, fts_rows), sort_keys=True)
    return sha256(proof.encode("utf-8")).hexdigest(), message_ids, counts


def capture_hermes_cleanup_witness(db: sqlite3.Connection, exported: dict[str, Any]) -> str | None:
    """Freeze the deletion preimage without blocking ordinary history reads."""
    try:
        return _cleanup_selection(db, exported)[0]
    except (OSError, TypeError, ValueError, sqlite3.Error):
        return None


def _read_selection(db: sqlite3.Connection, plan: HermesCleanupPlan) -> tuple[str, tuple[int, ...], dict[str, int]]:
    try:
        exported = _export_state_session_rows(db, plan.session_id)
    except ValueError as exc:
        raise HermesCleanupBlocked("hermes_cleanup_source_absent") from exc
    if (sha256(exported["raw_bytes"]).hexdigest() != plan.transcript_sha256
            or metadata_project_root(hermes_workspace_roots(exported["session"])) != plan.project_root):
        raise HermesCleanupBlocked("hermes_cleanup_source_changed")
    selected = _cleanup_selection(db, exported)
    if selected[0] != plan.witness:
        raise HermesCleanupBlocked("hermes_cleanup_witness_changed_or_missing")
    return selected


def plan_hermes_cleanup(source: TranscriptSource) -> HermesCleanupPlan:
    locator = str(source.metadata.get("native_source_uri") or source.source_uri)
    plan = HermesCleanupPlan(sha256(locator.encode()).hexdigest(), source.session_id)
    try:
        if not is_hermes_sqlite_source(source) or not _IDENTITY.fullmatch(source.session_id):
            raise HermesCleanupBlocked("hermes_cleanup_locator_unverified")
        database = path_from_local_file_uri(locator, allow_fragment=True)
        if _locator_uri(database, source.session_id) != locator:
            raise HermesCleanupBlocked("hermes_cleanup_locator_unverified")
        _verify_path(database)
        root = normalized_root(source.project_root)
        digest = source.metadata.get("native_input_sha256")
        witness = source.metadata.get("hermes_cleanup_sha256")
        if not root or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise HermesCleanupBlocked("hermes_cleanup_source_unverified")
        plan = replace(plan, database=database, project_root=root, transcript_sha256=digest, witness=witness or "")
        _verify_no_copies(database, source.session_id)
        with closing(_connect_readonly(database)) as db:
            db.execute("BEGIN")
            _, ids, counts = _read_selection(db, plan)
        return replace(plan, message_ids=ids, counts=counts)
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        reason = str(exc) if isinstance(exc, HermesCleanupBlocked) else "hermes_cleanup_unverified"
        return replace(plan, reason_codes=(reason,))


def _absence_verified(db: sqlite3.Connection, session_id: str, message_ids: tuple[int, ...]) -> bool:
    _, tables, fts = _schema(db)
    for table, column in (("sessions", "id"), ("messages", "session_id"), ("session_model_usage", "session_id")):
        if table in tables and db.execute(f"SELECT 1 FROM {table} WHERE {column} COLLATE BINARY = ?", (session_id,)).fetchone():
            return False
    if _linked(db, tables, session_id):
        return False
    for table, column in (("messages", "id"), *((f"{name}_docsize", "id") for name in fts),
                          *((name, "rowid") for name, external in fts.items() if not external)):
        # Bound variable counts on older SQLite builds and long conversations.
        for start in range(0, len(message_ids), 500):
            batch = message_ids[start:start + 500]
            params = ",".join("?" for _ in batch)
            if db.execute(f"SELECT 1 FROM {table} WHERE {column} IN ({params}) LIMIT 1", batch).fetchone():
                return False
    return True


def hermes_receipt_absence_verified(locator_sha256: str, session_id: str, *, message_ids: object = ()) -> bool:
    """Reopen the configured database and verify exact native rows and companion absence."""
    if not _IDENTITY.fullmatch(session_id) or not _positive_ids(message_ids):
        return False
    assert isinstance(message_ids, (tuple, list))
    try:
        selected = _find_state_db(Path.home())
        if selected is None:
            return False
        database = selected.absolute()
        _verify_path(database)
        if sha256(_locator_uri(database, session_id).encode()).hexdigest() != locator_sha256:
            return False
        _verify_no_copies(database, session_id)
        with closing(_connect_readonly(database)) as db:
            db.execute("BEGIN")
            return _absence_verified(db, session_id, tuple(message_ids))
    except (OSError, TypeError, ValueError, sqlite3.Error):
        return False


def hermes_source_absence_verified(source: TranscriptSource, *, message_ids: object = ()) -> bool:
    locator = str(source.metadata.get("native_source_uri") or source.source_uri)
    return is_hermes_sqlite_source(source) and hermes_receipt_absence_verified(
        sha256(locator.encode()).hexdigest(), source.session_id, message_ids=message_ids,
    )


def _backup_path(data_dir: Path, receipt_id: str) -> Path:
    if str(UUID(receipt_id)) != receipt_id:
        raise HermesCleanupBlocked("hermes_cleanup_receipt_unverified")
    target = data_dir.resolve() / "hermes-cleanup-backups" / f"{receipt_id}.sqlite"
    if target.resolve() != target:
        raise HermesCleanupBlocked("hermes_cleanup_backup_path_unverified")
    return target


def discard_hermes_cleanup_backup(data_dir: Path, receipt_id: str) -> bool:
    try:
        _backup_path(data_dir, receipt_id).unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        return False


def _check_backup_progress(status: int, _remaining: int, _total: int) -> None:
    if status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        raise HermesCleanupBlocked("hermes_cleanup_backup_busy")


def apply_hermes_cleanup(plan: HermesCleanupPlan, *, data_dir: Path, receipt_id: str) -> dict:
    """Remove reviewed rows in one native transaction and verify by reopening."""
    database = plan.database
    if database is None or plan.retained or not plan.message_ids:
        return {"status": "retained", "reason_codes": list(plan.reason_codes or ("hermes_cleanup_invalid_plan",))}
    backup = None
    commit_attempted = False
    try:
        _verify_path(database)
        with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0.2)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            expected = (plan.witness, plan.message_ids, plan.counts)
            if _read_selection(db, plan) != expected:
                raise HermesCleanupBlocked("hermes_cleanup_source_changed")
            _verify_no_copies(database, plan.session_id)
            target = _backup_path(data_dir, receipt_id)
            target.parent.mkdir(exist_ok=True)
            with target.open("xb"):
                pass
            backup = target
            with closing(_connect_readonly(database)) as live, closing(sqlite3.connect(backup)) as saved:
                saved.row_factory = sqlite3.Row
                live.backup(saved, pages=256, progress=_check_backup_progress)
                if _read_selection(saved, plan) != expected:
                    raise HermesCleanupBlocked("hermes_cleanup_backup_unverified")
            with backup.open("r+b") as durable:
                os.fsync(durable.fileno())
            _verify_path(database)
            _verify_no_copies(database, plan.session_id)
            removed_messages = db.execute("DELETE FROM messages WHERE session_id COLLATE BINARY = ?", (plan.session_id,))
            removed_session = db.execute("DELETE FROM sessions WHERE id COLLATE BINARY = ?", (plan.session_id,))
            if (removed_messages.rowcount != len(plan.message_ids) or removed_session.rowcount != 1
                    or not _absence_verified(db, plan.session_id, plan.message_ids)):
                raise HermesCleanupBlocked("hermes_cleanup_delete_unverified")
            # External-content SELECTs alone read the backing messages, even
            # when the index contains stale tokens. Compare the actual postings.
            for table, external in _schema(db)[2].items():
                if external:
                    db.execute(f"INSERT INTO {table}({table},rank) VALUES ('integrity-check',1)")
            commit_attempted = True
            db.commit()
        if not hermes_receipt_absence_verified(plan.locator_sha256, plan.session_id, message_ids=plan.message_ids):
            raise HermesCleanupBlocked("hermes_cleanup_commit_unverified")
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        reason = str(exc) if isinstance(exc, HermesCleanupBlocked) else "hermes_cleanup_transaction_unavailable"
        if backup is not None and not commit_attempted and not discard_hermes_cleanup_backup(data_dir, receipt_id):
            reason = "hermes_cleanup_backup_retained"
        return {"status": "partial_failure" if commit_attempted else "retained", "reason_codes": [reason]}
    return {"status": "deleted", "reason_codes": ["hermes_cleanup_rows_deleted"],
            "message_ids": list(plan.message_ids), "counts": plan.counts}
