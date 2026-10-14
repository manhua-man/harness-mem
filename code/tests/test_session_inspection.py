from __future__ import annotations

import json
import sqlite3

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.source_inspection import classify_records, ownership_for
from harness_mem.commands.session_inventory import collect_session_inventory, read_session_page
from harness_mem.config.merge import MergedConfig
from harness_mem.storage.canonical_store import CanonicalStoreRuntime
from harness_mem.storage.transcript_store import TranscriptStore


@pytest.fixture
def fixture_sources(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    data = tmp_path / "data"
    monkeypatch.setattr("harness_mem.commands.session_inventory.load_merged_config", lambda *_: MergedConfig())

    def write(name, records):
        path = projects / "arbitrary-name" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        return path

    def factory(client):
        assert client == "cursor"
        return CursorAdapter(None, projects_dir=projects)

    return root, projects, data, write, factory


def test_inventory_is_read_only_and_distinguishes_ownership_and_drafts(fixture_sources):
    root, _, data, write, factory = fixture_sources
    write("short", [{"role": "user", "cwd": str(root), "message": {"content": "yes"}}])
    write("empty", [{"type": "session_start", "cwd": str(root)}, {"type": "turn_ended"}])
    write("mention", [{"role": "user", "message": {"content": str(root)}}])
    write("other", [{"role": "user", "cwd": str(root.parent / "other"), "message": {"content": "other"}}])
    write("unknown", [{"future_format": True, "cwd": str(root)}])
    inventory = collect_session_inventory(data, project_root=root, project_name="project", clients=["cursor"], adapter_factory=factory)
    rows = {row["session_id"]: row for row in inventory.rows}
    assert rows["short"]["processing"] == "pending"
    assert rows["empty"]["readability"] == "empty_draft"
    assert rows["empty"]["processing"] == "skipped"
    assert rows["mention"]["ownership"] == "unknown"
    assert rows["other"]["ownership"] == "other"
    assert rows["unknown"]["processing"] == "blocked"
    assert not data.exists()
    assert "content" not in json.dumps(inventory.payload())


@pytest.mark.parametrize("item", [
    {"type": "image", "source": {"data": "fixture"}},
    {"type": "tool_use", "name": "Read", "input": {}},
    {"type": "document", "source": "fixture"},
])
def test_non_text_interactions_never_count_as_empty(item):
    assert classify_records([{"role": "assistant", "message": {"content": [item]}}], "cursor") == "readable"


def test_broken_and_future_records_never_count_as_empty(fixture_sources):
    root, _, data, write, factory = fixture_sources
    bad = write("bad", [])
    bad.write_text("not JSON", encoding="utf-8")
    write("good", [{"type": "session_start", "cwd": str(root)}])
    result = collect_session_inventory(data, project_root=root, project_name="project", clients=["cursor"], adapter_factory=factory)
    bad_row = next(row for row in result.rows if row["session_id"] == "bad")
    # Discovery cannot certify format/content without an owner and complete read.
    assert bad_row["readability"] == "not_checked"
    assert bad_row["ownership"] == "unknown"
    assert len(result.rows) == 2


def test_source_pages_cover_tail_and_reject_changed_revision(fixture_sources):
    root, _, data, write, factory = fixture_sources
    path = write("long", [{"role": "user", "cwd": str(root), "message": {"content": "a" * 200 + "LAST_TOPIC"}}])
    inventory = collect_session_inventory(data, project_root=root, project_name="project", clients=["cursor"], adapter_factory=factory)
    session = inventory.rows[0]
    offset = 0
    pieces = []
    hashes = set()
    while True:
        page = read_session_page(data, project_root=root, project_name="project", session=session, offset=offset, page_chars=31, adapter_factory=factory)
        pieces.append(page["content"])
        hashes.add(page["content_sha256"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert "".join(pieces) == path.read_text(encoding="utf-8")
    assert len(hashes) == 1
    path.write_text(path.read_text(encoding="utf-8") + "\n{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        read_session_page(data, project_root=root, project_name="project", session=session, adapter_factory=factory)
    assert not data.exists()


def test_private_content_not_returned(fixture_sources):
    root, _, data, write, factory = fixture_sources
    write("private", [{"role": "user", "cwd": str(root), "message": {"content": "public <private>secret</private>"}}])
    inventory = collect_session_inventory(data, project_root=root, project_name="project", clients=["cursor"], adapter_factory=factory)
    page = read_session_page(data, project_root=root, project_name="project", session=inventory.rows[0], adapter_factory=factory)
    assert "secret" not in page["content"]
    assert "public" in page["content"]


def test_path_mentions_and_conflicting_roots_are_not_ownership(tmp_path):
    from harness_mem.adapters.source_inspection import normalized_root
    assert normalized_root("") == ""
    assert normalized_root("relative-project") == ""
    assert ownership_for([str(tmp_path), str(tmp_path / "other")], tmp_path) == "unknown"
    assert ownership_for(["vscode-remote://host/work"], tmp_path) == "unknown"
    assert ownership_for([tmp_path.name], tmp_path) == "unknown"


@pytest.mark.parametrize("store_type", [TranscriptStore, CanonicalStoreRuntime])
def test_read_only_stores_never_initialize_or_allow_writes(tmp_path, store_type):
    missing = tmp_path / "missing"
    with pytest.raises(sqlite3.OperationalError):
        store_type(missing, read_only=True)
    assert not missing.exists()
    writable = store_type(tmp_path)
    writable.close()
    reader = store_type(tmp_path, read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader._conn.execute("CREATE TABLE forbidden(id INTEGER)")
    finally:
        reader.close()


@pytest.mark.parametrize("meta_root,turn_roots,expected", [
    ("project", ["project", "other"], "unknown"),
    (None, ["project"], "project"),
    (None, ["other"], "other"),
    ("project", ["project"], "project"),
])
def test_codex_inspects_all_native_structured_roots(tmp_path, meta_root, turn_roots, expected):
    from harness_mem.adapters.source_inspection import inspect_native_source
    rows = [{"type": "session_meta", "payload": {
        "id": "fixture", **({"cwd": str(tmp_path / meta_root)} if meta_root else {}),
    }}]
    rows.extend({"type": "turn_context", "payload": {"cwd": str(tmp_path / root)}}
                for root in turn_roots)
    rows.append({"type": "event_msg", "payload": {"type": "user_message", "message": "hello"}})
    path = tmp_path / "fixture.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    inspected = inspect_native_source(None, "codex", {"path": path, "session_id": "fixture"},
                                      project_root=tmp_path / "project", config=MergedConfig())
    assert inspected.ownership == expected
    assert inspected.readability == "readable"
    assert inspected.reason is None
    assert inspected.text == "User: hello"


@pytest.mark.parametrize("unknown", [False, True])
def test_codex_native_classification_preserves_capture_digest_and_privacy(tmp_path, unknown):
    from harness_mem.adapters.source_inspection import inspect_native_source, read_native_source
    from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, render_codex_conversation
    from harness_mem.capture_policy import redact_private_bytes
    from harness_mem.transcript_chunking import sha256_bytes
    rows = [
        {"type": "session_meta", "payload": {"cwd": str(tmp_path)}},
        {"type": "response_item", "payload": {"type": "message", "role": "system",
          "content": [{"type": "input_text", "text": "SYSTEM_SECRET"}]}},
        {"type": "response_item", "payload": {"type": "reasoning", "text": "REASONING_SECRET"}},
        {"type": "event_msg", "payload": {"type": "user_message",
          "message": "hello <private>PRIVATE_SECRET</private>"}},
    ]
    if unknown:
        rows.append({"type": "future_native_format", "payload": {"text": "FUTURE_SECRET"}})
    path = tmp_path / "fixture.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    record = {"path": path, "session_id": "fixture"}
    exported = read_native_source(None, "codex", record)
    assert "SYSTEM_SECRET" not in repr(exported)
    assert "REASONING_SECRET" not in repr(exported)
    assert "FUTURE_SECRET" not in repr(exported)
    inspected = inspect_native_source(None, "codex", record, project_root=tmp_path, config=MergedConfig())
    assert inspected.ownership == "project"
    assert inspected.readability == ("unknown_format" if unknown else "readable")
    assert inspected.reason == ("unknown_format" if unknown else None)
    _, turns = parse_codex_archive_jsonl_session(path)
    permitted = render_codex_conversation(turns).encode("utf-8")
    captured, _ = redact_private_bytes(permitted)
    assert inspected.native_digest == sha256_bytes(captured)
    assert "hello" in inspected.text
    assert "SECRET" not in inspected.text
