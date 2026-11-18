from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from harness_mem.adapters.antigravity import sqlite_cleanup as cleanup
from harness_mem.adapters.antigravity import sqlite_history
from harness_mem.core.schemas.transcript import TranscriptSource


def _field(number, value):
    assert number < 16 and len(value) < 128
    return bytes((number * 8 + 2, len(value))) + value


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    profile = tmp_path / ".gemini" / "antigravity"
    identity, neighbor = str(uuid4()), str(uuid4())
    native_db = profile / "conversations" / f"{identity}.db"
    native_db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(native_db)) as db, db:
        db.execute("PRAGMA user_version=1")
        for name, columns in sqlite_history._TABLES.items():
            ddl = ", ".join([f"{columns[0]} PRIMARY KEY", *columns[1:]])
            db.execute(f"CREATE TABLE {name} ({ddl})")
        db.execute("INSERT INTO trajectory_meta VALUES ('native-trajectory', ?, 4, 1)", (identity,))
        db.execute("INSERT INTO steps (idx,step_type,status,has_subtrajectory) VALUES (0,14,3,0)")

    summary_db = profile / "conversation_summaries.db"
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with closing(sqlite3.connect(summary_db)) as db, db:
        db.execute("PRAGMA user_version=3")
        columns = ", ".join([f"{cleanup._SUMMARY_COLUMNS[0]} TEXT PRIMARY KEY", *cleanup._SUMMARY_COLUMNS[1:]])
        db.execute(f"CREATE TABLE conversation_summaries ({columns})")
        db.execute("CREATE TABLE search_schema_version (version INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO search_schema_version VALUES (3)")
        db.execute(cleanup._FTS_SQL)
        for rowid, session_id in enumerate((identity, neighbor), start=1):
            db.execute(
                "INSERT INTO conversation_summaries "
                "(conversation_id,status,not_fully_idle,killed,app_data_dir,last_modified_time,step_count) "
                "VALUES (?, 'CASCADE_RUN_STATUS_IDLE', 0, 0, 'antigravity', ?, 1)",
                (session_id, past),
            )
            db.execute("INSERT INTO conversations_fts (rowid,conversation_id,user_body) VALUES (?, ?, 'body')",
                       (rowid, session_id))

    target = _field(1, _field(1, identity.encode()) + _field(2, b"selected"))
    other = _field(1, _field(1, neighbor.encode()) + _field(2, b"neighbor")) + _field(2, b"metadata")
    proto = profile / "agyhub_summaries_proto.pb"
    proto.write_bytes(target + other)
    brain = profile / "brain" / identity / ".system_generated"
    brain.mkdir(parents=True)
    (brain / "log.jsonl").write_text("session-owned", encoding="utf-8")
    annotation = profile / "annotations" / f"{identity}.pbtxt"
    annotation.parent.mkdir()
    annotation.write_text("session-owned", encoding="utf-8")

    with cleanup._read_main(native_db) as db:
        raw = sqlite_history.sqlite_conversation_bytes(db, identity)
    digest = sha256(raw).hexdigest()
    witness = cleanup.capture_antigravity_cleanup_witness(native_db, identity)
    assert witness
    source = TranscriptSource(
        id="source", project_name="acceptance", project_root=str(tmp_path), client="antigravity",
        session_id=identity, source_kind="antigravity-sqlite", source_uri=native_db.as_uri(),
        source_revision=f"sha256:{digest}", raw_sha256=digest, normalized_sha256=digest, coverage="complete",
        metadata={"native_input_sha256": digest, "antigravity_cleanup_sha256": witness},
    )
    return source, native_db, summary_db, proto, other, neighbor


def _selected_rows(summary_db, identity):
    with cleanup.read_only_db(summary_db) as db:
        return cleanup._summary_records(db, identity)


@pytest.mark.parametrize("fault", ["none", "rollback", "proto_write", "unacknowledged_commit"])
def test_native_cleanup_reopens_and_recovers_exact_selection(tmp_path, monkeypatch, native, fault):
    source, native_db, summary_db, proto, other_proto, neighbor = native
    receipt_id = str(uuid4())
    original_proto = proto.read_bytes()
    selected = _selected_rows(summary_db, source.session_id)
    untouched = _selected_rows(summary_db, neighbor)
    plan = cleanup.plan_antigravity_sqlite_cleanup(source)
    assert plan.to_preview()["counts"] == {
        "planned": 6, "native_files_or_directories": 3, "summary_rows": 1, "search_rows": 1,
        "protobuf_entries": 1,
    }
    assert native_db.exists() and proto.read_bytes() == original_proto
    receipts = []

    def fail(*_args):
        raise OSError("injected")

    def record(witness):
        if fault == "unacknowledged_commit" and witness["phase"] == "summary_committed":
            fail()
        receipts.append(witness)

    with monkeypatch.context() as context:
        if fault == "rollback":
            context.setattr(cleanup, "_delete_summary", fail)
        elif fault == "proto_write":
            context.setattr(cleanup.os, "link", fail)
        result = cleanup.apply_antigravity_sqlite_cleanup(
            plan, data_dir=tmp_path, receipt_id=receipt_id, record_witness=record,
        )

    if fault == "unacknowledged_commit":
        assert result["status"] == "partial_failure" and not native_db.exists()
        assert cleanup._claim_path(native_db, receipt_id).exists()
        assert proto.read_bytes() == original_proto and receipts[-1]["phase"] == "prepared"
        with pytest.raises(cleanup.AntigravityCleanupBlocked, match="commit_unverified"):
            cleanup.plan_antigravity_sqlite_recovery(
                source, data_dir=tmp_path, receipt_id=receipt_id, witness=receipts[-1],
            )
        return
    if fault != "none":
        assert result["status"] == "partial_failure"
        if fault == "rollback":
            assert result["reason_codes"] == ["antigravity_cleanup_preimage_restored"]
            assert native_db.exists() and proto.read_bytes() == original_proto
            assert _selected_rows(summary_db, source.session_id) == selected
        else:
            assert receipts[-1]["phase"] == "summary_committed"
            assert not proto.exists() and cleanup._claim_path(proto, receipt_id).exists()
        recovered = cleanup.plan_antigravity_sqlite_recovery(
            source, data_dir=tmp_path, receipt_id=receipt_id, witness=receipts[-1],
        )
        result = cleanup.apply_antigravity_sqlite_cleanup(
            recovered, data_dir=tmp_path, receipt_id=receipt_id, record_witness=record, witness=receipts[-1],
        )

    assert result["status"] == "deleted", result
    assert not any(action.target.exists() for action in plan.actions)
    assert proto.read_bytes() == other_proto
    assert _selected_rows(summary_db, neighbor) == untouched
    assert cleanup.antigravity_source_absence_verified(source, witness=receipts[-1])
    with closing(sqlite3.connect(summary_db)) as db, db:
        db.execute("INSERT INTO conversations_fts(rowid,conversation_id,user_body) VALUES (1, ?, 'new owner')",
                   (neighbor,))
    assert not cleanup.antigravity_source_absence_verified(source, witness=receipts[-1])


def test_frozen_companion_change_blocks_apply(tmp_path, native):
    source, native_db, summary_db, proto, _, _ = native
    plan = cleanup.plan_antigravity_sqlite_cleanup(source)
    proto.write_bytes(proto.read_bytes().replace(b"selected", b"modified"))
    result = cleanup.apply_antigravity_sqlite_cleanup(
        plan, data_dir=tmp_path, receipt_id=str(uuid4()), record_witness=lambda _: pytest.fail("unexpected receipt"),
    )
    assert result["status"] == "retained"
    assert native_db.exists() and _selected_rows(summary_db, source.session_id)[0]


def test_sidecar_and_child_conversation_are_protected(native):
    source, native_db, summary_db, _, _, neighbor = native
    sidecar = native_db.with_name(native_db.name + "-wal")
    sidecar.write_bytes(b"")
    blocked = cleanup.plan_antigravity_sqlite_cleanup(source)
    assert blocked.reason_codes == ("antigravity_cleanup_active_or_open",)
    sidecar.unlink()
    with closing(sqlite3.connect(summary_db)) as db, db:
        db.execute("UPDATE conversation_summaries SET parent_conversation_id=? WHERE conversation_id=?",
                   (source.session_id, neighbor))
    blocked = cleanup.plan_antigravity_sqlite_cleanup(source)
    assert blocked.reason_codes == ("antigravity_cleanup_related_conversation",)
    assert native_db.exists()
