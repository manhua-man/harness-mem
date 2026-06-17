from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands import (
    cmd_correct,
    cmd_confirm_rule,
    cmd_confirm_supersede,
    cmd_confirm_procedural,
    cmd_handoff,
    cmd_record_skill_result,
    cmd_search_skills,
    cmd_suggest_procedural,
    cmd_suggest_supersede,
)
from harness_mem.core.schemas import Observation, RuleCandidate, ConfirmedRule
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.cli


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        cmd_correct(
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

    assert run(cmd_confirm_rule(candidate.id)) == 0

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
    candidate = RuleCandidate(
        project_name="demo",
        session_id="session-backfill-001",
        pattern="Always validate JWT expiry before API calls",
        trigger="Before any authenticated API call",
    )
    _write_json(
        data_dir / "structured" / "rule_candidates" / f"{candidate.id}.json",
        candidate.to_dict(),
    )
    _write_json(
        data_dir / "structured" / "confirmed_rules" / "rule-backfill-001.json",
        {
            "id": "rule-backfill-001",
            "project_name": "demo",
            "pattern": candidate.pattern,
            "trigger": candidate.trigger,
            "examples": [],
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "source_candidate_id": candidate.id,
            "tags": [],
        },
    )

    migrated_backend = LocalMemoryBackend(data_dir)
    run(migrated_backend.init())
    try:
        assert migrated_backend.runtime_state == "bootstrapped_from_legacy"
        confirmed_rules = run(migrated_backend.structured_store.list_confirmed_rules("demo"))
        assert len(confirmed_rules) == 1
        assert confirmed_rules[0].source_session_id == "session-backfill-001"
    finally:
        run(migrated_backend.close())


def test_handoff_update_reuses_existing_record(data_dir: Path):
    assert run(
        cmd_handoff(
            "demo",
            "task-001",
            "Fix auth bug",
            next_steps=["Check JWT validation logic"],
            blockers=["Waiting for token samples"],
        )
    ) == 0

    assert run(
        cmd_handoff(
            "demo",
            "task-001",
            "Fix auth bug follow-up",
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
        assert handoff.summary == "Fix auth bug follow-up"
        assert handoff.status == "blocked"
        assert handoff.next_steps == ["Collect fresh token samples"]
        assert handoff.blockers == ["Need production token sample"]
    finally:
        run(backend.close())


def test_correct_requires_session_in_project(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observation = Observation(
            session_id="session-other-project",
            client="claude-code",
            raw_content="User corrected the agent to validate JWT expiry before authenticated calls.",
            content_type="transcript",
            metadata={"project_name": "other"},
            tags=["session", "correction"],
        )
        run(backend.verbatim_store.save(observation))
    finally:
        run(backend.close())

    assert run(
        cmd_correct(
            "session-other-project",
            "demo",
            "Always validate JWT expiry before API calls",
            "Before any authenticated API call",
        )
    ) == 1

    output = capsys.readouterr().out
    assert "No observations found for session: session-other-project in project: demo" in output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_rule_candidates("demo"))
        assert candidates == []
    finally:
        run(backend.close())


def test_handoff_rejects_invalid_status(data_dir: Path, capsys: pytest.CaptureFixture[str]):
    assert run(
        cmd_handoff(
            "demo",
            "task-001",
            "Fix auth bug",
            status="paused",
        )
    ) == 1

    assert "Invalid handoff status: paused" in capsys.readouterr().out

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        handoffs = run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        assert handoffs == []
    finally:
        run(backend.close())


def test_supersede_cli_marks_old_truth_historical(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_confirmed_rule(
                ConfirmedRule(
                    id="rule-old",
                    project_name="demo",
                    pattern="Use the old route.",
                    trigger="When editing API clients",
                    source_candidate_id="candidate-old",
                )
            )
        )
        run(
            backend.structured_store.save_confirmed_rule(
                ConfirmedRule(
                    id="rule-new",
                    project_name="demo",
                    pattern="Use the new route.",
                    trigger="When editing API clients",
                    source_candidate_id="candidate-new",
                )
            )
        )
    finally:
        run(backend.close())

    assert run(
        cmd_suggest_supersede(
            "demo",
            "confirmed_rule",
            "rule-old",
            "confirmed_rule",
            "rule-new",
            "New route replaces old route",
            "Project docs now point to the new route.",
        )
    ) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_supersede_candidates("demo"))
        assert len(candidates) == 1
        candidate = candidates[0]
    finally:
        run(backend.close())

    assert run(cmd_confirm_supersede(candidate.id)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        old_rule = run(backend.structured_store.get_confirmed_rule("rule-old"))
        new_rule = run(backend.structured_store.get_confirmed_rule("rule-new"))
        supersede = run(backend.structured_store.get_supersede_candidate(candidate.id))
        assert old_rule is not None and old_rule.valid_to is not None
        assert new_rule is not None and new_rule.supersedes == ["rule-old"]
        assert supersede is not None and supersede.status == "accepted"
    finally:
        run(backend.close())


def test_procedural_cli_confirms_searches_and_records_skill(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert run(
        cmd_suggest_procedural(
            "demo",
            "Focused runtime change needs validation",
            [
                "Run focused tests",
                "Run ruff and mypy",
                "Run full pytest",
            ],
            "All checks are green",
            success_examples=["328 passed, 1 skipped"],
            source_session_id="session-proc-cli",
        )
    ) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        candidates = run(backend.structured_store.list_procedural_candidates("demo"))
        assert len(candidates) == 1
        candidate = candidates[0]
    finally:
        run(backend.close())

    assert run(cmd_confirm_procedural(candidate.id)) == 0
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        skills = run(backend.structured_store.list_skills("demo"))
        assert len(skills) == 1
        skill = skills[0]
    finally:
        run(backend.close())

    assert run(cmd_search_skills("demo", "focused validation")) == 0
    search_output = capsys.readouterr().out
    assert "Focused runtime change needs validation" in search_output

    assert run(cmd_record_skill_result(skill.id, success=True)) == 0
    result_output = capsys.readouterr().out
    assert "success_rate=1.0" in result_output
