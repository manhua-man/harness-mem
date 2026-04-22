"""Tests for learning-loop and task-resume CLI flows."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem import cli_commands
from harness_mem.core.schemas import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli_commands, "DEFAULT_DATA_DIR", data_dir)
    return data_dir


def test_learning_loop_promotes_candidate_to_confirmed_rule(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            session_id="session-learning-001",
            client="claude-code",
            raw_content="User corrected the agent to validate JWT expiry before authenticated calls.",
            content_type="transcript",
            metadata={"project_name": "demo"},
            tags=["session", "correction"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(
        cli_commands.cmd_correct(
            "session-learning-001",
            "demo",
            "Always validate JWT expiry before API calls",
            "Before any authenticated API call",
        )
    ) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_rule_candidates("demo"))
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.status == "pending"
    finally:
        run(backend.close())

    assert run(cli_commands.cmd_confirm_rule(candidate.id)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        updated_candidate = run(backend.structured_store.get_rule_candidate(candidate.id))
        confirmed_rules = run(backend.structured_store.list_confirmed_rules("demo"))
        assert updated_candidate is not None
        assert updated_candidate.status == "accepted"
        assert len(confirmed_rules) == 1
        assert confirmed_rules[0].source_candidate_id == candidate.id
    finally:
        run(backend.close())


def test_handoff_update_reuses_existing_record(data_dir: Path):
    assert run(
        cli_commands.cmd_handoff(
            "demo",
            "task-001",
            "Fix auth bug",
            next_steps=["Check JWT validation logic"],
            blockers=["Waiting for token samples"],
        )
    ) == 0

    assert run(
        cli_commands.cmd_handoff(
            "demo",
            "task-001",
            "Fix auth bug",
            status="blocked",
            next_steps=["Collect fresh token samples"],
            blockers=["Need production token sample"],
        )
    ) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        handoffs = run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.task_id == "task-001"
        assert handoff.status == "blocked"
        assert handoff.next_steps == ["Collect fresh token samples"]
        assert handoff.blockers == ["Need production token sample"]
    finally:
        run(backend.close())
