from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import (
    fake_embed_texts,
    no_embed_texts,
    patch_cli_adapters,
    read_events,
    run,
    write_claude_session,
)

pytestmark = pytest.mark.cli


def test_wake_without_profile_still_prints_budget(capsys: pytest.CaptureFixture[str]):
    assert run(cli.cmd_wake_up("demo-no-profile")) == 0
    captured = capsys.readouterr().out
    assert "Approx wake-up tokens:" in captured
    assert "[L0]" in captured


def test_profile_and_wake_surface_conventions(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                description="desc",
                stacks=["python"],
                key_files=["app.py"],
                conventions=["run tests first"],
            )
        )
    )

    assert run(cli.cmd_profile("demo")) == 0
    profile_output = capsys.readouterr().out
    assert "Conventions (1):" in profile_output
    assert "run tests first" in profile_output

    assert run(cli.cmd_wake_up("demo")) == 0
    wake_output = capsys.readouterr().out
    assert "Conventions:" in wake_output
    assert "run tests first" in wake_output


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
    captured = capsys.readouterr().out
    assert "search-default-project" in captured


def test_search_surfaces_observation_id_for_show(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            id="obs-search-001",
            session_id="search-session-001",
            client="codex",
            raw_content="JWT expiry handling is documented in the auth flow.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["search"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(cli.cmd_search("demo", "JWT", "fts")) == 0
    captured = capsys.readouterr().out
    assert "[obs-search-001]" in captured
    assert "session: search-session-001" in captured


def test_timeline_surfaces_observation_id_for_show(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            id="obs-timeline-001",
            session_id="timeline-session-001",
            client="codex",
            raw_content="JWT expiry handling is documented in the auth flow.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["timeline"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(cli.cmd_timeline("demo", 5)) == 0
    captured = capsys.readouterr().out
    assert "[obs-timeline-001]" in captured
    assert "session: timeline-session-001" in captured


def test_show_accepts_session_id_when_it_resolves_uniquely(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            id="obs-show-001",
            session_id="show-session-001",
            client="codex",
            raw_content="JWT expiry handling is documented in the auth flow.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["show"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(cli.cmd_show("demo", "show-session-001")) == 0
    captured = capsys.readouterr().out
    assert "# Observation: obs-show-001" in captured
    assert "Session: show-session-001" in captured


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


def test_cmd_search_reports_hybrid_mode(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="architecture",
                    content="SQLite FTS5 powers local search.",
                    source="manual",
                )
            )
        )
    finally:
        run(backend.close())

    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", fake_embed_texts)

    assert run(cli.cmd_search("demo", "SQLite", "hybrid")) == 0
    output = capsys.readouterr().out
    assert "[Hybrid Search]" in output
    assert "mode: hybrid" in output


def test_cmd_search_reports_fts_fallback_when_embedding_missing(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="architecture",
                    content="SQLite FTS5 powers local search.",
                    source="manual",
                )
            )
        )
    finally:
        run(backend.close())

    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", no_embed_texts)

    assert run(cli.cmd_search("demo", "SQLite", "auto")) == 0
    output = capsys.readouterr().out
    assert "[FTS Search]" in output
    assert "embedding not available" in output


def test_search_logs_command_event(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="architecture",
                    content="SQLite FTS5 powers local search.",
                    source="manual",
                )
            )
        )
    finally:
        run(backend.close())

    assert run(cli.cmd_search("demo", "SQLite", "fts")) == 0
    _ = capsys.readouterr()

    events = read_events(data_dir)
    assert any(event["type"] == "command_invoked" and event["command"] == "search" for event in events)
    assert any(event["type"] == "next_step_adopted" and event["command"] == "search" for event in events)


@pytest.mark.integration
def test_best_practices_claude_mainline_flow(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-best-practice-001",
        "Please improve local search reliability.",
        ["We decided to use SQLite FTS5 for local search because it keeps the stack local-first."],
    )
    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )
    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", no_embed_texts)

    assert cli.cmd_use("demo") == 0
    _ = capsys.readouterr()

    assert run(cli.cmd_doctor("demo")) == 0
    initial_doctor = capsys.readouterr().out
    assert "harness-mem ingest claude-code -n 1" in initial_doctor
    assert "Start by ingesting the newest session: sess-best-practice-001." in initial_doctor

    assert run(cli.cmd_ingest("claude-code", "demo", 5)) == 0
    ingest_output = capsys.readouterr().out
    assert "Sessions found: 1" in ingest_output
    assert "Ingested: 1 sessions" in ingest_output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert len(observations) == 1
        assert observations[0].metadata["project_name"] == "demo"
    finally:
        run(backend.close())

    assert run(cli.cmd_doctor("demo")) == 0
    post_ingest_doctor = capsys.readouterr().out
    assert "harness-mem ds" in post_ingest_doctor

    assert run(cli.cmd_distill("demo")) == 0
    distill_output = capsys.readouterr().out
    assert "Extracted 1 memory entries from 1 sessions" in distill_output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert len(entries) == 1
        assert "SQLite FTS5" in entries[0].content
    finally:
        run(backend.close())

    assert run(cli.cmd_doctor("demo")) == 0
    post_distill_doctor = capsys.readouterr().out
    assert "harness-mem wake" in post_distill_doctor

    assert run(cli.cmd_wake_up("demo")) == 0
    wake_output = capsys.readouterr().out
    assert "# Memory Entries" in wake_output
    assert "Approx wake-up tokens:" in wake_output
    assert "SQLite FTS5" in wake_output

    assert run(cli.cmd_search("demo", "SQLite", "auto")) == 0
    search_output = capsys.readouterr().out
    assert "[FTS Search]" in search_output
    assert "embedding not available" in search_output
    assert "SQLite FTS5" in search_output
