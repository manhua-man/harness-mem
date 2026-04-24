"""CLI UX tests for quickstart, doctor, and interactive flows."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import cli, cli_commands
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(coro):
    return asyncio.run(coro)


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
    assert "Suggested next step:" in captured.out
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
    assert "Suggested next step:" in captured.out
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
