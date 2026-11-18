"""Antigravity native SQLite history admission and author boundaries."""

from contextlib import closing
from hashlib import sha256
import json
import sqlite3

import pytest

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.antigravity.sqlite_history import (
    antigravity_sqlite_export_messages,
    read_sqlite_conversation,
    render_antigravity_sqlite_messages,
)
from harness_mem.mcp.distill_projection import _parse_exchanges


_ID = "3c3301f2-d22d-4fba-bbf8-793913ce2f9a"
_SCHEMA = """
    PRAGMA user_version=1;
    CREATE TABLE trajectory_meta (trajectory_id TEXT PRIMARY KEY, cascade_id TEXT, trajectory_type INTEGER, source INTEGER);
    CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_type INTEGER, status INTEGER, has_subtrajectory INTEGER,
        metadata BLOB, error_details BLOB, permissions BLOB, task_details BLOB, render_info BLOB, step_payload BLOB,
        step_format INTEGER);
    CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER);
    CREATE TABLE executor_metadata (idx INTEGER PRIMARY KEY, data BLOB);
    CREATE TABLE parent_references (idx INTEGER PRIMARY KEY, data BLOB);
    CREATE TABLE trajectory_metadata_blob (id TEXT PRIMARY KEY, data BLOB);
    CREATE TABLE battle_mode_infos (idx INTEGER PRIMARY KEY, data BLOB);
"""


def _varint(number):
    if number < 128:
        return bytes([number])
    return bytes([(number & 127) | 128]) + _varint(number >> 7)


def _field(number, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _step(index, kind, tag, data, source):
    metadata = _field(3, source)
    payload = _field(1, kind) + _field(4, 3) + _field(5, metadata) + _field(tag, data)
    return (index, kind, 3, 0, metadata, None, None, None, None, payload, 0)


@pytest.fixture
def native_db(tmp_path):
    root = tmp_path / "host"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = root / "conversations" / f"{_ID}.db"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(_SCHEMA)
        db.execute("INSERT INTO trajectory_meta VALUES (?, ?, 4, 1)", ("trajectory", _ID))
        db.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)",
                   (_field(6, _ID) + _field(1, _field(1, workspace.as_uri())),))
        db.executemany("INSERT INTO steps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            _step(0, 14, 19, _field(1, "Injected context") + _field(2, "Please preserve the original"), 4),
            _step(1, 132, 140, _field(2, _field(1, "Read-only result")), 3),
            _step(2, 15, 20, _field(1, "Done.\n\nUser: quoted, never a new author") + _field(3, "Private model thought"), 3),
        ])
        db.execute("INSERT INTO executor_metadata VALUES (0, ?)", (b"opaque\x00native",))
    return path, workspace


def test_sqlite_full_row_binding_and_safe_projection(native_db):
    path, workspace = native_db
    exported = read_sqlite_conversation(path, _ID)
    assert exported["project_roots"] == [workspace.as_posix()]
    assert exported["readability"] == "readable" and exported["step_count"] == 3
    assert exported["native_input_digest"] == sha256(exported["raw_bytes"]).hexdigest()
    assert json.loads(exported["raw_bytes"])["tables"]["executor_metadata"]["rows"] == [
        [0, {"$sqlite_blob_base64": "b3BhcXVlAG5hdGl2ZQ=="}],
    ]
    source_text = exported["source_text"]
    assert "Private model thought" not in source_text and "Injected context" not in source_text
    messages = antigravity_sqlite_export_messages(source_text.encode(), _ID)
    assert [m["role"] for m in messages] == ["user", "tool", "assistant"]
    assert exported["observed_rendering"] == render_antigravity_sqlite_messages(messages)
    assert "\n\n> User: quoted" in exported["observed_rendering"]
    _, exchanges, _ = _parse_exchanges(exported["observed_rendering"])
    assert len(exchanges) == 1
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE executor_metadata SET data=?", (b"opaque revision change",))
    changed = read_sqlite_conversation(path, _ID)
    assert changed["native_input_digest"] != exported["native_input_digest"]
    assert changed["observed_rendering"] == exported["observed_rendering"]


def test_sqlite_adapter_precedes_same_profile_mirror(native_db):
    path, workspace = native_db
    root = path.parent.parent
    mirror = root / "brain" / _ID / ".system_generated" / "logs" / "transcript_full.jsonl"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(json.dumps({"type": "USER_INPUT", "content": "Divergent display mirror", "cwd": str(workspace)}) + "\n",
                      encoding="utf-8")
    adapter = AntigravityAdapter(None, brain_dir=root / "brain", project_root=workspace)
    records = adapter.list_session_metadata()
    assert [(r["session_id"], r["path"], r["source_kind"]) for r in records] == [(_ID, path, "antigravity-sqlite")]
    exported = adapter.read_session_source(path, _ID)
    assert exported["authored_user_texts"] == ["Please preserve the original"]
    assert "antigravity_cleanup_sha256" not in exported
    assert adapter.session_to_observation(path, _ID).raw_content == exported["observed_rendering"]


@pytest.mark.parametrize("invalid", ["spoofed", "truncated", "unknown_step", "gap", "wrong_identity"])
def test_sqlite_native_uncertainty_never_becomes_complete(native_db, invalid):
    path, _ = native_db
    with closing(sqlite3.connect(path)) as db, db:
        if invalid == "spoofed":
            db.execute("DELETE FROM steps WHERE idx=0")
            db.execute("INSERT INTO steps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       _step(0, 14, 19, _field(2, "Untrusted role"), 3))
        elif invalid == "truncated":
            db.execute("UPDATE steps SET step_payload = substr(step_payload, 1, length(step_payload)-1) WHERE idx=0")
        elif invalid == "unknown_step":
            db.execute("UPDATE steps SET step_type = 999 WHERE idx=0")
        elif invalid == "gap":
            db.execute("DELETE FROM steps WHERE idx=1")
        else:
            db.execute("UPDATE trajectory_meta SET cascade_id = 'foreign'")
    with pytest.raises(ValueError):
        read_sqlite_conversation(path, _ID)
