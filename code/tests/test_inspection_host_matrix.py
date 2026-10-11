from __future__ import annotations

import json
import sqlite3
from urllib.parse import quote

import pytest

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.grok.adapter import GrokAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.opencode.adapter import OpenCodeAdapter
from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.commands.session_inventory import collect_session_inventory, read_session_page
from harness_mem.config.merge import MergedConfig


@pytest.mark.parametrize("client", ["claude-code", "codex", "cursor", "grok", "hermes", "opencode", "antigravity"])
def test_native_inventory_and_complete_pages_are_readonly_for_each_host(tmp_path, monkeypatch, client):
    root = tmp_path / "project"
    root.mkdir()
    native = tmp_path / "native"
    native.mkdir()
    data = tmp_path / "data"
    rows = [{"role": "user", "cwd": str(root), "content": "HEAD " + "x" * 100 + " TAIL_TOPIC"}]
    path = native / "unused"
    if client == "claude-code":
        path = native / "bucket" / "fixture.jsonl"
        adapter = ClaudeCodeAdapter(None, sessions_dir=native)
    elif client == "codex":
        path = native / "rollout-fixture.jsonl"
        rows = [{"type": "session_meta", "payload": {"id": "fixture", "cwd": str(root)}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": rows[0]["content"]}}]
        adapter = CodexAdapter(None, sessions_dir=native, archive_dir=tmp_path / "archive", scope="all")
    elif client == "cursor":
        path = native / "bucket" / "agent-transcripts" / "fixture" / "fixture.jsonl"
        adapter = CursorAdapter(None, projects_dir=native)
    elif client == "grok":
        path = native / quote(str(root), safe="") / "fixture" / "chat_history.jsonl"
        adapter = GrokAdapter(None, sessions_dir=native)
    elif client == "hermes":
        path = native / "session_fixture.json"
        rows = [{"session_id": "session_fixture", "cwd": str(root), "messages": rows}]
        adapter = HermesAdapter(None, sessions_dir=native, scope="all")
    elif client == "antigravity":
        path = native / "fixture" / ".system_generated" / "logs" / "transcript.jsonl"
        rows = [{"type": "USER_INPUT", "cwd": str(root), "content": rows[0]["content"]}]
        adapter = AntigravityAdapter(None, brain_dir=native)
    else:
        path = native / "opencode.db"
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT, title TEXT, time_created INTEGER, time_updated INTEGER);
                CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
                CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT);
            """)
            db.execute("INSERT INTO session VALUES('fixture',?,'Fixture',1,2)", (str(root),))
            db.execute("INSERT INTO message VALUES('m','fixture',1,?)", (json.dumps({"role": "user"}),))
            db.execute("INSERT INTO part VALUES('p','m','fixture',?)", (json.dumps({"type": "text", "text": rows[0]["content"]}),))
        adapter = OpenCodeAdapter(None, database_path=path)
    if client != "opencode":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    before = {p: p.read_bytes() for p in native.rglob("*") if p.is_file()}
    monkeypatch.setattr("harness_mem.commands.session_inventory.load_merged_config", lambda *_: MergedConfig())
    def factory(_):
        return adapter
    inventory = collect_session_inventory(data, project_root=root, project_name="project", clients=[client], adapter_factory=factory)
    assert len(inventory.rows) == 1, inventory.payload()
    source = inventory.rows[0]
    assert (source["ownership"], source["readability"], source["processing"]) == ("project", "readable", "pending"), inventory.payload()
    offset, chunks = 0, []
    while True:
        page = read_session_page(data, project_root=root, project_name="project", session=source, offset=offset, page_chars=37, adapter_factory=factory)
        chunks.append(page["content"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert "TAIL_TOPIC" in "".join(chunks)
    assert {p: p.read_bytes() for p in native.rglob("*") if p.is_file()} == before
    assert not data.exists()
