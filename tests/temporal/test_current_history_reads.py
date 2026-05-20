from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands import candidates as candidates_command
from harness_mem.commands import search as search_command
from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, RelationFact
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

pytestmark = pytest.mark.storage


@pytest.fixture
def store(tmp_path: Path):
    local_store = LocalStructuredStore(tmp_path)
    try:
        yield local_store
    finally:
        local_store.close()


def test_temporal_fields_round_trip_and_legacy_defaults():
    created_at = datetime(2026, 5, 20, tzinfo=timezone.utc)
    legacy_entry = MemoryEntry.from_dict(
        {
            "id": "legacy-entry",
            "project_name": "demo",
            "category": "decision",
            "content": "Use React for the dashboard.",
            "source": "manual",
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "tags": [],
        }
    )

    assert legacy_entry.valid_from == created_at
    assert legacy_entry.recorded_at == created_at
    assert legacy_entry.valid_to is None
    assert legacy_entry.supersedes == []
    assert legacy_entry.superseded_by == []

    payload = legacy_entry.to_dict()
    assert payload["valid_from"] == created_at.isoformat()
    assert payload["recorded_at"] == created_at.isoformat()


def test_memory_entries_default_current_only_and_include_history(
    store: LocalStructuredStore,
):
    now = datetime.now(timezone.utc)
    current = MemoryEntry(
        id="current-entry",
        project_name="demo",
        category="decision",
        content="Current rule uses React.",
        source="manual",
    )
    historical = MemoryEntry(
        id="historical-entry",
        project_name="demo",
        category="decision",
        content="Historical rule used Vue.",
        source="manual",
        valid_to=now - timedelta(days=1),
        superseded_by=["current-entry"],
    )

    run(store.save_memory_entry(current))
    run(store.save_memory_entry(historical))

    listed = run(store.list_memory_entries("demo", limit=10))
    assert [entry.id for entry in listed] == ["current-entry"]

    with_history = run(
        store.list_memory_entries("demo", limit=10, include_history=True)
    )
    assert {entry.id for entry in with_history} == {
        "current-entry",
        "historical-entry",
    }

    search_default = run(store.search_memory_entries("rule", "demo", mode="fts"))
    assert [entry.id for entry in search_default] == ["current-entry"]

    search_history = run(
        store.search_memory_entries(
            "rule",
            "demo",
            mode="fts",
            include_history=True,
        )
    )
    assert {entry.id for entry in search_history} == {
        "current-entry",
        "historical-entry",
    }


def test_confirmed_rules_and_relation_facts_default_current_only(
    store: LocalStructuredStore,
):
    now = datetime.now(timezone.utc)
    current_rule = ConfirmedRule(
        id="rule-current",
        project_name="demo",
        pattern="Use the current API route.",
        trigger="When editing API clients",
        source_candidate_id="candidate-current",
    )
    old_rule = ConfirmedRule(
        id="rule-old",
        project_name="demo",
        pattern="Use the old API route.",
        trigger="When editing API clients",
        source_candidate_id="candidate-old",
        valid_to=now - timedelta(days=1),
        superseded_by=["rule-current"],
    )
    current_fact = RelationFact(
        id="fact-current",
        project_name="demo",
        source_entity="Frontend",
        target_entity="React",
        relation_type="uses",
        evidence="Current frontend uses React.",
        source="manual",
    )
    old_fact = RelationFact(
        id="fact-old",
        project_name="demo",
        source_entity="Frontend",
        target_entity="Vue",
        relation_type="uses",
        evidence="Historical frontend used Vue.",
        source="manual",
        valid_to=now - timedelta(days=1),
        superseded_by=["fact-current"],
    )

    run(store.save_confirmed_rule(current_rule))
    run(store.save_confirmed_rule(old_rule))
    run(store.save_relation_fact(current_fact))
    run(store.save_relation_fact(old_fact))

    assert [rule.id for rule in run(store.list_confirmed_rules("demo"))] == [
        "rule-current"
    ]
    assert {
        rule.id
        for rule in run(store.list_confirmed_rules("demo", include_history=True))
    } == {"rule-current", "rule-old"}

    assert [fact.id for fact in run(store.list_relation_facts("demo"))] == [
        "fact-current"
    ]
    assert {
        fact.id
        for fact in run(store.list_relation_facts("demo", include_history=True))
    } == {"fact-current", "fact-old"}

    searched = run(store.search_relation_facts("frontend", "demo"))
    assert [fact.id for fact in searched] == ["fact-current"]


def test_cli_include_history_marks_historical_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    try:
        now = datetime.now(timezone.utc)
        current = MemoryEntry(
            id="cli-current-entry",
            project_name="demo",
            category="decision",
            content="Current CLI temporal sentinel uses React.",
            source="manual",
        )
        historical = MemoryEntry(
            id="cli-historical-entry",
            project_name="demo",
            category="decision",
            content="Historical CLI temporal sentinel used Vue.",
            source="manual",
            valid_to=now - timedelta(days=1),
            superseded_by=["cli-current-entry"],
        )
        old_rule = ConfirmedRule(
            id="cli-rule-old",
            project_name="demo",
            pattern="Historical CLI temporal rule used the old route.",
            trigger="When checking CLI temporal history",
            source_candidate_id="candidate-old",
            valid_to=now - timedelta(days=1),
            superseded_by=["cli-rule-current"],
        )
        run(backend.structured_store.save_memory_entry(current))
        run(backend.structured_store.save_memory_entry(historical))
        run(backend.structured_store.save_confirmed_rule(old_rule))

        monkeypatch.setattr(search_command, "DEFAULT_DATA_DIR", tmp_path)
        assert run(
            search_command.cmd_search(
                "demo",
                "temporal sentinel",
                "fts",
            )
        ) == 0
        default_out = capsys.readouterr().out
        assert "Historical CLI temporal sentinel" not in default_out

        assert run(
            search_command.cmd_search(
                "demo",
                "temporal sentinel",
                "fts",
                include_history=True,
            )
        ) == 0
        history_out = capsys.readouterr().out
        assert "Historical CLI temporal sentinel" in history_out
        assert "[historical valid_to=" in history_out

        monkeypatch.setattr(
            candidates_command.command_support,
            "DEFAULT_DATA_DIR",
            tmp_path,
        )
        assert run(
            candidates_command.cmd_confirmed_rules(
                "demo",
                include_history=True,
            )
        ) == 0
        rules_out = capsys.readouterr().out
        assert "Historical CLI temporal rule" in rules_out
        assert "[historical valid_to=" in rules_out
    finally:
        run(backend.close())
