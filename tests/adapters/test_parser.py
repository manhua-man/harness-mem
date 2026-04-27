"""Tests for :mod:`harness_mem.adapters.parser`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from harness_mem.adapters.parser import (
    HEURISTIC_PATTERNS,
    extract_heuristic_entries,
    list_session_files,
    parse_claude_jsonl_session,
    parse_codex_jsonl_session,
    select_turns_for_packet,
    session_sort_key,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, lines: list[dict]) -> Path:
    """Write a list of dicts as a .jsonl file."""
    path.write_text(
        "\n".join(json.dumps(rec, ensure_ascii=False) for rec in lines),
        encoding="utf-8",
    )
    return path


def _claude_turn(user: str = "", assistant: list[str] | None = None, tools: list[dict] | None = None) -> dict:
    """Build a Claude-format turn dict (matching parser.Turn)."""
    return {
        "user": user,
        "assistant": assistant or [],
        "tools": tools or [],
    }


def _claude_user_record(content: str) -> dict:
    return {"type": "user", "message": {"content": content}}


def _claude_assistant_text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _claude_tool_use(name: str, input_: dict | None = None) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": input_ or {}}]}}


# ===================================================================
# parse_claude_jsonl_session
# ===================================================================

class TestParseClaudeJsonl:
    def test_basic_user_assistant_turns(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record("Hello"),
            _claude_assistant_text("Hi there, how can I help?"),
            _claude_user_record("What is Python?"),
            _claude_assistant_text("Python is a programming language."),
        ])
        turns = parse_claude_jsonl_session(p, on_error="silent")
        assert len(turns) == 2
        assert turns[0]["user"] == "Hello"
        assert "Hi there" in turns[0]["assistant"][0]
        assert turns[1]["user"] == "What is Python?"
        assert "Python is a" in turns[1]["assistant"][0]

    def test_tool_use_recorded(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record("Create a file"),
            _claude_tool_use("write_file", {"path": "/tmp/test.txt", "content": "hello"}),
        ])
        turns = parse_claude_jsonl_session(p, on_error="silent")
        assert len(turns) == 1
        assert len(turns[0]["tools"]) == 1
        assert turns[0]["tools"][0]["name"] == "write_file"

    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "empty.jsonl", [])
        assert parse_claude_jsonl_session(p, on_error="silent") == []

    def test_all_malformed_lines_returns_empty(self, tmp_path: Path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\nstill not json\n", encoding="utf-8")
        assert parse_claude_jsonl_session(p, on_error="silent") == []

    def test_on_error_warn_does_not_raise(self, tmp_path: Path):
        p = tmp_path / "unreadable.jsonl"
        # Don't create the file at all — triggers file-not-found
        result = parse_claude_jsonl_session(p, on_error="warn")
        assert result == []

    def test_on_error_raise_propagates(self, tmp_path: Path):
        p = tmp_path / "no-such-file.jsonl"
        with pytest.raises(Exception):
            parse_claude_jsonl_session(p, on_error="raise")

    def test_user_truncation(self, tmp_path: Path):
        long_user = "x" * 5000
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record(long_user),
        ])
        turns = parse_claude_jsonl_session(p, max_user_chars=100, on_error="silent")
        assert len(turns[0]["user"]) == 100

    def test_assistant_truncation(self, tmp_path: Path):
        long_asst = "x" * 5000
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record("hi"),
            _claude_assistant_text(long_asst),
        ])
        turns = parse_claude_jsonl_session(p, max_assistant_chars=50, on_error="silent")
        assert len(turns[0]["assistant"][0]) == 50

    def test_filter_xml_directives_skips_xml(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record("<system>You are a helpful assistant</system>"),
            _claude_user_record("Actual user question"),
        ])
        turns = parse_claude_jsonl_session(p, filter_xml_directives=True, on_error="silent")
        assert len(turns) == 1
        assert turns[0]["user"] == "Actual user question"

    def test_short_assistant_text_skipped(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record("hi"),
            _claude_assistant_text("ok"),  # len("ok") <= 20, should be skipped
        ])
        turns = parse_claude_jsonl_session(p, on_error="silent")
        assert len(turns[0]["assistant"]) == 0

    def test_default_parameters_match_adapter_behavior(self, tmp_path: Path):
        """Verify default truncations match the original claude adapter (2000/1000/300)."""
        long_user = "A" * 3000
        long_asst = "B" * 2000
        p = _write_jsonl(tmp_path / "session.jsonl", [
            _claude_user_record(long_user),
            _claude_assistant_text(long_asst),
            _claude_tool_use("bash", {"cmd": "C" * 500}),
        ])
        turns = parse_claude_jsonl_session(p, on_error="silent")
        assert len(turns[0]["user"]) == 2000
        assert len(turns[0]["assistant"][0]) == 1000
        assert len(turns[0]["tools"][0]["input"]) == 300


# ===================================================================
# parse_codex_jsonl_session
# ===================================================================

class TestParseCodexJsonl:
    def test_role_based_format(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "codex.jsonl", [
            {"role": "user", "content": "Hello Codex"},
            {"role": "assistant", "content": "Hello! I'm Codex."},
        ])
        turns = parse_codex_jsonl_session(p)
        assert len(turns) == 1
        assert turns[0]["user"] == "Hello Codex"
        assert "Hello! I'm Codex" in turns[0]["assistant"][0]

    def test_type_based_format_fallback(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "codex.jsonl", [
            {"type": "user", "message": {"content": "Hi"}},
        ])
        turns = parse_codex_jsonl_session(p)
        assert len(turns) == 1
        assert turns[0]["user"] == "Hi"

    def test_tool_calls_list_format(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "codex.jsonl", [
            {"role": "user", "content": "Run command"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "bash", "arguments": '{"cmd":"ls"}'}}]},
        ])
        turns = parse_codex_jsonl_session(p)
        assert len(turns) == 1
        assert any("[tool: bash]" in a for a in turns[0]["assistant"])

    def test_tool_calls_dict_format(self, tmp_path: Path):
        p = _write_jsonl(tmp_path / "codex.jsonl", [
            {"role": "user", "content": "Run command"},
            {"role": "assistant", "function_call": {"name": "bash", "arguments": '{"cmd":"ls"}'}},
        ])
        turns = parse_codex_jsonl_session(p)
        assert len(turns) == 1
        assert any("[tool: bash]" in a for a in turns[0]["assistant"])

    def test_issues_reporting_malformed_lines(self, tmp_path: Path):
        p = tmp_path / "partial.jsonl"
        p.write_text(
            '{"role": "user", "content": "hi"}\n'
            'not-json\n'
            '{"role": "assistant", "content": "bye"}\n',
            encoding="utf-8",
        )
        issues: list[dict] = []
        turns = parse_codex_jsonl_session(p, issues=issues)
        assert len(turns) == 1
        assert len(issues) == 1
        assert issues[0]["code"] == "session_malformed_lines_skipped"

    def test_all_malformed_raises_valueerror(self, tmp_path: Path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\nstill not\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no valid JSON records"):
            parse_codex_jsonl_session(p)

    def test_empty_after_parse_issues_warning(self, tmp_path: Path):
        """Valid JSON but no parseable transcript content."""
        p = _write_jsonl(tmp_path / "empty.jsonl", [
            {"type": "something_else", "data": "noise"},
        ])
        issues: list[dict] = []
        turns = parse_codex_jsonl_session(p, issues=issues)
        assert turns == []
        assert any(i["code"] == "session_empty_after_parse" for i in issues)

    def test_file_not_found_raises_valueerror(self, tmp_path: Path):
        p = tmp_path / "nonexistent.jsonl"
        with pytest.raises(ValueError, match="unable to read file"):
            parse_codex_jsonl_session(p)


# ===================================================================
# list_session_files
# ===================================================================

class TestListSessionFiles:
    def test_basic_scan(self, tmp_path: Path):
        for name in ["a.jsonl", "b.jsonl", "c.jsonl"]:
            (tmp_path / name).write_text("x" * 2000, encoding="utf-8")
        sessions = list_session_files(tmp_path, min_size_kb=0)
        assert len(sessions) == 3
        keys = {"path", "name", "session_id", "size_kb", "size", "lines", "mtime"}
        assert all(keys.issubset(s.keys()) for s in sessions)
        # sorted newest first
        assert sessions[0]["mtime"] >= sessions[-1]["mtime"]

    def test_min_size_filter(self, tmp_path: Path):
        (tmp_path / "small.jsonl").write_text("x" * 100, encoding="utf-8")     # < 1KB
        (tmp_path / "big.jsonl").write_text("x" * 200000, encoding="utf-8")    # ~195KB
        sessions = list_session_files(tmp_path, min_size_kb=100)
        assert len(sessions) == 1
        assert sessions[0]["name"] == "big.jsonl"

    def test_empty_directory(self, tmp_path: Path):
        assert list_session_files(tmp_path, min_size_kb=0) == []

    def test_nonexistent_directory(self):
        assert list_session_files(Path("/nonexistent/path"), min_size_kb=0) == []


# ===================================================================
# session_sort_key
# ===================================================================

class TestSessionSortKey:
    def test_returns_mtime(self):
        now = datetime.now(UTC)
        assert session_sort_key({"mtime": now}) == now

    def test_fallback_to_epoch(self):
        epoch = datetime.min.replace(tzinfo=UTC)
        assert session_sort_key({}) == epoch
        assert session_sort_key({"mtime": "not-a-datetime"}) == epoch


# ===================================================================
# select_turns_for_packet
# ===================================================================

class TestSelectTurnsForPacket:
    def test_short_session_returns_all(self):
        turns = [_claude_turn(f"Turn {i}", []) for i in range(5)]
        selected, omitted = select_turns_for_packet(turns, max_turns=10)
        assert len(selected) == 5
        assert omitted == 0

    def test_long_session_keeps_head_and_tail(self):
        turns = [_claude_turn(f"Turn {i}", []) for i in range(20)]
        selected, omitted = select_turns_for_packet(turns, max_turns=12)
        assert len(selected) == 12
        assert omitted == 8
        # First half = turns 0..5, last half = turns 14..19
        assert selected[0]["user"] == "Turn 0"
        assert selected[-1]["user"] == "Turn 19"
        assert selected[-2]["user"] == "Turn 18"

    def test_exactly_max_turns(self):
        turns = [_claude_turn(f"Turn {i}", []) for i in range(12)]
        selected, omitted = select_turns_for_packet(turns, max_turns=12)
        assert len(selected) == 12
        assert omitted == 0

    def test_empty_list(self):
        selected, omitted = select_turns_for_packet([], max_turns=12)
        assert selected == []
        assert omitted == 0


# ===================================================================
# HEURISTIC_PATTERNS / extract_heuristic_entries
# ===================================================================

class TestExtractHeuristicEntries:
    def test_decision_pattern(self):
        turns = [_claude_turn("", ["we decided to use FastAPI for the backend"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert any(e.category == "decision" for e in entries)

    def test_architecture_pattern(self):
        turns = [_claude_turn("", ["I set up the database with PostgreSQL"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert any(e.category == "architecture" for e in entries)

    def test_bug_pattern(self):
        turns = [_claude_turn("", ["the fix was to increase the timeout to 30s"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert any(e.category == "bug" for e in entries)

    def test_convention_pattern(self):
        turns = [_claude_turn("", ["the standard is to use snake_case"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert any(e.category == "convention" for e in entries)

    def test_api_pattern(self):
        turns = [_claude_turn("", ["the api endpoint is at /v2/users"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert any(e.category == "api" for e in entries)

    def test_ignores_user_turns(self):
        """User text should not produce entries."""
        turns = [_claude_turn("we should use FastAPI", [])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        assert len(entries) == 0

    def test_empty_turns(self):
        assert extract_heuristic_entries([], "demo", "sess-1") == []

    def test_deduplicates_identical_content(self):
        turns = [_claude_turn("", [
            "we decided to use FastAPI",
            "we decided to use FastAPI",  # same content again
        ])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        decision_entries = [e for e in entries if e.category == "decision"]
        assert len(decision_entries) == 1

    def test_custom_patterns(self):
        custom = [(__import__("re").compile(r"\bmy_custom_pattern\b", __import__("re").I), "custom", "custom")]
        turns = [_claude_turn("", ["my_custom_pattern was used"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1", patterns=custom)
        assert len(entries) == 1
        assert entries[0].category == "custom"

    def test_bug_confidence_lower(self):
        turns = [_claude_turn("", ["the fix was to restart the service"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        bug_entry = next(e for e in entries if e.category == "bug")
        assert bug_entry.confidence == 0.6  # bug confidence

    def test_other_confidence_higher(self):
        turns = [_claude_turn("", ["we decided to use Redis"])]
        entries = extract_heuristic_entries(turns, "demo", "sess-1")
        dec_entry = next(e for e in entries if e.category == "decision")
        assert dec_entry.confidence == 0.7  # non-bug confidence

    def test_heuristic_patterns_constant_is_populated(self):
        """Verify HEURISTIC_PATTERNS has the expected number of patterns."""
        assert len(HEURISTIC_PATTERNS) >= 20
        categories = {c for _, c, _ in HEURISTIC_PATTERNS}
        assert "decision" in categories
        assert "architecture" in categories
        assert "bug" in categories
        assert "convention" in categories
        assert "api" in categories
