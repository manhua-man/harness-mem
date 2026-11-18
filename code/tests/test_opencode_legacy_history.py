"""Use isolated native OpenCode files and databases through the public history flow."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from harness_mem.adapters.opencode.adapter import OpenCodeAdapter
from harness_mem.adapters.opencode.legacy import OpenCodeSourceError
from harness_mem.commands import session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _records(identity, project, text):
    message_id = f"msg-{identity}"
    return (
        {"id": identity, "directory": str(project), "projectID": "proj", "title": identity,
         "time": {"created": 1000, "updated": 2000}},
        {"id": message_id, "sessionID": identity, "role": "user", "time": {"created": 1000}},
        {"id": f"prt-{identity}", "messageID": message_id, "sessionID": identity, "type": "text", "text": text},
    )


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _legacy(storage, records):
    session, message, part = records
    session_path = _write_json(storage / "session" / session["projectID"] / f"{session['id']}.json", session)
    message_path = _write_json(storage / "message" / session["id"] / f"{message['id']}.json", message)
    part_path = _write_json(storage / "part" / message["id"] / f"{part['id']}.json", part)
    return session_path, message_path, part_path


def _database(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    session, message, part = records
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT, title TEXT,
                project_id TEXT, time_created INTEGER, time_updated INTEGER);
            CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
            CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT);
        """)
        db.execute("INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)", (
            session["id"], session["directory"], session["title"], session["projectID"],
            session["time"]["created"], session["time"]["updated"],
        ))
        db.execute("INSERT INTO message VALUES (?, ?, ?, ?)", (
            message["id"], session["id"], message["time"]["created"], json.dumps(message),
        ))
        db.execute("INSERT INTO part VALUES (?, ?, ?, ?)", (
            part["id"], message["id"], session["id"], json.dumps(part),
        ))


def test_migrated_duplicate_requires_same_workspace_and_complete_native_data(tmp_path):
    root = tmp_path / "project"
    database = tmp_path / "opencode.db"
    records = _records("ses-copy", root, "Original native text")
    paths = _legacy(tmp_path / "storage", records)
    _database(database, records)
    adapter = OpenCodeAdapter(None, database_path=database)
    selected, = adapter.list_session_metadata()
    assert selected["path"] == database
    assert "Original native text" in adapter.read_session_source(database, "ses-copy")["source_text"]
    assert paths[2] in adapter.session_dependency_paths(selected)
    assert database.with_name("opencode.db-wal") in adapter.session_dependency_paths(selected)

    _write_json(paths[2], {**records[2], "text": "Different legacy content"})
    with pytest.raises(OpenCodeSourceError, match="opencode_dual_format_conflict"):
        adapter.read_session_source(database, "ses-copy")
    _write_json(paths[2], records[2])
    _write_json(paths[0], {**records[0], "directory": str(tmp_path / "other-project")})
    with pytest.raises(OpenCodeSourceError, match="opencode_dual_format_conflict"):
        adapter.read_session_source(database, "ses-copy")


def test_legacy_reports_missing_parts_and_conflicting_native_identity(tmp_path):
    records = _records("ses-legacy", tmp_path / "project", "Complete text")
    path, _, part = _legacy(tmp_path / ".local" / "share" / "opencode" / "storage", records)
    adapter = OpenCodeAdapter(None, home_dir=tmp_path)
    assert adapter.database_path is None
    part.unlink()
    with pytest.raises(OpenCodeSourceError, match="opencode_legacy_parts_missing"):
        adapter.read_session_source(path, "ses-legacy")
    _write_json(part, {**records[2], "sessionID": "ses-other"})
    with pytest.raises(OpenCodeSourceError, match="opencode_legacy_part_mismatch"):
        adapter.read_session_source(path, "ses-legacy")

    _write_json(path, {**records[0], "directory": "relative-directory"})
    issues = []
    assert adapter.list_session_metadata(issues=issues) == []
    assert [issue["code"] for issue in issues] == ["opencode_legacy_workspace_unknown"]


def test_discovered_legacy_source_rechecks_when_a_sqlite_copy_appears(tmp_path):
    root = tmp_path / "project"
    profile = tmp_path / ".local" / "share" / "opencode"
    records = _records("ses-legacy", root, "Original native text")
    path, _, _ = _legacy(profile / "storage", records)
    first = OpenCodeAdapter(None, home_dir=tmp_path)
    assert first.list_session_metadata()[0]["path"] == path

    database = profile / "opencode.db"
    _database(database, (records[0], records[1], {**records[2], "text": "Changed database text"}))
    with pytest.raises(OpenCodeSourceError, match="opencode_source_dependencies_changed"):
        first.read_session_source(path, "ses-legacy")
    second = OpenCodeAdapter(None, home_dir=tmp_path)
    with pytest.raises(OpenCodeSourceError, match="opencode_dual_format_conflict"):
        second.read_session_source(database, "ses-legacy")


def test_legacy_page_revision_tracks_part_mutations_without_header_change(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    records = _records("ses-legacy", root, "Original part data")
    session_path, message_path, part_path = _legacy(
        tmp_path / ".local" / "share" / "opencode" / "storage", records,
    )
    data_dir = tmp_path / "data"
    adapter = OpenCodeAdapter(None, home_dir=tmp_path)
    metadata = session_inventory.collect_session_inventory(
        data_dir, project_root=root, project_name="project", clients=["opencode"],
        adapter_factory=lambda _: adapter, lightweight=True,
    ).rows[0]

    def read_page(reference):
        return session_inventory.read_session_page(
            data_dir, project_root=root, project_name="project", session=reference, adapter_factory=lambda _: adapter,
        )

    first = read_page(metadata)
    assert "Original part data" in first["content"]
    manifest = json.loads(first["content"].splitlines()[0])["native_files"]
    assert set(manifest.values()) == {sha256(path.read_bytes()).hexdigest() for path in (session_path, message_path, part_path)}
    _write_json(part_path, {**records[2], "text": "Revised independent part body"})
    second = read_page(metadata)
    assert "Revised independent part body" in second["content"]
    assert first["content_sha256"] != second["content_sha256"]
    assert first["verified_session"]["source_revision"] != second["verified_session"]["source_revision"]
    part_path.unlink()
    with pytest.raises(ValueError, match="opencode_legacy_parts_missing"):
        read_page(metadata)


def test_legacy_and_sqlite_hm_finalization_read_back_ordinary_knowledge(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    profile = tmp_path / "profile"
    database = profile / "opencode.db"
    results = {
        "ses-legacy": ("Legacy receipt policy", "Every legacy export preserves a signed retention receipt."),
        "ses-sqlite": ("SQLite rotation policy", "The SQLite archive rotation keeps two verified backup generations."),
    }
    files = _legacy(profile / "storage", _records("ses-legacy", root, results["ses-legacy"][1]))
    _database(database, _records("ses-sqlite", root, results["ses-sqlite"][1]))
    original = {path: sha256(path.read_bytes()).hexdigest() for path in (*files, database)}
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: OpenCodeAdapter(None, database_path=database))
    handlers = tool_handlers.build_tool_handlers()
    scope = {"project_name": "project", "project_root": str(root)}
    try:
        inventory = handlers["inspect_sessions"](project_root=str(root), clients=["opencode"])
        assert {row["session_id"] for row in inventory["sessions"]} == set(results)
        for row in inventory["sessions"]:
            title, statement = results[row["session_id"]]
            evidence = root / (row["session_id"] + ".txt")
            evidence.write_text(statement, encoding="utf-8")
            packet = handlers["prepare_session_distill"](**scope, batch_sessions=[row])
            assert packet["success"], packet
            job_id = packet["distill_job_id"]
            candidate = handlers["govern_memory"](action="suggest", arguments={
                "kind": "memory", "project_name": "project", "category": "decision",
                "content": statement, "source": evidence.name, "distill_job_id": job_id,
                "evidence_basis": "repository", "verification_outcome": "verified",
                "verification_refs": [{"kind": "repository", "locator": evidence.name,
                                       "content_sha256": sha256(evidence.read_bytes()).hexdigest()}],
                "assimilation_disposition": "add", "assimilation_reason": "The current archive policy is durable.",
                "canonical_title": title, "topic_path": ["Archive"],
            })
            assert candidate["success"], candidate
            final = handlers["finalize_session_distill"]("project", job_id, {
                "session_summary": "The archive policy was verified against the current repository.",
                "final_user_request": "Keep the archive policy available for later work.",
                "final_outcome": "The verified archive policy was saved.",
                "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
                "evidence_status": "answered", "promotion_decision": "promote",
                "final_scope_judgment": {candidate["entry_id"]: {"points": [{
                    "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
                    "source_use": "reusable_knowledge", "reason": "The repository confirms the current policy.",
                    "scope_segments": [{"text": title + "\n" + statement, "source_use": "reusable_knowledge",
                                        "future_scope": "durable", "standalone": True, "content_role": "claim",
                                        "source_support": "supported"}],
                }]}},
            })
            assert final["success"], final
            assert statement in Path(final["note"]["path"]).read_text(encoding="utf-8")
            clean = handlers["prepare_session_distill"](
                **scope, batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True,
            )
            assert clean["counts"] == {"unsupported": 1}, clean
        assert {path: sha256(path.read_bytes()).hexdigest() for path in original} == original
    finally:
        asyncio.run(backend.close())

    reopened = LocalMemoryBackend(data_dir)
    asyncio.run(reopened.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
        for title, statement in results.values():
            found = handlers["search_memory"](query=title, scope="project", project_name="project", detail="full")
            assert {"title": title, "statement": statement} in found["memories"]
    finally:
        asyncio.run(reopened.close())
