"""Regression tests for distillation, Codex ingest, and natural-language search."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.core.schemas import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli, "DEFAULT_DATA_DIR", data_dir)
    return data_dir


def _write_claude_session(
    sessions_root: Path,
    project_name: str,
    session_id: str,
    user_text: str,
    assistant_texts: list[str],
) -> Path:
    project_dir = sessions_root / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    session_path = project_dir / f"{session_id}.jsonl"

    records = [
        {"type": "user", "message": {"content": user_text}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": text} for text in assistant_texts],
            },
        },
    ]
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return session_path


def _write_codex_session(sessions_root: Path, session_id: str, text: str) -> Path:
    session_path = sessions_root / f"{session_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"role": "user", "content": text}) + "\n", encoding="utf-8")
    return session_path


def test_cmd_distill_all_sessions_processes_project(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-a",
        "Please help with search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

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
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-pattern-source",
        "Please improve search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_distill("demo", "sess-pattern-source")) == 0

    captured = capsys.readouterr()
    assert "(source: we decided to use)" in captured.out


def test_cmd_distill_prints_per_entry_sources_for_multi_entry_session(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sessions_root = tmp_path / "claude-projects"
    project_dir = sessions_root / "demo"
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

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_distill("demo", "sess-multi-entry")) == 0

    captured = capsys.readouterr()
    assert "(source: we decided to use)" in captured.out
    assert "(source: the fix was)" in captured.out


def test_distill_ignores_user_only_prompts(data_dir: Path, tmp_path: Path):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-user-prompt",
        "We decided to use SQLite for search. Please implement it.",
        ["I can explore a few options and report back once I verify the tradeoffs."],
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        adapter = ClaudeCodeAdapter(backend, sessions_dir=sessions_root)
        entry = run(adapter.distill_session("sess-user-prompt", "demo"))
        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert entry == []
        assert entries == []
    finally:
        run(backend.close())


def test_distill_dedupes_on_rerun(data_dir: Path, tmp_path: Path):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-dedupe",
        "Please improve the search docs.",
        ["We decided to use SQLite FTS5 for full-text search because it keeps the v1 stack local-first."],
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        adapter = ClaudeCodeAdapter(backend, sessions_dir=sessions_root)
        first = run(adapter.distill_session("sess-dedupe", "demo"))
        assert first != []

        second = run(adapter.distill_session("sess-dedupe", "demo"))
        # Second run: deduped against existing, no new entries saved
        assert second == []

        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert len(entries) == 1
    finally:
        run(backend.close())


def test_project_distill_category_no_match_returns_failure(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-a",
        "Please help with search.",
        ["We decided to use SQLite FTS5 for project search indexing."],
    )
    _write_claude_session(
        sessions_root,
        "demo",
        "sess-b",
        "Please improve search.",
        ["We decided to use SQLite FTS5 because it keeps the stack local-first."],
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_distill("demo", category="bug")) == 1

    captured = capsys.readouterr()
    assert "No bug entries found across 2 sessions" in captured.out


def test_codex_ingest_requires_project_name(data_dir: Path):
    assert run(cli.cmd_ingest("codex", None, 5)) == 1


def test_use_sets_active_project_and_search_uses_it(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            session_id="search-default-project",
            client="codex",
            raw_content="JWT expiry handling is documented in the auth flow.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["search"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(cli.cmd_search(None, "JWT")) == 0
    captured = capsys.readouterr()
    assert "search-default-project" in captured.out


def test_codex_ingest_sets_project_metadata(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sessions_root = tmp_path / "codex-sessions"
    _write_codex_session(sessions_root, "codex-demo", "Worked on auth token expiry handling.")

    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_ingest("codex", "demo-project", 5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert len(observations) == 1
        assert observations[0].metadata["project_name"] == "demo-project"
    finally:
        run(backend.close())


def test_codex_ingest_uses_active_project(data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sessions_root = tmp_path / "codex-sessions"
    _write_codex_session(sessions_root, "codex-active", "Worked on auth token expiry handling.")

    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=sessions_root),
    )

    assert cli.cmd_use("demo-project") == 0
    assert run(cli.cmd_ingest("codex", None, 5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert len(observations) == 1
        assert observations[0].metadata["project_name"] == "demo-project"
    finally:
        run(backend.close())


def test_natural_language_search_matches_relevant_observation(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            session_id="search-001",
            client="codex",
            raw_content="I worked on authentication and JWT expiry handling.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["search"],
        )
        run(backend.verbatim_store.save(observation))

        results = run(
            backend.verbatim_store.search(
                "what did I work on",
                project_name="demo",
                limit=5,
            )
        )
        assert len(results) == 1
    finally:
        run(backend.close())
