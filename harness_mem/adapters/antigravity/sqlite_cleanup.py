"""Remove one reviewed Antigravity SQLite conversation and its local indexes."""

from __future__ import annotations

import base64
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable, Iterator
from uuid import UUID

from harness_mem.adapters.antigravity.sqlite_history import (
    SQLITE_SOURCE_KIND, _encode_cell, _fields, _one, _varint, read_only_db,
    sqlite_conversation_bytes,
)
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.native_source_cleanup import (
    NativeCleanupAction, _action_manifest, _is_link_or_reparse, _remove_directory_tree,
    path_from_local_file_uri,
)


class AntigravityCleanupBlocked(ValueError):
    """A selected conversation cannot safely be removed or resumed."""


_PROFILES = ("antigravity", "antigravity-cli", "antigravity-ide")
_SUMMARIES = "conversation_summaries.db"
_PROTOS = ("agyhub_summaries_proto.pb", "jetbox_summaries_proto.pb")
_SIDECARS = ("-wal", "-shm", "-journal")
_SUMMARY_COLUMNS = (
    "conversation_id", "title", "preview", "step_count", "last_modified_time",
    "workspace_uris", "status", "source", "project_id", "agent_name",
    "parent_conversation_id", "nesting_depth", "battle_id", "winning_conversation_id",
    "not_fully_idle", "killed", "last_user_input_time", "last_user_input_step_index",
    "app_data_dir", "raw_summary", "group_id",
)
_FTS_SQL = """CREATE VIRTUAL TABLE conversations_fts USING fts5(
    conversation_id UNINDEXED,
    chunk_index UNINDEXED,
    chunk_first_step UNINDEXED,
    chunk_last_step UNINDEXED,
    last_modified_time UNINDEXED,
    step_count UNINDEXED,
    last_step_created_at UNINDEXED,
    archived UNINDEXED,
    user_step_byte_offsets UNINDEXED,
    agent_step_byte_offsets UNINDEXED,
    title,
    workspace,
    project,
    user_body,
    agent_body,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '1 2 3'
)"""
_FTS_TABLES = {
    "conversations_fts", "conversations_fts_config", "conversations_fts_content",
    "conversations_fts_data", "conversations_fts_docsize", "conversations_fts_idx",
}


@dataclass(frozen=True)
class AntigravityCleanupPlan:
    source: TranscriptSource = field(repr=False)
    locator_sha256: str
    database: Path | None = None
    actions: tuple[NativeCleanupAction, ...] = ()
    search_count: int = 0
    summary_count: int = 0
    proto_count: int = 0
    supported: bool = True
    retained: bool = False
    reason_codes: tuple[str, ...] = ()

    def to_preview(self) -> dict:
        return {
            "supported": self.supported,
            "retained": self.retained,
            "reason_codes": list(self.reason_codes),
            "locator_sha256": self.locator_sha256,
            "counts": {
                "planned": len(self.actions) + self.summary_count + self.search_count + self.proto_count,
                "native_files_or_directories": len(self.actions),
                "summary_rows": self.summary_count,
                "search_rows": self.search_count,
                "protobuf_entries": self.proto_count,
            },
        }


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _roots() -> tuple[Path, ...]:
    return tuple(Path.home() / ".gemini" / profile for profile in _PROFILES)


def _safe(path: Path) -> bool:
    return path.resolve() == path and not _is_link_or_reparse(path)


def _exists(path: Path) -> bool:
    return path.exists() or _is_link_or_reparse(path)


def _database_path(root: Path, identity: str) -> Path:
    return root / "conversations" / f"{identity}.db"


def _check_location(database: Path, identity: str) -> Path:
    root = database.parent.parent
    if not _uuid(identity) or root not in _roots() or database != _database_path(root, identity) or not _safe(database):
        raise AntigravityCleanupBlocked("antigravity_cleanup_locator_unverified")
    return root


def _base_plan(source: TranscriptSource) -> AntigravityCleanupPlan:
    locator = str(source.metadata.get("native_source_uri") or source.source_uri)
    plan = AntigravityCleanupPlan(source, sha256(locator.encode()).hexdigest())
    if source.client != "antigravity" or source.source_kind != SQLITE_SOURCE_KIND:
        return replace(plan, supported=False, reason_codes=("antigravity_cleanup_source_unsupported",))
    path = path_from_local_file_uri(locator)
    _check_location(path, source.session_id)
    return replace(plan, database=path)


def _sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(path.with_name(path.name + suffix) for suffix in _SIDECARS)


def _check_activity(path: Path, identity: str) -> None:
    if (os.environ.get("ANTIGRAVITY_CURRENT_CONVERSATION_ID") == identity
            or any(_exists(sidecar) for sidecar in _sidecars(path))):
        raise AntigravityCleanupBlocked("antigravity_cleanup_active_or_open")


@contextmanager
def _read_main(path: Path) -> Iterator[sqlite3.Connection]:
    # A standalone conversation with a WAL or rollback journal stays protected.
    # Immutable mode prevents a read of an idle standalone DB creating sidecars.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=0.2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        yield db


@contextmanager
def _write_summary(path: Path) -> Iterator[sqlite3.Connection]:
    if not _safe(path):
        raise AntigravityCleanupBlocked("antigravity_cleanup_locator_unverified")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.2)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        yield db


def _validate_summary(db: sqlite3.Connection) -> bool:
    schema = db.execute("SELECT type, name, sql FROM main.sqlite_schema").fetchall()
    tables = {name for kind, name, _ in schema if kind == "table" and not name.startswith("sqlite_stat")}
    columns = db.execute("PRAGMA main.table_info(conversation_summaries)").fetchall()
    search = "conversations_fts" in tables
    expected = {"conversation_summaries"} | (_FTS_TABLES | {"search_schema_version"} if search else set())
    if (db.execute("PRAGMA user_version").fetchone() != (3,) or tables != expected
            or tuple(row[1] for row in columns) != _SUMMARY_COLUMNS or not columns or columns[0][5] != 1
            or any(row[5] != 0 for row in columns[1:])
            or any(kind not in {"table", "index"} for kind, _, _ in schema)
            or db.execute("PRAGMA main.foreign_key_list(conversation_summaries)").fetchone()):
        raise AntigravityCleanupBlocked("antigravity_cleanup_summary_schema_unsupported")
    if search:
        sql = next(sql for kind, name, sql in schema if kind == "table" and name == "conversations_fts")
        if (" ".join(sql.lower().split()) != " ".join(_FTS_SQL.lower().split())
                or db.execute("SELECT version FROM search_schema_version").fetchall() != [(3,)]):
            raise AntigravityCleanupBlocked("antigravity_cleanup_search_schema_unsupported")
    return search


def _summary_records(
    db: sqlite3.Connection, identity: str,
) -> tuple[tuple | None, tuple[tuple, ...]]:
    search = _validate_summary(db)
    summary = db.execute(
        "SELECT * FROM main.conversation_summaries WHERE conversation_id COLLATE BINARY=?",
        (identity,),
    ).fetchone()
    if db.execute(
        "SELECT 1 FROM main.conversation_summaries WHERE conversation_id COLLATE BINARY<>? AND "
        "(parent_conversation_id COLLATE BINARY=? OR winning_conversation_id COLLATE BINARY=?) LIMIT 1",
        (identity, identity, identity),
    ).fetchone():
        raise AntigravityCleanupBlocked("antigravity_cleanup_related_conversation")
    if not search:
        return summary, ()
    rows = tuple(db.execute(
        "SELECT rowid,* FROM main.conversations_fts WHERE conversation_id COLLATE BINARY=? ORDER BY rowid",
        (identity,),
    ))
    for rowid, *_ in rows:
        if (type(rowid) is not int or rowid < 1 or not db.execute(
            "SELECT 1 FROM main.conversations_fts_docsize WHERE id=?", (rowid,),
        ).fetchone()):
            raise AntigravityCleanupBlocked("antigravity_cleanup_search_footprint_unverified")
    return summary, rows


def _summary_absent(db: sqlite3.Connection, identity: str, rowids: tuple[int, ...]) -> bool:
    summary, search = _summary_records(db, identity)
    if summary is not None or search:
        return False
    return all(
        db.execute(f"SELECT 1 FROM main.{table} WHERE id=?", (rowid,)).fetchone() is None
        for rowid in rowids for table in ("conversations_fts_content", "conversations_fts_docsize")
    )


def _verify_finished(summary: tuple, database: Path, identity: str, steps: int) -> None:
    row = dict(zip(_SUMMARY_COLUMNS, summary))
    if (row["status"] != "CASCADE_RUN_STATUS_IDLE" or row["not_fully_idle"] != 0
            or row["killed"] != 0 or row["app_data_dir"] != database.parent.parent.name):
        raise AntigravityCleanupBlocked("antigravity_cleanup_end_state_unverified")
    if any(row[name] for name in (
        "parent_conversation_id", "nesting_depth", "battle_id", "winning_conversation_id", "group_id",
    )):
        raise AntigravityCleanupBlocked("antigravity_cleanup_related_conversation")
    updated = datetime.fromisoformat(row["last_modified_time"])
    if (row["conversation_id"] != identity or row["step_count"] != steps or steps < 1
            or updated.tzinfo is None or (datetime.now(timezone.utc) - updated).total_seconds() < 60):
        raise AntigravityCleanupBlocked("antigravity_cleanup_end_state_unverified")


def _remove_summary_entry(data: bytes, identity: str) -> tuple[bytes, bytes | None]:
    """Splice one exact native map entry and preserve every other wire byte."""
    wanted = identity.encode("ascii")
    kept: list[bytes] = []
    selected = None
    offset = 0
    while offset < len(data):
        start = offset
        tag, offset = _varint(data, offset)
        size, offset = _varint(data, offset)
        end = offset + size
        if tag not in {10, 18} or end > len(data):
            raise AntigravityCleanupBlocked("antigravity_cleanup_proto_layout_unsupported")
        payload = data[offset:end]
        raw = data[start:end]
        offset = end
        if tag == 10:
            key = _one(_fields(payload), 1, 2)
            if not isinstance(key, bytes) or not _uuid(key.decode("ascii", errors="strict")):
                raise AntigravityCleanupBlocked("antigravity_cleanup_proto_identity_unverified")
            if key == wanted:
                if selected is not None:
                    raise AntigravityCleanupBlocked("antigravity_cleanup_proto_duplicate")
                selected = raw
                continue
        if wanted in payload:
            raise AntigravityCleanupBlocked("antigravity_cleanup_proto_related_conversation")
        kept.append(raw)
    return b"".join(kept), selected


def _local_proto(root: Path, identity: str) -> tuple[Path, bytes, bytes, bytes] | None:
    selected = None
    for name in _PROTOS:
        path = root / name
        if not _exists(path):
            continue
        if not _safe(path):
            raise AntigravityCleanupBlocked("antigravity_cleanup_proto_locator_unverified")
        before = path.read_bytes()
        after, entry = _remove_summary_entry(before, identity)
        if entry is not None:
            if selected is not None:
                raise AntigravityCleanupBlocked("antigravity_cleanup_proto_duplicate")
            selected = path, before, after, entry
    return selected


def _check_other_sources(root: Path, identity: str) -> None:
    token = identity.encode("ascii")
    for profile in _roots():
        if profile != root:
            other = _database_path(profile, identity)
            summary = profile / _SUMMARIES
            if any(_exists(path) for path in (
                other, *_sidecars(other), profile / "brain" / identity,
                profile / "annotations" / f"{identity}.pbtxt",
            )):
                raise AntigravityCleanupBlocked("antigravity_cleanup_other_profile_copy")
            if _exists(summary):
                with read_only_db(summary) as db:
                    if not _summary_absent(db, identity, ()):
                        raise AntigravityCleanupBlocked("antigravity_cleanup_other_profile_copy")
            for name in _PROTOS:
                proto = profile / name
                if _exists(proto) and (not _safe(proto) or token in proto.read_bytes()):
                    raise AntigravityCleanupBlocked("antigravity_cleanup_other_profile_copy")
        paths = [profile / "history.jsonl", profile / "conversations" / f"{identity}.pb"]
        paths.extend(profile.glob("*summaries_proto.pb.bak*"))
        for path in paths:
            if not _exists(path):
                continue
            if not _safe(path) or path.suffix == ".pb" or token in path.read_bytes():
                raise AntigravityCleanupBlocked("antigravity_cleanup_other_native_copy")
    roaming = os.environ.get("APPDATA")
    if roaming:
        user = Path(roaming) / "Antigravity" / "User"
        for path in (
            user / "globalStorage" / "state.vscdb", *user.glob("profiles/*/globalStorage/state.vscdb"),
            *user.glob("workspaceStorage/*/state.vscdb"),
        ):
            if not _exists(path):
                continue
            with read_only_db(path) as db:
                rows = db.execute(
                    "SELECT value FROM ItemTable WHERE key='antigravityUnifiedStateSync.trajectorySummaries'",
                ).fetchall()
            for (value,) in rows:
                if token in base64.b64decode(value, validate=True):
                    raise AntigravityCleanupBlocked("antigravity_cleanup_ide_summary_copy")


def _candidates(root: Path, identity: str) -> tuple[NativeCleanupAction, ...]:
    return (
        NativeCleanupAction("file", _database_path(root, identity), root),
        NativeCleanupAction("directory", root / "brain" / identity, root),
        NativeCleanupAction("file", root / "annotations" / f"{identity}.pbtxt", root),
    )


def _manifest_sha256(action: NativeCleanupAction, path: Path) -> str:
    if not _safe(path):
        raise AntigravityCleanupBlocked("antigravity_cleanup_companion_locator_unverified")
    if action.kind == "directory":
        for child in path.iterdir():
            if child.name == ".system_generated":
                continue
            if (child.name not in {".user_uploaded", "scratch"} or _is_link_or_reparse(child)
                    or not child.is_dir() or any(child.iterdir())):
                raise AntigravityCleanupBlocked("antigravity_cleanup_brain_artifact_ownership_unverified")
    return _digest([
        [item.relative_path, item.kind, item.size_bytes, item.mtime_ns, item.sha256]
        for item in _action_manifest(path, action.kind)
    ])


def _summary_sha256(summary: tuple, search: tuple[tuple, ...]) -> str:
    return _digest([[_encode_cell(value) for value in row] for row in (summary, *search)])


def _file_witnesses(actions: tuple[NativeCleanupAction, ...]) -> dict[str, str]:
    return {action.locator_sha256: _manifest_sha256(action, action.target) for action in actions}


def _capture(
    database: Path, identity: str, db: sqlite3.Connection,
) -> tuple[dict, tuple[NativeCleanupAction, ...], tuple[Path, bytes, bytes, bytes] | None]:
    root = _check_location(database, identity)
    _check_activity(database, identity)
    _check_other_sources(root, identity)
    actions = tuple(action for action in _candidates(root, identity) if _exists(action.target))
    if not actions or actions[0].target != database:
        raise AntigravityCleanupBlocked("antigravity_cleanup_source_missing")
    files = _file_witnesses(actions)
    with _read_main(database) as native:
        native_digest = sha256(sqlite_conversation_bytes(native, identity)).hexdigest()
        steps = native.execute("SELECT COUNT(*) FROM steps").fetchone()[0]
        if native.execute("SELECT 1 FROM steps WHERE status<>3 OR has_subtrajectory<>0 LIMIT 1").fetchone():
            raise AntigravityCleanupBlocked("antigravity_cleanup_steps_not_terminal")
    summary, search = _summary_records(db, identity)
    if summary is None:
        raise AntigravityCleanupBlocked("antigravity_cleanup_summary_missing")
    _verify_finished(summary, database, identity, steps)
    proto = _local_proto(root, identity)
    _check_activity(database, identity)
    return ({
        "native_sha256": native_digest,
        "summary_sha256": _summary_sha256(summary, search),
        "search_rowids": [row[0] for row in search],
        "file_sha256s": files,
        "proto_entry_sha256": sha256(proto[3]).hexdigest() if proto else None,
        "proto_name": proto[0].name if proto else None,
    }, actions, proto)


def capture_antigravity_cleanup_witness(path: Path, session_id: str) -> str | None:
    """Bind exact native and companion preimages while retaining readable unsupported sessions."""
    try:
        with read_only_db(path.parent.parent / _SUMMARIES) as db:
            details, _, _ = _capture(path, session_id, db)
        return _digest(details)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return None


def _check_frozen(source: TranscriptSource, details: dict) -> None:
    if (details.get("native_sha256") != source.metadata.get("native_input_sha256")
            or _digest(details) != source.metadata.get("antigravity_cleanup_sha256")):
        raise AntigravityCleanupBlocked("antigravity_cleanup_source_or_companions_changed")


def _reason(exc: Exception) -> str:
    return str(exc) if isinstance(exc, AntigravityCleanupBlocked) else "antigravity_cleanup_transaction_unavailable"


def plan_antigravity_sqlite_cleanup(source: TranscriptSource) -> AntigravityCleanupPlan:
    """Preview only. Recheck the frozen native records and their exact companions."""
    try:
        plan = _base_plan(source)
        if plan.database is None:
            return plan
        with read_only_db(plan.database.parent.parent / _SUMMARIES) as db:
            details, actions, proto = _capture(plan.database, source.session_id, db)
        _check_frozen(source, details)
        return replace(plan, actions=actions, summary_count=1, search_count=len(details["search_rowids"]),
                       proto_count=int(proto is not None))
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        locator = str(source.metadata.get("native_source_uri") or source.source_uri)
        return AntigravityCleanupPlan(source, sha256(locator.encode()).hexdigest(),
                                      retained=True, reason_codes=(_reason(exc),))


def _claim_path(target: Path, receipt_id: str) -> Path:
    if not _uuid(receipt_id):
        raise AntigravityCleanupBlocked("antigravity_cleanup_receipt_unverified")
    token = _digest([receipt_id, os.path.normcase(str(target))])[:32]
    return target.with_name(f".harness-mem-agy-claim-{token}")


def _check_witness(plan: AntigravityCleanupPlan, receipt_id: str, witness: dict) -> dict:
    details = witness.get("details")
    if (witness.get("version") != 1 or witness.get("receipt_id") != receipt_id
            or witness.get("locator_sha256") != plan.locator_sha256
            or witness.get("phase") not in {"prepared", "summary_committed", "verified"}
            or not isinstance(details, dict) or not _uuid(receipt_id)):
        raise AntigravityCleanupBlocked("antigravity_cleanup_receipt_unverified")
    _check_frozen(plan.source, details)
    return details


def _receipt_rowids(details: dict) -> tuple[int, ...]:
    rowids = details.get("search_rowids")
    if (not isinstance(rowids, list) or any(type(rowid) is not int or rowid < 1 for rowid in rowids)
            or rowids != sorted(set(rowids))):
        raise AntigravityCleanupBlocked("antigravity_cleanup_receipt_unverified")
    return tuple(rowids)


def _prepared_actions(
    root: Path, identity: str, receipt_id: str, details: dict, *, phase: str,
) -> tuple[NativeCleanupAction, ...]:
    expected = details["file_sha256s"]
    actions = []
    for action in _candidates(root, identity):
        claim = _claim_path(action.target, receipt_id)
        original, claimed = _exists(action.target), _exists(claim)
        digest = expected.get(action.locator_sha256)
        if digest is None:
            if original or claimed:
                raise AntigravityCleanupBlocked("antigravity_cleanup_companion_reappeared")
            continue
        if (original and claimed or (original and phase != "prepared")
                or (not original and not claimed and phase != "verified")):
            raise AntigravityCleanupBlocked("antigravity_cleanup_claim_conflict")
        if (original or claimed) and _manifest_sha256(action, claim if claimed else action.target) != digest:
            raise AntigravityCleanupBlocked("antigravity_cleanup_claim_changed")
        actions.append(action)
    if len(actions) != len(expected):
        raise AntigravityCleanupBlocked("antigravity_cleanup_receipt_unverified")
    return tuple(actions)


def _proto_paths(root: Path, receipt_id: str, details: dict) -> tuple[Path, Path] | None:
    name = details.get("proto_name")
    if name is None and details.get("proto_entry_sha256") is None:
        return None
    if name not in _PROTOS or not isinstance(details.get("proto_entry_sha256"), str):
        raise AntigravityCleanupBlocked("antigravity_cleanup_receipt_unverified")
    path = root / name
    return path, _claim_path(path, receipt_id)


def _verify_prepared_proto(root: Path, identity: str, details: dict) -> None:
    proto = _local_proto(root, identity)
    if ((proto[0].name if proto else None) != details.get("proto_name")
            or (sha256(proto[3]).hexdigest() if proto else None) != details.get("proto_entry_sha256")):
        raise AntigravityCleanupBlocked("antigravity_cleanup_proto_changed")


def _published_proto(root: Path, identity: str, receipt_id: str, details: dict) -> bool:
    paths = _proto_paths(root, receipt_id, details)
    if paths is not None and not paths[0].is_file():
        return False
    return _local_proto(root, identity) is None


def _publish_proto(root: Path, identity: str, receipt_id: str, details: dict) -> None:
    paths = _proto_paths(root, receipt_id, details)
    if paths is None:
        _verify_prepared_proto(root, identity, details)
        return
    path, claim = paths
    if not _exists(claim):
        _verify_prepared_proto(root, identity, details)
        os.rename(path, claim)
    if not _safe(claim):
        raise AntigravityCleanupBlocked("antigravity_cleanup_proto_locator_unverified")
    after, entry = _remove_summary_entry(claim.read_bytes(), identity)
    if entry is None or sha256(entry).hexdigest() != details["proto_entry_sha256"]:
        raise AntigravityCleanupBlocked("antigravity_cleanup_proto_changed")
    if not _exists(path):
        # Publish without clobbering a cache created by another process after
        # the original was claimed. The claim is retained until the receipt.
        fd, temp_name = tempfile.mkstemp(prefix=".harness-mem-agy-proto-", dir=root)
        staged = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(staged, path)
        finally:
            staged.unlink(missing_ok=True)
    if not _safe(path) or path.read_bytes() != after or not _published_proto(root, identity, receipt_id, details):
        raise AntigravityCleanupBlocked("antigravity_cleanup_proto_replacement_conflict")


def _target_files_absent(root: Path, identity: str, receipt_id: str) -> bool:
    database = _database_path(root, identity)
    _check_activity(database, identity)
    targets = [action.target for action in _candidates(root, identity)]
    return not any(_exists(path) for path in (
        *targets, *(_claim_path(path, receipt_id) for path in targets),
        *(_claim_path(root / name, receipt_id) for name in _PROTOS),
    ))


def antigravity_receipt_absence_verified(locator_sha256: str, session_id: str, *, witness: dict | None) -> bool:
    """Use the exact native locator and proven FTS row IDs when replaying a receipt."""
    try:
        if not _uuid(session_id) or not isinstance(witness, dict):
            return False
        receipt_id = witness.get("receipt_id")
        details = witness.get("details")
        if (witness.get("version") != 1 or not isinstance(receipt_id, str)
                or not _uuid(receipt_id) or witness.get("phase") != "verified"
                or witness.get("locator_sha256") != locator_sha256 or not isinstance(details, dict)):
            return False
        candidates = [root for root in _roots()
                      if sha256(_database_path(root, session_id).as_uri().encode()).hexdigest() == locator_sha256]
        if len(candidates) != 1:
            return False
        root = candidates[0]
        _check_location(_database_path(root, session_id), session_id)
        _check_other_sources(root, session_id)
        if not _target_files_absent(root, session_id, receipt_id):
            return False
        if not _published_proto(root, session_id, receipt_id, details):
            return False
        with read_only_db(root / _SUMMARIES) as db:
            return _summary_absent(db, session_id, _receipt_rowids(details))
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return False


def antigravity_source_absence_verified(source: TranscriptSource, *, witness: dict | None) -> bool:
    try:
        if not isinstance(witness, dict) or not isinstance(receipt_id := witness.get("receipt_id"), str):
            return False
        plan = _base_plan(source)
        _check_witness(plan, receipt_id, witness)
        return antigravity_receipt_absence_verified(plan.locator_sha256, source.session_id, witness=witness)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return False


def _verify_phase(
    plan: AntigravityCleanupPlan, receipt_id: str, witness: dict, db: sqlite3.Connection,
) -> tuple[NativeCleanupAction, ...]:
    details = _check_witness(plan, receipt_id, witness)
    database, identity = plan.database, plan.source.session_id
    assert database is not None
    root = _check_location(database, identity)
    _check_activity(database, identity)
    _check_other_sources(root, identity)
    phase = witness["phase"]
    actions = _prepared_actions(root, identity, receipt_id, details, phase=phase)
    if phase == "prepared":
        summary, search = _summary_records(db, identity)
        if summary is None:
            # Absence alone cannot tell whether a previous commit was ours.
            raise AntigravityCleanupBlocked("antigravity_cleanup_commit_unverified")
        if (_summary_sha256(summary, search) != details["summary_sha256"]
                or tuple(row[0] for row in search) != _receipt_rowids(details)):
            raise AntigravityCleanupBlocked("antigravity_cleanup_summary_changed")
        _verify_prepared_proto(root, identity, details)
    elif not _summary_absent(db, identity, _receipt_rowids(details)):
        raise AntigravityCleanupBlocked("antigravity_cleanup_summary_reappeared")
    elif phase == "verified" and not _published_proto(root, identity, receipt_id, details):
        raise AntigravityCleanupBlocked("antigravity_cleanup_proto_reappeared")
    return actions


def plan_antigravity_sqlite_recovery(
    source: TranscriptSource, *, data_dir: Path, receipt_id: str, witness: dict,
) -> AntigravityCleanupPlan:
    """Check the prior receipt and the exact remaining claims without a write."""
    del data_dir
    plan = _base_plan(source)
    if plan.database is None:
        return plan
    with read_only_db(plan.database.parent.parent / _SUMMARIES) as db:
        actions = _verify_phase(plan, receipt_id, witness, db)
    details = witness["details"]
    return replace(plan, actions=actions, summary_count=1, search_count=len(_receipt_rowids(details)),
                   proto_count=int(details.get("proto_name") is not None))


def _claim_files(
    actions: tuple[NativeCleanupAction, ...], receipt_id: str, details: dict,
) -> None:
    for action in actions:
        claim = _claim_path(action.target, receipt_id)
        if not _exists(claim):
            os.rename(action.target, claim)
        if _exists(action.target) or _manifest_sha256(action, claim) != details["file_sha256s"][action.locator_sha256]:
            raise AntigravityCleanupBlocked("antigravity_cleanup_claim_changed")


def _delete_summary(db: sqlite3.Connection, identity: str, rowids: tuple[int, ...]) -> None:
    for rowid in rowids:
        removed = db.execute(
            "DELETE FROM main.conversations_fts WHERE rowid=? AND conversation_id COLLATE BINARY=?",
            (rowid, identity),
        )
        if removed.rowcount != 1:
            raise AntigravityCleanupBlocked("antigravity_cleanup_search_delete_unverified")
    removed = db.execute("DELETE FROM main.conversation_summaries WHERE conversation_id COLLATE BINARY=?", (identity,))
    if removed.rowcount != 1 or not _summary_absent(db, identity, rowids):
        raise AntigravityCleanupBlocked("antigravity_cleanup_summary_delete_unverified")


def _restore_files(
    root: Path, identity: str, receipt_id: str, details: dict, actions: tuple[NativeCleanupAction, ...],
) -> bool:
    try:
        with read_only_db(root / _SUMMARIES) as db:
            summary, search = _summary_records(db, identity)
        if summary is None or _summary_sha256(summary, search) != details["summary_sha256"]:
            return False
        for action in reversed(actions):
            claim = _claim_path(action.target, receipt_id)
            if not _exists(claim):
                continue
            if _exists(action.target) or _manifest_sha256(action, claim) != details["file_sha256s"][action.locator_sha256]:
                return False
            os.rename(claim, action.target)
        return True
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return False


def _unlink_claims(
    root: Path, identity: str, receipt_id: str, details: dict, actions: tuple[NativeCleanupAction, ...],
) -> None:
    for action in reversed(actions):
        claim = _claim_path(action.target, receipt_id)
        if not _exists(claim):
            continue
        if _exists(action.target) or _manifest_sha256(action, claim) != details["file_sha256s"][action.locator_sha256]:
            raise AntigravityCleanupBlocked("antigravity_cleanup_claim_changed")
        if action.kind == "directory":
            _remove_directory_tree(claim)
        else:
            claim.unlink()
    paths = _proto_paths(root, receipt_id, details)
    if paths is not None and _exists(paths[1]):
        path, claim = paths
        if not _safe(claim):
            raise AntigravityCleanupBlocked("antigravity_cleanup_proto_locator_unverified")
        after, entry = _remove_summary_entry(claim.read_bytes(), identity)
        if (entry is None or sha256(entry).hexdigest() != details["proto_entry_sha256"]
                or not _safe(path) or path.read_bytes() != after):
            raise AntigravityCleanupBlocked("antigravity_cleanup_proto_replacement_conflict")
        claim.unlink()


def apply_antigravity_sqlite_cleanup(
    plan: AntigravityCleanupPlan, *, data_dir: Path, receipt_id: str,
    record_witness: Callable[[dict], None], witness: dict | None = None,
) -> dict:
    """Delete selected SQLite rows, then publish an exact protobuf splice."""
    del data_dir
    if plan.database is None or plan.retained or not plan.supported or not plan.actions:
        return {"status": "retained", "reason_codes": ["antigravity_cleanup_plan_invalid"]}
    identity = plan.source.session_id
    actions: tuple[NativeCleanupAction, ...] = ()
    if not _uuid(receipt_id):
        return {"status": "retained", "reason_codes": ["antigravity_cleanup_receipt_unverified"]}
    try:
        root = _check_location(plan.database, identity)
        with _write_summary(root / _SUMMARIES) as db:
            if witness is None:
                details, _, _ = _capture(plan.database, identity, db)
                _check_frozen(plan.source, details)
                prepared = {"version": 1, "phase": "prepared", "locator_sha256": plan.locator_sha256,
                            "receipt_id": receipt_id, "details": details}
                record_witness(prepared)
                witness = prepared
            actions = _verify_phase(plan, receipt_id, witness, db)
            details = _check_witness(plan, receipt_id, witness)
            if witness["phase"] == "prepared":
                _claim_files(actions, receipt_id, details)
                _check_activity(plan.database, identity)
                _check_other_sources(root, identity)
                _verify_prepared_proto(root, identity, details)
                _delete_summary(db, identity, _receipt_rowids(details))
                db.commit()
                committed = {**witness, "phase": "summary_committed"}
                record_witness(committed)
                witness = committed
        # Keep the summary writer lock during the protobuf and claim stages.
        # If the native application recreates a summary between transactions,
        # the receipt stops rather than clearing the new version.
        with _write_summary(root / _SUMMARIES) as db:
            actions = _verify_phase(plan, receipt_id, witness, db)
            if witness["phase"] == "summary_committed":
                _publish_proto(root, identity, receipt_id, details)
                verified = {**witness, "phase": "verified"}
                record_witness(verified)
                witness = verified
            _unlink_claims(root, identity, receipt_id, details, actions)
        if not antigravity_receipt_absence_verified(plan.locator_sha256, identity, witness=witness):
            raise AntigravityCleanupBlocked("antigravity_cleanup_absence_unverified")
        return {"status": "deleted", "reason_codes": ["antigravity_native_conversation_deleted"],
                "counts": plan.to_preview()["counts"]}
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        reason = _reason(exc)
        if actions and witness is not None and witness["phase"] == "prepared":
            if _restore_files(plan.database.parent.parent, identity, receipt_id, witness["details"], actions):
                reason = "antigravity_cleanup_preimage_restored"
        return {"status": "partial_failure" if witness is not None else "retained", "reason_codes": [reason]}
