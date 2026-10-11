"""Read-only inventory regressions using synthetic, isolated sources."""

import inspect
from pathlib import Path

import pytest

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.grok.adapter import GrokAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.parser import list_session_files


@pytest.mark.parametrize("adapter", [ClaudeCodeAdapter, CursorAdapter, GrokAdapter, HermesAdapter])
@pytest.mark.parametrize("method", ["list_sessions", "ingest"])
def test_adapter_defaults_do_not_filter_short_sources(adapter, method):
    assert inspect.signature(getattr(adapter, method)).parameters["min_size_kb"].default == 0


def test_inventory_preserves_short_empty_and_unknown_sources(tmp_path):
    contents = {
        "short": '{"role":"user","message":{"content":[{"type":"text","text":"Keep SQLite"}]}}',
        "empty": " \n",
        "unknown": '{"future_schema":true}',
        "malformed": "not JSON",
    }
    for name, content in contents.items():
        (tmp_path / f"{name}.jsonl").write_text(content, encoding="utf-8")
    records = {row["session_id"]: row for row in list_session_files(tmp_path)}
    assert set(records) == set(contents)
    assert records["empty"]["source_status"] == "empty_source"
    for name in ("short", "unknown", "malformed"):
        assert records[name]["source_status"] == "readable"
    assert list_session_files(tmp_path, min_size_kb=1) == []


@pytest.mark.parametrize("failure", ["read", "stat", "encoding"])
def test_inventory_retains_failed_source_and_continues(tmp_path, monkeypatch, failure):
    bad = tmp_path / "bad.jsonl"
    good = tmp_path / "good.jsonl"
    bad.write_bytes(b"\xff" if failure == "encoding" else b"{}")
    good.write_text("{}", encoding="utf-8")
    method = "read_text" if failure == "read" else "stat"
    original = getattr(Path, method)

    def fail_one(path, *args, **kwargs):
        if path == bad:
            raise PermissionError("synthetic unreadable source")
        return original(path, *args, **kwargs)

    if failure != "encoding":
        monkeypatch.setattr(Path, method, fail_one)
    issues = []
    records = {row["session_id"]: row for row in list_session_files(tmp_path, issues=issues)}
    assert records["bad"]["source_status"] == "unreadable"
    assert records["good"]["source_status"] == "readable"
    assert len(issues) == 1
    assert "lines" not in records["bad"]


def test_cursor_inventory_propagates_errors_without_dropping_short_session(tmp_path):
    source = tmp_path / "demo" / "agent-transcripts" / "session"
    source.mkdir(parents=True)
    (source / "short.jsonl").write_text('{"role":"user"}', encoding="utf-8")
    (source / "bad.jsonl").write_bytes(b"\xff")
    issues = []
    adapter = CursorAdapter(None, projects_dir=tmp_path, project_root=Path("F:/demo"))
    records = adapter.list_sessions(issues=issues)
    assert {row["session_id"] for row in records} == {"short", "bad"}
    assert issues[0]["code"] == "session_read_failed"
