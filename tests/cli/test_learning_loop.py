from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem import cli_commands
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.cli


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
        assert confirmed_rules[0].source_session_id == candidate.session_id
    finally:
        run(backend.close())


def test_confirmed_rule_backfills_source_session_from_candidate(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidate = RuleCandidate(
            project_name="demo",
            session_id="session-backfill-001",
            pattern="Always validate JWT expiry before API calls",
            trigger="Before any authenticated API call",
        )
        run(backend.structured_store.save_rule_candidate(candidate))

        confirmed_rules_dir = data_dir / "structured" / "confirmed_rules"
        confirmed_rules_dir.mkdir(parents=True, exist_ok=True)
        confirmed_blob = {
            "id": "rule-backfill-001",
            "project_name": "demo",
            "pattern": candidate.pattern,
            "trigger": candidate.trigger,
            "examples": [],
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "source_candidate_id": candidate.id,
            "tags": [],
        }
        (confirmed_rules_dir / "rule-backfill-001.json").write_text(
            json.dumps(confirmed_blob, indent=2),
            encoding="utf-8",
        )
        backend.structured_store._index.insert(
            "confirmed_rules",
            {
                "id": confirmed_blob["id"],
                "project_name": confirmed_blob["project_name"],
                "pattern": confirmed_blob["pattern"],
                "trigger": confirmed_blob["trigger"],
                "examples": confirmed_blob["examples"],
                "confirmed_at": confirmed_blob["confirmed_at"],
                "source_candidate_id": confirmed_blob["source_candidate_id"],
                "tags": confirmed_blob["tags"],
            },
        )
    finally:
        run(backend.close())

    migrated_backend = LocalMemoryBackend(data_dir)
    run(migrated_backend.init())
    try:
        confirmed_rules = run(migrated_backend.structured_store.list_confirmed_rules("demo"))
        assert len(confirmed_rules) == 1
        assert confirmed_rules[0].source_session_id == "session-backfill-001"
    finally:
        run(migrated_backend.close())


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
