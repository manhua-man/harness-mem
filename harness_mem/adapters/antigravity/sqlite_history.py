"""Read Antigravity's version-one conversation SQLite format.

The stable row export includes every declared table and BLOB. The separate
conversation projection decodes known fields from the protobuf Step and
CortexTrajectoryMetadata messages, without turning tools or system steps into
user messages. Layout confirmed against native stores and txcript's field map
(https://github.com/skillsynchq/txcript/blob/main/docs/formats/antigravity.md).
"""

from __future__ import annotations

import base64
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit


SQLITE_SOURCE_KIND = "antigravity-sqlite"
SQLITE_PROJECTION_FORMAT = "harness-mem-antigravity-sqlite-v1"
_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_STEP_PAYLOAD_FIELDS = {5: 10, 7: 13, 8: 14, 9: 15, 14: 19, 15: 20, 21: 28,
                        23: 30, 38: 47, 90: 103, 98: 111, 101: 114, 132: 140}
_HOST_CONTEXT_STEPS = {23: "checkpoint", 90: "ephemeral", 98: "history", 101: "system"}
_TABLES = {
    "trajectory_meta": ("trajectory_id", "cascade_id", "trajectory_type", "source"),
    "steps": ("idx", "step_type", "status", "has_subtrajectory", "metadata", "error_details",
              "permissions", "task_details", "render_info", "step_payload", "step_format"),
    "gen_metadata": ("idx", "data", "size"),
    "executor_metadata": ("idx", "data"),
    "parent_references": ("idx", "data"),
    "trajectory_metadata_blob": ("id", "data"),
    "battle_mode_infos": ("idx", "data"),
}
_ROLE_BY_TYPE = {"USER_INPUT": "user", "PLANNER_RESPONSE": "assistant", "TOOL_RESULT": "tool"}
_BOUNDARY_LINE = re.compile(r"(?im)^(?=[ \t]*(?:(?:user|assistant|tool|system):|#{1,6}[ \t]+turn\b))")


def is_conversation_db(path: Path) -> bool:
    return path.parent.name == "conversations" and path.suffix == ".db" and bool(_ID.fullmatch(path.stem))


@contextmanager
def read_only_db(path: Path) -> Iterator[sqlite3.Connection]:
    if path.resolve() != path.absolute():
        raise ValueError("Antigravity SQLite location is a link")
    sidecars = [path.with_name(path.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
    before = path.stat()
    idle = is_conversation_db(path) and not any(candidate.exists() for candidate in sidecars)
    uri = path.absolute().as_uri() + ("?mode=ro&immutable=1" if idle else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        yield db
    if idle:
        after = path.stat()
        if ((before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns)
                or any(candidate.exists() for candidate in sidecars)):
            raise ValueError("Antigravity SQLite conversation changed during idle read")


def _varint(buf: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(buf):
            break
        byte = buf[offset]
        offset += 1
        if shift == 63 and byte > 1:
            break
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("invalid Antigravity protobuf varint")


_Fields = dict[int, list[tuple[int, Any]]]


def _fields(buf: bytes) -> _Fields:
    if not isinstance(buf, bytes):
        raise ValueError("Antigravity protobuf value is not a BLOB")
    out: _Fields = {}
    offset = 0
    while offset < len(buf):
        tag, offset = _varint(buf, offset)
        number, wire = tag >> 3, tag & 7
        if not 0 < number < (1 << 29) or wire not in (0, 1, 2, 5):
            raise ValueError("unknown Antigravity protobuf field encoding")
        value: int | bytes
        if wire == 0:
            value, offset = _varint(buf, offset)
        else:
            if wire == 2:
                size, offset = _varint(buf, offset)
            else:
                size = 8 if wire == 1 else 4
            end = offset + size
            if end > len(buf):
                raise ValueError("truncated Antigravity protobuf field")
            value = buf[offset:end]
            offset = end
        out.setdefault(number, []).append((wire, value))
    return out


def _one(fields: _Fields, number: int, wire: int) -> Any:
    values = fields.get(number, [])
    if not values:
        return None
    if len(values) != 1 or values[0][0] != wire:
        raise ValueError("ambiguous Antigravity protobuf field")
    return values[0][1]


def _text(fields: _Fields, number: int) -> str:
    return (_one(fields, number, 2) or b"").decode("utf-8", errors="strict")


def _sub(fields: _Fields, number: int) -> _Fields:
    return _fields(_one(fields, number, 2) or b"")


def _many(fields: _Fields, number: int) -> Iterator[_Fields]:
    for wire, value in fields.get(number, []):
        if wire != 2:
            raise ValueError("invalid Antigravity protobuf list")
        yield _fields(value)


def _workspace_path(value: str) -> str:
    uri = urlsplit(value)
    if uri.scheme != "file" or uri.netloc not in {"", "localhost"} or uri.query or uri.fragment:
        raise ValueError("unsupported Antigravity workspace URI")
    path = unquote(uri.path, errors="strict")
    if re.match(r"^/[A-Za-z]:[\\/]", path):
        path = path[1:]
    if not path or "\x00" in path or not (path.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", path)):
        raise ValueError("invalid Antigravity workspace URI")
    return path


def _trajectory_roots(blob: bytes, session_id: str) -> list[str]:
    main = _fields(blob)
    identity = _text(main, 6)
    if identity and identity != session_id:
        raise ValueError("Antigravity trajectory metadata identity differs")
    uris = [_text(workspace, 1) for workspace in _many(main, 1)]
    uris.append(_text(main, 7))
    return list(dict.fromkeys(_workspace_path(uri) for uri in uris if uri))


def read_summary_roots(path: Path, session_id: str | None = None) -> dict[str, list[str]]:
    """Read only workspace binding for exact summary rows in the source's profile."""
    if not path.is_file():
        return {}
    where = "" if session_id is None else " WHERE conversation_id COLLATE BINARY = ?"
    with read_only_db(path) as db:
        rows = db.execute("SELECT conversation_id, workspace_uris FROM conversation_summaries" + where,
                          () if session_id is None else (session_id,)).fetchall()
    roots = {}
    for identity, raw in rows:
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            continue
        try:
            uris = json.loads(raw)
            if not isinstance(uris, list) or not all(isinstance(value, str) for value in uris):
                raise ValueError("unsupported Antigravity workspace list")
            roots[identity] = list(dict.fromkeys(_workspace_path(uri) for uri in uris))
        except (ValueError, TypeError):
            # Malformed metadata must never assign a workspace to its session.
            roots[identity] = []
    return roots


def _validate_schema(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone() != (1,):
        raise ValueError("unsupported Antigravity SQLite conversation version")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != set(_TABLES):
        raise ValueError("unsupported Antigravity SQLite conversation tables")
    for table, columns in _TABLES.items():
        info = db.execute(f'PRAGMA table_info("{table}")').fetchall()
        if tuple(row[1] for row in info) != columns or not info or info[0][5] != 1:
            raise ValueError("unsupported Antigravity SQLite conversation columns")


def read_conversation_roots(path: Path, session_id: str) -> list[str]:
    """Discover owners without reading or rendering conversation bodies."""
    _validate_locator(path, session_id)
    with read_only_db(path) as db:
        if db.execute("PRAGMA user_version").fetchone() != (1,):
            raise ValueError("unsupported Antigravity SQLite conversation version")
        _verify_identity(db.execute("SELECT * FROM trajectory_meta").fetchall(), session_id)
        return _db_trajectory_roots(db, session_id)


def _db_trajectory_roots(db: sqlite3.Connection, session_id: str) -> list[str]:
    metadata = db.execute("SELECT data FROM trajectory_metadata_blob WHERE id COLLATE BINARY = 'main'").fetchall()
    if len(metadata) > 1:
        raise ValueError("ambiguous Antigravity trajectory metadata")
    return _trajectory_roots(metadata[0][0], session_id) if metadata else []


def _validate_locator(path: Path, session_id: str) -> None:
    if not is_conversation_db(path) or path.stem != session_id:
        raise ValueError("Antigravity SQLite conversation locator does not match session")


def _verify_identity(rows: list[tuple], session_id: str) -> None:
    if len(rows) != 1 or len(rows[0]) != 4 or rows[0][1] != session_id or rows[0][2] != 4:
        raise ValueError("Antigravity SQLite conversation identity is unverified")


def _read_rows(db: sqlite3.Connection, session_id: str) -> dict[str, list[tuple]]:
    _validate_schema(db)
    rows = {table: db.execute(f'SELECT * FROM "{table}" ORDER BY 1 COLLATE BINARY').fetchall()
            for table in _TABLES}
    _verify_identity(rows["trajectory_meta"], session_id)
    return rows


def _encode_cell(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$sqlite_blob_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float):
        return {"$sqlite_float": value.hex()}
    return value


def _row_export(rows: dict[str, list[tuple]], session_id: str) -> bytes:
    envelope = {"format": "harness-mem-antigravity-sqlite-rows-v1", "session_id": session_id,
                "tables": {table: {"columns": _TABLES[table],
                                   "rows": [[_encode_cell(value) for value in row] for row in values]}
                           for table, values in rows.items()}}
    return json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def sqlite_conversation_bytes(db: sqlite3.Connection, session_id: str) -> bytes:
    """Canonical complete logical rows in a caller's pinned read transaction."""
    return _row_export(_read_rows(db, session_id), session_id)


def _tool_call(fields: _Fields) -> dict[str, str]:
    return {"id": _text(fields, 1), "name": _text(fields, 2), "arguments": _text(fields, 3)}


def _tool_result(kind: int, body: _Fields) -> str:
    if kind == 132:  # CortexStepGeneric.result.result
        return _text(_sub(body, 2), 1)
    if kind == 8:  # CortexStepViewFile content / raw_content
        return _text(body, 4) or _text(body, 9)
    if kind == 21:  # CortexStepRunCommand combined stdout/stderr
        return _text(_sub(body, 21), 1) or _text(body, 4)
    if kind in {7, 38}:  # Grep output/error or MCP result_string
        return (_text(body, 5) if kind == 7 else "") or _text(body, 3)
    if kind == 9:  # CortexStepListDirectory results
        return "\n".join(_text(entry, 1) for entry in _many(body, 3))
    if kind == 5:  # CortexStepCodeAction exact affected URI (not implementation claim)
        return _text(_sub(_sub(body, 2), 1), 8)
    return ""


def _project_step(row: tuple) -> dict[str, Any]:
    index, kind, status, nested, metadata, error, _, _, _, payload, step_format = row
    if kind not in _STEP_PAYLOAD_FIELDS or step_format != 0 or nested:
        raise ValueError("unsupported Antigravity trajectory step")
    envelope = _fields(payload)
    if _one(envelope, 1, 0) != kind or _one(envelope, 4, 0) != status:
        raise ValueError("Antigravity trajectory step header differs")
    envelope_metadata = _one(envelope, 5, 2)
    if envelope_metadata is None or (metadata and metadata != envelope_metadata):
        raise ValueError("Antigravity trajectory step metadata differs")
    meta = _fields(envelope_metadata)
    body = _sub(envelope, _STEP_PAYLOAD_FIELDS[kind])
    record = {"step_index": index, "step_type": kind, "status": status}
    if kind == 14:
        if _one(meta, 3, 0) != 4 or status != 3:
            raise ValueError("Antigravity user step is not explicit and complete")
        content = _text(body, 2)
        # The query can contain host-injected instructions. Only clean explicit
        # response fields are permitted author evidence. An image-bearing turn
        # needs a separate readable projection before cleanup can be justified.
        if not content.strip() or body.get(5):
            raise ValueError("Antigravity user step has no supported explicit content")
        return {**record, "type": "USER_INPUT", "content": content}
    if kind == 15:
        calls = [_tool_call(call) for call in _many(body, 7)]
        return {**record, "type": "PLANNER_RESPONSE", "content": _text(body, 1), "tool_calls": calls}
    if kind in _HOST_CONTEXT_STEPS:
        return {**record, "type": "GENERIC", "native_context": _HOST_CONTEXT_STEPS[kind]}
    err = _fields(error or b"")
    content = _text(err, 9) or _text(err, 1) or _text(err, 2) or _tool_result(kind, body)
    return {**record, "type": "TOOL_RESULT", "content": content, "call": _tool_call(_sub(meta, 4))}


def antigravity_sqlite_export_messages(raw: bytes, session_id: str) -> list[dict[str, str]]:
    """Rebuild authorship only from a frozen, validated SQLite projection."""
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    if (not records or not isinstance(records[0], dict)
            or records[0].get("format") != SQLITE_PROJECTION_FORMAT
            or records[0].get("session_id") != session_id):
        raise ValueError("invalid Antigravity SQLite conversation projection")
    messages: list[dict[str, str]] = []
    for index, record in enumerate(records[1:]):
        if not isinstance(record, dict) or record.get("step_index") != index:
            raise ValueError("Antigravity SQLite projection step order differs")
        kind = record.get("type")
        if kind == "GENERIC":
            continue
        content = record.get("content")
        if kind not in _ROLE_BY_TYPE or not isinstance(content, str):
            raise ValueError("invalid Antigravity SQLite message projection")
        if content.strip():
            messages.append({"role": _ROLE_BY_TYPE[kind], "content": content})
    return messages


def render_antigravity_sqlite_messages(messages: list[dict[str, str]]) -> str:
    # An embedded role or turn heading stays a quoted literal inside its body.
    return "\n\n".join(f"{row['role'].title()}: {_BOUNDARY_LINE.sub('> ', row['content'])}" for row in messages)


def read_sqlite_conversation(path: Path, session_id: str) -> dict[str, Any]:
    """Pin all native rows, then project the supported ordered steps."""
    _validate_locator(path, session_id)
    with read_only_db(path) as db:
        rows = _read_rows(db, session_id)
        roots = _db_trajectory_roots(db, session_id)
    if rows["parent_references"] or rows["battle_mode_infos"]:
        raise ValueError("Antigravity SQLite conversation uses additional trajectories")
    steps = rows["steps"]
    if any(row[0] != index for index, row in enumerate(steps)):
        raise ValueError("Antigravity SQLite trajectory is incomplete")
    records = [_project_step(row) for row in steps]
    raw = _row_export(rows, session_id)
    digest = sha256(raw).hexdigest()
    header = {"format": SQLITE_PROJECTION_FORMAT, "session_id": session_id, "native_sha256": digest}
    # ASCII escapes all embedded line separators, so JSONL stays round-trippable.
    text = "".join(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
                   for record in [header, *records])
    messages = antigravity_sqlite_export_messages(text.encode("utf-8"), session_id)
    users = [row["content"] for row in messages if row["role"] == "user"]
    return {"source_uri": path.absolute().as_uri(), "source_text": text, "raw_bytes": raw,
            "native_input_digest": digest, "project_roots": roots, "authored_user_texts": users,
            "observed_rendering": render_antigravity_sqlite_messages(messages),
            "readability": "readable" if users else "empty_draft", "step_count": len(steps)}
