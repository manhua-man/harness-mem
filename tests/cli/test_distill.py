from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run, write_claude_session

pytestmark = pytest.mark.cli


def test_cmd_distill_all_sessions_processes_project(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root: Path,
):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-a",
        "Please help with search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )

    patch_cli_adapters(monkeypatch, claude_sessions_root=claude_sessions_root)

    assert run(cli.cmd_distill("demo")) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert len(entries) == 1
        assert "SQLite FTS5" in entries[0].content
    finally:
        run(backend.close())


def test_cmd_distill_prints_heuristic_pattern_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-pattern-source",
        "Please improve search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )

    patch_cli_adapters(monkeypatch, claude_sessions_root=claude_sessions_root)

    assert run(cli.cmd_distill("demo", "sess-pattern-source")) == 0

    captured = capsys.readouterr().out
    assert "(source: we decided to use)" in captured


def test_cmd_distill_prints_per_entry_sources_for_multi_entry_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
):
    project_dir = claude_sessions_root / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    session_path = project_dir / "sess-multi-entry.jsonl"
    records = [
        {"type": "user", "message": {"content": "Please improve search."}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "We decided to use SQLite FTS5 for search indexing because it keeps the stack local-first."}],
            },
        },
        {"type": "user", "message": {"content": "What fixed the migration issue?"}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "The fix was to rebuild the local index after migration so stale tokens do not leak into search results."}],
            },
        },
    ]
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    patch_cli_adapters(monkeypatch, claude_sessions_root=claude_sessions_root)

    assert run(cli.cmd_distill("demo", "sess-multi-entry")) == 0

    captured = capsys.readouterr().out
    assert "(source: we decided to use)" in captured
    assert "(source: the fix was)" in captured


def test_distill_ignores_user_only_prompts(data_dir: Path, claude_sessions_root: Path):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-user-prompt",
        "We decided to use SQLite for search. Please implement it.",
        ["I can explore a few options and report back once I verify the tradeoffs."],
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        adapter = ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root)
        entry = run(adapter.distill_session("sess-user-prompt", "demo"))
        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert entry == []
        assert entries == []
    finally:
        run(backend.close())


def test_distill_dedupes_on_rerun(data_dir: Path, claude_sessions_root: Path):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-dedupe",
        "Please improve the search docs.",
        ["We decided to use SQLite FTS5 for full-text search because it keeps the v1 stack local-first."],
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        adapter = ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root)
        first = run(adapter.distill_session("sess-dedupe", "demo"))
        assert first != []

        second = run(adapter.distill_session("sess-dedupe", "demo"))
        assert second == []

        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert len(entries) == 1
    finally:
        run(backend.close())


def test_distill_extracts_relation_facts(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-relation",
        "Please summarize dependencies.",
        ["HybridSearchLayer delegates to SQLiteIndex for local relation search reads."],
    )

    patch_cli_adapters(monkeypatch, claude_sessions_root=claude_sessions_root)

    assert run(cli.cmd_distill("demo", "sess-relation")) == 0
    captured = capsys.readouterr().out
    assert "Extracted 1 relation facts from sess-relation" in captured
    assert "HybridSearchLayer --delegates_to-> SQLiteIndex" in captured

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        facts = run(backend.structured_store.list_relation_facts("demo", limit=10))
        assert entries == []
        assert len(facts) == 1
        assert facts[0].relation_type == "delegates_to"

        adapter = ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root)
        assert run(adapter.distill_relation_facts("sess-relation", "demo")) == []
    finally:
        run(backend.close())


def test_project_distill_category_no_match_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-a",
        "Please help with search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-b",
        "Please improve search.",
        ["We decided to use SQLite FTS5 because it keeps the stack local-first."],
    )

    patch_cli_adapters(monkeypatch, claude_sessions_root=claude_sessions_root)

    assert run(cli.cmd_distill("demo", category="bug")) == 1

    captured = capsys.readouterr().out
    assert "No bug entries found across 2 sessions" in captured
