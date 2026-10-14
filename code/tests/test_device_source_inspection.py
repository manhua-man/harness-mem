"""Selected native reads without project binding, using fictional local sources."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.protocol import SessionRecord
from harness_mem.adapters.source_inspection import InspectedSource, inspect_native_source, read_native_source
from harness_mem.capture_policy import PRIVATE_REDACTION, redact_private_bytes
from harness_mem.config.merge import MergedConfig
from harness_mem.transcript_chunking import sha256_bytes


@pytest.fixture(autouse=True)
def fictional_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home" / "hermes"))
    monkeypatch.delenv("HERMES_STATE_DB", raising=False)


def json_source(tmp_path: Path, client: str, metadata: dict, content: str = "selected message") -> tuple[Any, SessionRecord]:
    adapter: Any = None
    path = tmp_path / "selected.jsonl"
    rows = [{"role": "user", "content": content, **metadata}]
    if client == "codex":
        rows = [
            {"type": "session_meta", "payload": {"id": "selected", **metadata}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": content}},
        ]
    elif client == "cursor":
        adapter = CursorAdapter(None, projects_dir=tmp_path / "cursor", sqlite_databases=())
    elif client == "hermes":
        adapter = HermesAdapter(None, sessions_dir=tmp_path / "hermes", home_dir=tmp_path / "home")
        rows = [{"session_id": "selected", **metadata, "messages": [{"role": "user", "content": content}]}]
    elif client == "grok":
        path = tmp_path / "unbound-bucket" / "selected" / "chat_history.jsonl"
    elif client == "antigravity":
        brain = tmp_path / "brain"
        adapter = AntigravityAdapter(None, brain_dir=brain, home_dir=tmp_path / "home")
        path = brain / "selected" / ".system_generated" / "logs" / "transcript_full.jsonl"
        rows = [{"type": "USER_INPUT", "content": content, **metadata}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return adapter, {"path": path, "session_id": "selected"}


@pytest.mark.parametrize("client,binding", [
    (client, binding)
    for client in ("claude-code", "codex", "cursor", "grok", "hermes", "antigravity")
    for binding in ("absent", "rootless", "remote", "other", "matching", "multiple")
    if (client, binding) != ("antigravity", "multiple")
])
def test_selected_json_source_does_not_require_project_ownership(tmp_path, client, binding):
    root, other = tmp_path / "project", tmp_path / "historical"
    metadata = {
        "absent": {}, "rootless": {"cwd": "relative-workspace"},
        "remote": {"workspace": "vscode-remote://fictional/workspace"},
        "other": {"cwd": str(other)}, "matching": {"cwd": str(root)},
        "multiple": {"workspace_root": str(root), "cwd": str(other)},
    }[binding]
    adapter, record = json_source(tmp_path, client, metadata)
    before = record["path"].read_bytes()
    inspected = inspect_native_source(adapter, client, record, project_root=None, config=MergedConfig())
    assert inspected.ownership == "source"
    assert inspected.readability == "readable"
    assert inspected.reason is None
    assert "selected message" in inspected.text
    assert inspected.captured_bytes is not None
    assert inspected.native_digest == sha256_bytes(inspected.captured_bytes)
    if client == "codex":
        assert inspected.native_input_bytes is None
        assert inspected.native_input_digest == sha256_bytes(before)
    else:
        assert inspected.native_input_bytes == before
    assert inspected.project_roots is not None
    if binding == "multiple":
        assert set(inspected.project_roots) == {str(root), str(other)}
    strict = inspect_native_source(adapter, client, record, project_root=root, config=MergedConfig())
    assert strict.ownership == {"matching": "project", "other": "other"}.get(binding, "unknown")
    assert strict.text == inspected.text
    assert strict.native_digest == inspected.native_digest
    assert record["path"].read_bytes() == before


def test_antigravity_native_tool_envelopes_do_not_hide_a_real_conversation(tmp_path):
    adapter, record = json_source(tmp_path, "antigravity", {})
    rows = [
        {"type": "USER_INPUT", "source": "USER", "status": "DONE", "content": "Use TSV for exports."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE", "content": "Preference received."},
        {"type": "GENERIC", "source": "MODEL", "status": "DONE", "content": 'Created At: 2026-10-15\n{"status":"empty","memories":[]}'},
    ]
    record["path"].write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    inspected = inspect_native_source(adapter, "antigravity", record, project_root=None, config=MergedConfig())
    assert inspected.ownership == "source"
    assert inspected.readability == "readable"
    assert "Use TSV for exports." in inspected.text
    assert "Preference received." in inspected.text


def test_antigravity_native_tool_envelope_alone_is_not_a_conversation(tmp_path):
    adapter, record = json_source(tmp_path, "antigravity", {})
    record["path"].write_text(json.dumps({"type": "GENERIC", "source": "MODEL", "status": "DONE", "content": "Tool output"}), encoding="utf-8")
    inspected = inspect_native_source(adapter, "antigravity", record, project_root=None, config=MergedConfig())
    assert inspected.readability == "empty_draft"


def test_codex_outputs_original_input_and_parsed_authored_texts_once(tmp_path, monkeypatch):
    path = tmp_path / "rollout.jsonl"
    user = "first <private>fixture secret</private>"
    rows = [
        {"type": "session_meta", "payload": {"cwd": str(tmp_path / "old")}},
        {"type": "response_item", "payload": {"type": "message", "role": "system",
         "content": [{"type": "input_text", "text": "host system fixture"}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": user}},
        {"type": "turn_context", "payload": {"cwd": str(tmp_path / "new")}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "second"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "assistant only"}},
    ]
    raw = b"\xef\xbb\xbf" + "\r\n".join(json.dumps(row) for row in rows).encode("utf-8")
    path.write_bytes(raw)
    read_bytes = Path.read_bytes
    reads = []

    def counted_read(source):
        reads.append(source)
        return read_bytes(source)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    record: SessionRecord = {"path": path, "session_id": "selected"}
    exported = read_native_source(None, "codex", record)
    assert reads == [path]
    assert "native_input_bytes" not in exported
    assert exported["native_input_digest"] == sha256_bytes(raw)
    assert exported["authored_user_texts"] == [user, "second"]
    assert "host system fixture" not in exported["source_text"]
    reads.clear()
    inspected = inspect_native_source(None, "codex", record, project_root=None, config=MergedConfig())
    assert reads == [path]
    assert inspected.native_input_bytes is None
    assert inspected.native_input_digest == sha256_bytes(raw)
    assert inspected.authored_user_texts == exported["authored_user_texts"]
    expected, _ = redact_private_bytes(exported["raw_bytes"])
    assert inspected.captured_bytes == expected
    assert inspected.native_digest == sha256_bytes(expected)
    assert "fixture secret" not in inspected.text
    assert PRIVATE_REDACTION in inspected.text
    assert "host system fixture" not in inspected.text


@pytest.mark.parametrize("unknown", [False, True])
def test_codex_nonreadable_sources_keep_classification_and_no_capture(tmp_path, unknown):
    rows = [{"type": "session_meta", "payload": {"id": "selected"}}]
    if unknown:
        rows += [
            {"type": "event_msg", "payload": {"type": "user_message", "message": "public <private>fixture secret</private>"}},
            {"type": "future_native_format", "payload": {"text": "unknown fixture"}},
        ]
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    record: SessionRecord = {"path": path, "session_id": "selected"}
    for root in (None, tmp_path):
        inspected = inspect_native_source(None, "codex", record, project_root=root, config=MergedConfig())
        assert inspected.readability == ("unknown_format" if unknown else "empty_draft")
        assert inspected.reason == ("unknown_format" if unknown else None)
        assert inspected.captured_bytes is inspected.native_input_bytes is None
        assert inspected.authored_user_texts is None
        assert "fixture secret" not in inspected.text


@pytest.mark.parametrize("host_user", [False, True])
@pytest.mark.parametrize("unknown", [False, True])
def test_codex_filtered_empty_capture_is_skipped_before_import(tmp_path, host_user, unknown):
    rows = [{"type": "session_meta", "payload": {"id": "selected"}}]
    if host_user:
        rows.append({"type": "event_msg", "payload": {
            "type": "user_message", "message": "# AGENTS.md instructions\nHost context.",
        }})
    rows.append({"type": "event_msg", "payload": {
        "type": "agent_message", "message": "Assistant-only host progress.",
    }})
    if unknown:
        rows.append({"type": "future_native_format", "payload": {"text": "unknown"}})
    path = tmp_path / "rollout-filtered.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    before = path.read_bytes()
    inspected = inspect_native_source(
        None, "codex", {"path": path, "session_id": "selected"},
        project_root=None, config=MergedConfig(),
    )
    assert inspected.readability == ("unknown_format" if unknown else "empty_draft")
    assert inspected.captured_bytes is None
    assert inspected.authored_user_texts is None
    assert not inspected.text.strip()
    assert path.read_bytes() == before


def test_codex_lifecycle_metadata_does_not_block_complete_conversation(tmp_path):
    path = tmp_path / "rollout.jsonl"
    rows = [{"type": "session_meta", "payload": {"id": "selected"}}]
    rows.extend({"type": kind, "payload": {"fixture": "host-only metadata"}}
                for kind in ("world_state", "compacted", "inter_agent_communication_metadata", "token_usage_record"))
    rows.extend([
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Keep useful facts."}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "Understood.", "phase": "final_answer"}},
    ])
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    before = path.read_bytes()
    inspected = inspect_native_source(None, "codex", {"path": path, "session_id": "selected"},
                                      project_root=None, config=MergedConfig())
    assert inspected.readability == "readable"
    assert inspected.reason is None
    assert "User: Keep useful facts." in inspected.text
    assert "Assistant: Understood." in inspected.text
    assert "host-only metadata" not in inspected.text
    assert inspected.captured_bytes is not None
    assert path.read_bytes() == before


@pytest.mark.parametrize("private_tags", [False, True])
def test_capture_bytes_follow_existing_redaction_policy(tmp_path, private_tags):
    adapter, record = json_source(tmp_path, "cursor", {}, "public <private>fictional secret</private>")
    raw = record["path"].read_bytes()
    inspected = inspect_native_source(adapter, "cursor", record, project_root=None,
                                      config=MergedConfig(capture_private_tags=private_tags))
    expected = redact_private_bytes(raw)[0] if private_tags else raw
    assert inspected.captured_bytes == expected
    assert inspected.native_input_bytes == raw
    assert inspected.native_digest == sha256_bytes(expected)
    assert ("fictional secret" in inspected.text) is not private_tags
    assert inspected.authored_user_texts is None


@pytest.mark.parametrize("project_bound", [False, True])
@pytest.mark.parametrize("config,reason", [
    (MergedConfig(capture_enabled=False), "capture_disabled"),
    (MergedConfig(capture_ignore_clients=("CODEX",)), "client_ignored"),
    (MergedConfig(capture_ignore_session_ids=("selected",)), "session_ignored"),
    (MergedConfig(capture_ignore_source_globs=("*selected.jsonl",)), "source_ignored"),
])
def test_exclusion_precedes_native_read_and_contains_no_capture(tmp_path, monkeypatch, project_bound, config, reason):
    def forbidden(*args, **kwargs):
        pytest.fail("excluded source was read")

    monkeypatch.setattr("harness_mem.adapters.source_inspection.read_native_source", forbidden)
    record: SessionRecord = {"path": tmp_path / "selected.jsonl", "session_id": "selected"}
    inspected = inspect_native_source(None, "codex", record,
                                      project_root=tmp_path if project_bound else None, config=config)
    assert (inspected.ownership, inspected.readability, inspected.reason) == ("unknown", "excluded", reason)
    assert inspected.text == inspected.native_digest == ""
    assert inspected.captured_bytes is inspected.native_input_bytes is None
    assert inspected.authored_user_texts is inspected.project_roots is None


@pytest.mark.parametrize("raw,status,reason", [
    (b"", "empty_source", None),
    (b'{"type":"session_start"}', "empty_draft", None),
    (b'{"future_format":true}', "unknown_format", None),
    (b"not JSON", "parse_failed", "parse_failed"),
    (b"[]", "unknown_format", "unknown_format"),
])
def test_nonreadable_classification_is_unchanged(tmp_path, raw, status, reason):
    path = tmp_path / "source.jsonl"
    path.write_bytes(raw)
    record: SessionRecord = {"path": path, "session_id": "selected"}
    for root in (None, tmp_path):
        inspected = inspect_native_source(None, "claude-code", record, project_root=root, config=MergedConfig())
        assert (inspected.readability, inspected.reason) == (status, reason)
        assert inspected.native_digest == sha256_bytes(raw)
        assert inspected.captured_bytes is inspected.native_input_bytes is None
        assert inspected.authored_user_texts is None


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, UnicodeDecodeError])
def test_unreadable_source_errors_are_not_swallowed(tmp_path, monkeypatch, failure):
    path = tmp_path / "unreadable.jsonl"
    if failure is UnicodeDecodeError:
        path.write_bytes(b"\xff")
    elif failure is PermissionError:
        def denied(_path):
            raise PermissionError("fictional denied source")
        monkeypatch.setattr(Path, "read_bytes", denied)
    record: SessionRecord = {"path": path, "session_id": "selected"}
    for root in (None, tmp_path):
        with pytest.raises(failure):
            inspect_native_source(None, "claude-code", record, project_root=root, config=MergedConfig())


@pytest.mark.parametrize("client", ["hermes", "opencode"])
@pytest.mark.parametrize("binding", ["absent", "rootless", "other"])
def test_native_sqlite_reads_only_selected_session_without_owner(tmp_path, client, binding):
    path = tmp_path / "native.db"
    workspace = {"absent": None, "rootless": "relative-workspace", "other": str(tmp_path / "historical")}[binding]
    with sqlite3.connect(path) as db:
        if client == "hermes":
            db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT)")
            db.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, active INTEGER, content TEXT)")
            db.executemany("INSERT INTO sessions VALUES (?, ?)", [("selected", workspace), ("unrelated", workspace)])
            db.executemany("INSERT INTO messages VALUES (?, ?, 1, ?)", [(1, "selected", "selected message"), (2, "unrelated", "unrelated message")])
        else:
            db.execute("CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT)")
            db.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, content TEXT)")
            db.execute("CREATE TABLE part (id TEXT, session_id TEXT, message_id TEXT, content TEXT)")
            db.executemany("INSERT INTO session VALUES (?, ?)", [("selected", workspace), ("unrelated", workspace)])
            db.executemany("INSERT INTO message VALUES (?, ?, 1, ?)", [("a", "selected", "selected message"), ("b", "unrelated", "unrelated message")])
    adapter = HermesAdapter(None, sessions_dir=tmp_path / "sessions", state_db=path, home_dir=tmp_path / "home") if client == "hermes" else None
    record: SessionRecord = {"path": path, "session_id": "selected"}
    before = path.read_bytes()
    inspected = inspect_native_source(adapter, client, record, project_root=None, config=MergedConfig())
    assert (inspected.ownership, inspected.readability) == ("source", "readable")
    assert "selected message" in inspected.text and "unrelated message" not in inspected.text
    assert inspected.native_input_bytes == inspected.captured_bytes
    assert inspected.authored_user_texts is None
    strict = inspect_native_source(adapter, client, record, project_root=tmp_path, config=MergedConfig())
    assert strict.ownership == ("other" if binding == "other" else "unknown")
    assert path.read_bytes() == before


def test_cursor_global_sqlite_without_workspace_membership_is_readable(tmp_path):
    path = tmp_path / "User" / "globalStorage" / "state.vscdb"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
        for sid in ("selected", "unrelated"):
            db.executemany("INSERT INTO cursorDiskKV VALUES (?, ?)", [
                (f"composerData:{sid}", json.dumps({"composerId": sid, "fullConversationHeadersOnly": [{"bubbleId": "b"}]})),
                (f"bubbleId:{sid}:b", json.dumps({"bubbleId": "b", "text": f"{sid} message"})),
            ])
    adapter = CursorAdapter(None, sqlite_databases=(path,))
    record = next(row for row in adapter.list_session_metadata() if row["session_id"] == "selected")
    before = path.read_bytes()
    inspected = inspect_native_source(adapter, "cursor", record, project_root=None, config=MergedConfig())
    assert (inspected.ownership, inspected.readability) == ("source", "readable")
    assert inspected.project_roots == []
    assert "selected message" in inspected.text and "unrelated message" not in inspected.text
    assert inspected.native_input_bytes == inspected.captured_bytes
    strict = inspect_native_source(adapter, "cursor", record, project_root=tmp_path, config=MergedConfig())
    assert strict.ownership == "unknown"
    assert path.read_bytes() == before


def test_device_read_keeps_conversation_but_explicit_workspace_rejects_conflict(tmp_path):
    adapter, record = json_source(tmp_path, "antigravity", {"workspace_root": str(tmp_path / "old"), "cwd": str(tmp_path / "new")})
    inspected = inspect_native_source(adapter, "antigravity", record, project_root=None, config=MergedConfig())
    assert inspected.ownership == "source" and inspected.readability == "readable"
    with pytest.raises(ValueError, match="conflicting native workspace roots"):
        inspect_native_source(adapter, "antigravity", record, project_root=tmp_path / "old", config=MergedConfig())


def test_inspected_source_new_fields_preserve_positional_construction(tmp_path):
    record: SessionRecord = {"path": tmp_path / "source", "session_id": "selected"}
    inspected = InspectedSource("codex", "selected", "uri", "digest", "text", "project", "readable", None, record, None)
    assert inspected.captured_bytes is inspected.native_input_bytes is None
    assert inspected.authored_user_texts is inspected.project_roots is None
