"""CLI UX tests for quickstart, doctor, and interactive flows."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import cli, cli_commands  # noqa: E402
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter  # noqa: E402
from harness_mem.adapters.codex.adapter import CodexAdapter  # noqa: E402
from harness_mem.core.schemas import Observation  # noqa: E402
from harness_mem.core.schemas.memory_entry import MemoryEntry  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore  # noqa: E402
from harness_mem.core.schemas.project_profile import ProjectProfile  # noqa: E402
from harness_mem.search.hybrid_search import HybridSearchLayer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _read_events(data_dir: Path) -> list[dict]:
    events_path = data_dir / "events.log"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(cli_commands, "DEFAULT_DATA_DIR", data_dir)
    return data_dir


def test_quickstart_initializes_and_saves_profile(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15.0.0", "react": "19.0.0"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert run(cli.cmd_quickstart("demo", client="skip", limit=5)) == 0
    assert (data_dir / "active_project.txt").read_text(encoding="utf-8").strip() == "demo"
    assert (data_dir / "profiles" / "demo.json").exists()


def test_quickstart_shows_recent_sessions_and_recommends_distill(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    (project_root / "package.json").write_text(
        json.dumps({"dependencies": {"react": "19.0.0"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    claude_sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    codex_sessions_root = tmp_path / "codex-sessions"

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )
    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
    )

    assert run(cli.cmd_quickstart("demo", client="auto", limit=5)) == 0

    captured = capsys.readouterr()
    assert "Recent Claude Code sessions:" in captured.out
    assert "sess-recent-001" in captured.out
    assert "📍 Phase:" in captured.out
    assert "harness-mem ds" in captured.out


def test_quickstart_auto_does_not_ingest_global_codex_sessions(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    project_root = tmp_path / "demo"
    project_root.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    claude_sessions_root = tmp_path / "claude-projects"
    codex_sessions_root = tmp_path / "codex-sessions"
    codex_sessions_root.mkdir(parents=True, exist_ok=True)
    (codex_sessions_root / "unrelated.jsonl").write_text(
        json.dumps({"role": "user", "content": "Worked on another repo entirely."}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )
    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
    )

    assert run(cli.cmd_quickstart("demo", client="auto", limit=5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert observations == []
    finally:
        run(backend.close())

    captured = capsys.readouterr()
    assert "Codex sessions (global): 1" in captured.out
    assert "Auto-ingest skipped for Codex" in captured.out
    assert "Ingesting codex sessions" not in captured.out


def test_doctor_reports_uninitialized_state(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert run(cli.cmd_doctor("demo")) == 1
    captured = capsys.readouterr()
    assert "Initialized: no" in captured.out
    assert "quickstart" in captured.out


def test_wake_without_profile_still_prints_budget(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert run(cli.cmd_wake_up("demo-no-profile")) == 0
    captured = capsys.readouterr()
    assert "Approx wake-up tokens:" in captured.out
    assert "[L0]" in captured.out


def test_doctor_shows_recent_sessions_and_recommends_wake(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="sess-recent-001",
                    client="claude-code",
                    raw_content="Worked on the SQLite search migration.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session"],
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Use SQLite FTS5 for local search.",
                    source="session:sess-recent-001",
                    tags=["search"],
                )
            )
        )
    finally:
        run(backend.close())

    claude_sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    codex_sessions_root = tmp_path / "codex-sessions"

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )
    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr()
    assert "Recent Claude Code sessions:" in captured.out
    assert "sess-recent-001" in captured.out
    assert "📍 Phase:" in captured.out
    assert "harness-mem wake" in captured.out


def test_doctor_warns_that_codex_sessions_are_global_before_recommending_ingest(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    claude_sessions_root = tmp_path / "claude-projects"
    codex_sessions_root = tmp_path / "codex-sessions"
    codex_sessions_root.mkdir(parents=True, exist_ok=True)
    (codex_sessions_root / "unrelated.jsonl").write_text(
        json.dumps({"role": "user", "content": "Worked on another repo entirely."}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )
    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr()
    assert "Codex sessions (global): 1" in captured.out
    assert "not project-scoped" in captured.out
    assert "Review recent Codex sessions before any codex ingest" in captured.out
    assert "Start by ingesting the newest session" not in captured.out


def test_doctor_codex_only_project_recommends_search_until_structured_memory_exists(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="codex-session-001",
                    client="codex",
                    raw_content="Worked on JWT expiry handling in the auth flow.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session", "codex"],
                )
            )
        )
    finally:
        run(backend.close())

    claude_sessions_root = tmp_path / "claude-projects"
    codex_sessions_root = tmp_path / "codex-sessions"
    codex_sessions_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )
    monkeypatch.setattr(
        cli,
        "CodexAdapter",
        lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
    )

    assert run(cli.cmd_doctor("demo")) == 0

    captured = capsys.readouterr()
    assert "Observations: 1" in captured.out
    assert "Memory entries: 0" in captured.out
    assert "harness-mem search <query>" in captured.out
    assert "wake-up needs structured memory" in captured.out
    assert "harness-mem wake" not in captured.out


def test_interactive_correct_via_main(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="session-correct-001",
                    client="claude-code",
                    raw_content="User corrected the agent to validate JWT expiry before authenticated calls.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session", "correction"],
                )
            )
        )
    finally:
        run(backend.close())

    assert cli.cmd_use("demo") == 0
    answers = iter(
        [
            "session-correct-001",
            "Always validate JWT expiry before API calls",
            "Before any authenticated API call",
        ]
    )
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["harness-mem", "correct"])

    assert cli.main() == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_rule_candidates("demo"))
        assert len(candidates) == 1
        assert candidates[0].pattern == "Always validate JWT expiry before API calls"
    finally:
        run(backend.close())


def test_interactive_handoff_via_main(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    assert cli.cmd_use("demo") == 0
    answers = iter(
        [
            "task-42",
            "Fix auth bug",
            "blocked",
            "Check JWT validation",
            "",
            "Waiting for token samples",
            "",
        ]
    )
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["harness-mem", "handoff"])

    assert cli.main() == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        handoffs = run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        assert len(handoffs) == 1
        assert handoffs[0].task_id == "task-42"
        assert handoffs[0].status == "blocked"
        assert handoffs[0].next_steps == ["Check JWT validation"]
        assert handoffs[0].blockers == ["Waiting for token samples"]
    finally:
        run(backend.close())


def test_profile_edit_existing_profile_merges_without_crashing(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                description="old desc",
                stacks=["python"],
                key_files=["app.py"],
                conventions=["run tests first"],
            )
        )
    )

    answers = iter(["", "", "", ""])
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert run(cli.cmd_profile_edit("demo")) == 0

    updated = run(profile_store.get("demo"))
    assert updated is not None
    assert updated.description == "old desc"
    assert updated.stacks == ["python"]
    assert updated.key_files == ["app.py"]
    assert updated.conventions == ["run tests first"]


def test_profile_edit_description_supports_clear(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                description="old desc",
                stacks=["python"],
                key_files=["app.py"],
                conventions=["run tests first"],
            )
        )
    )

    answers = iter(["!clear", "", "", ""])
    monkeypatch.setattr(cli, "_can_prompt", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert run(cli.cmd_profile_edit("demo")) == 0

    updated = run(profile_store.get("demo"))
    assert updated is not None
    assert updated.description == ""


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


def test_purge_dry_run_handles_aware_timestamps_without_deleting(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="purge-aware-dry-run",
                    client="claude-code",
                    raw_content="Old observation kept during dry run.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Old memory kept during dry run.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.search("dry run", project_name="demo", limit=10))
        entries = run(backend.structured_store.search_memory_entries("dry run", project_name="demo", limit=10))
        assert len(observations) == 1
        assert len(entries) == 1
    finally:
        run(backend.close())

    captured = capsys.readouterr()
    assert "[DRY RUN] Would soft-delete" in captured.out


def test_purge_hides_soft_deleted_data_from_search_timeline_and_wake(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="purge-hide-001",
                    client="claude-code",
                    raw_content="Ancient auth observation that should disappear.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Ancient auth memory that should disappear.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", False)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.search("Ancient auth", project_name="demo", limit=10))
        timeline = run(backend.verbatim_store.timeline(project_name="demo", limit=10))
        entries = run(backend.structured_store.search_memory_entries("Ancient auth", project_name="demo", limit=10))
        listed_entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert observations == []
        assert timeline == []
        assert entries == []
        assert listed_entries == []
    finally:
        run(backend.close())

    assert run(cli.cmd_wake_up("demo")) == 0
    wake_output = capsys.readouterr().out
    assert "Ancient auth" not in wake_output


def test_purge_all_requires_project_context_for_structured_memory(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert run(cli.cmd_purge("2026-01-01", "all", True, project_name=None)) == 1
    output = capsys.readouterr().out
    assert "Project name required for purge" in output


def test_purge_project_scope_only_removes_target_project_data(
    data_dir: Path,
):
    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="demo-session",
                    client="claude-code",
                    raw_content="Old demo observation.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="other-session",
                    client="claude-code",
                    raw_content="Old other observation.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "other"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Old demo memory.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="other",
                    category="decision",
                    content="Old other memory.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", False, project_name="demo")) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        demo_observations = run(backend.verbatim_store.search("Old demo", project_name="demo", limit=10))
        other_observations = run(backend.verbatim_store.search("Old other", project_name="other", limit=10))
        demo_entries = run(backend.structured_store.search_memory_entries("Old demo", project_name="demo", limit=10))
        other_entries = run(backend.structured_store.search_memory_entries("Old other", project_name="other", limit=10))
        assert demo_observations == []
        assert demo_entries == []
        assert len(other_observations) == 1
        assert len(other_entries) == 1
    finally:
        run(backend.close())


def test_incremental_ingest_does_not_reimport_old_sessions(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(sessions_root, "demo", "sess-1", "u1", ["a1"])
    _write_claude_session(sessions_root, "demo", "sess-2", "u2", ["a2"])
    _write_claude_session(sessions_root, "demo", "sess-3", "u3", ["a3"])

    now = datetime.now().timestamp()
    for offset, session_id in enumerate(["sess-1", "sess-2", "sess-3"], start=3):
        session_path = sessions_root / "demo" / f"{session_id}.jsonl"
        session_path.touch()
        session_time = now - (offset * 60)
        session_path.touch()
        import os
        os.utime(session_path, (session_time, session_time))

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 2)) == 0
    assert run(cli.cmd_ingest("claude-code", "demo", 2)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert [o.session_id for o in observations] == ["sess-1", "sess-2"]
    finally:
        run(backend.close())


def test_full_rescan_bypasses_cursor_without_duplicate_ingest(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(sessions_root, "demo", "sess-1", "u1", ["a1"])
    _write_claude_session(sessions_root, "demo", "sess-2", "u2", ["a2"])
    _write_claude_session(sessions_root, "demo", "sess-3", "u3", ["a3"])

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 1)) == 0
    assert run(cli.cmd_ingest("claude-code", "demo", 10, True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert sorted(o.session_id for o in observations) == ["sess-1", "sess-2", "sess-3"]
    finally:
        run(backend.close())

    captured = capsys.readouterr()
    assert "[Full Rescan]" in captured.out


def test_incremental_ingest_warns_when_cursor_is_missing(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    sessions_root = tmp_path / "claude-projects"
    _write_claude_session(sessions_root, "demo", "sess-1", "u1", ["a1"])
    _write_claude_session(sessions_root, "demo", "sess-2", "u2", ["a2"])
    _write_claude_session(sessions_root, "demo", "sess-3", "u3", ["a3"])

    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                last_ingest_session_id="missing-session",
                last_ingest_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=sessions_root),
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 10)) == 0
    captured = capsys.readouterr()
    assert "cursor missing-session not found" in captured.out


def _fake_embed_texts(self, texts: list[str]) -> list[list[float]]:
    return [[1.0, float(len(text))] for text in texts]


def _no_embed_texts(self, texts: list[str]) -> None:
    return None


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

    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", _fake_embed_texts)

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

    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", _no_embed_texts)

    assert run(cli.cmd_search("demo", "SQLite", "auto")) == 0
    output = capsys.readouterr().out
    assert "[FTS Search]" in output
    assert "embedding not available" in output


def test_doctor_logs_next_step_event(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    assert cli.cmd_use("demo") == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="sess-recent-001",
                    client="claude-code",
                    raw_content="Worked on the SQLite search migration.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                    tags=["session"],
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Use SQLite FTS5 for local search.",
                    source="session:sess-recent-001",
                    tags=["search"],
                )
            )
        )
    finally:
        run(backend.close())

    claude_sessions_root = tmp_path / "claude-projects"
    _write_claude_session(
        claude_sessions_root,
        "demo",
        "sess-recent-001",
        "Help me improve search.",
        ["We decided to use SQLite FTS5 for local search."],
    )
    monkeypatch.setattr(
        cli,
        "ClaudeCodeAdapter",
        lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
    )

    assert run(cli.cmd_doctor("demo")) == 0

    events = _read_events(data_dir)
    assert any(
        event["type"] == "next_step_shown"
        and event["command"] == "doctor"
        and event["next_step"] == "harness-mem wake"
        for event in events
    )


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

    events = _read_events(data_dir)
    assert any(event["type"] == "command_invoked" and event["command"] == "search" for event in events)
    assert any(event["type"] == "next_step_adopted" and event["command"] == "search" for event in events)
