from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, RuleCandidate, TaskHandoff
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


def test_memory_entry_roundtrip_search_and_soft_delete(store: LocalStructuredStore):
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="Use SQLite FTS5 for local memory search",
        source="manual",
        tags=["search"],
    )

    assert run(store.save_memory_entry(entry)) == entry.id
    assert run(store.get_memory_entry(entry.id)) == entry

    listed = run(store.list_memory_entries("demo"))
    assert [item.id for item in listed] == [entry.id]

    searched = run(store.search_memory_entries("FTS5 local memory", project_name="demo", mode="fts"))
    assert [item.id for item in searched] == [entry.id]

    accessed_at = datetime.now(timezone.utc)
    assert run(store.touch_memory_entry(entry.id, accessed_at=accessed_at)) is True
    touched = run(store.get_memory_entry(entry.id))
    assert touched is not None
    assert touched.usage_count == 1
    assert touched.last_accessed_at == accessed_at

    assert run(store.soft_delete_memory_entry(entry.id)) is True
    assert run(store.get_memory_entry(entry.id)).compacted is True
    assert run(store.list_memory_entries("demo")) == []
    assert run(store.search_memory_entries("FTS5 local memory", project_name="demo", mode="fts")) == []
    assert run(store.touch_memory_entry("missing")) is False


def test_task_handoffs_are_project_scoped_and_ordered_by_activity(store: LocalStructuredStore):
    older = TaskHandoff(
        project_name="demo",
        task_id="task-old",
        summary="Older task",
        last_activity=datetime.now(timezone.utc) - timedelta(days=1),
    )
    newer = TaskHandoff(
        project_name="demo",
        task_id="task-new",
        summary="Newer task",
        last_activity=datetime.now(timezone.utc),
    )
    other_project = TaskHandoff(
        project_name="other",
        task_id="task-other",
        summary="Other project task",
        last_activity=datetime.now(timezone.utc) + timedelta(days=1),
    )

    assert run(store.save_task_handoff(older)) == older.id
    assert run(store.save_task_handoff(newer)) == newer.id
    assert run(store.save_task_handoff(other_project)) == other_project.id

    handoffs = run(store.get_latest_handoffs("demo", limit=10))
    assert [handoff.task_id for handoff in handoffs] == ["task-new", "task-old"]


def test_rule_candidate_status_updates_blob_and_index(store: LocalStructuredStore):
    candidate = RuleCandidate(
        project_name="demo",
        session_id="session-001",
        pattern="Always validate JWT expiry",
        trigger="Before authenticated API calls",
    )

    assert run(store.save_rule_candidate(candidate)) == candidate.id
    assert [item.id for item in run(store.list_rule_candidates("demo", status="pending"))] == [candidate.id]

    assert run(store.update_rule_candidate_status(candidate.id, "accepted")) is True
    updated = run(store.get_rule_candidate(candidate.id))
    assert updated is not None
    assert updated.status == "accepted"
    assert run(store.list_rule_candidates("demo", status="pending")) == []
    assert [item.id for item in run(store.list_rule_candidates("demo", status="accepted"))] == [candidate.id]


def test_confirmed_rules_roundtrip_with_source_session(store: LocalStructuredStore):
    rule = ConfirmedRule(
        project_name="demo",
        pattern="Always validate JWT expiry",
        trigger="Before authenticated API calls",
        source_candidate_id="candidate-001",
        source_session_id="session-001",
        tags=["auth"],
    )

    assert run(store.save_confirmed_rule(rule)) == rule.id

    loaded = run(store.get_confirmed_rule(rule.id))
    assert loaded is not None
    assert loaded.source_session_id == "session-001"

    listed = run(store.list_confirmed_rules("demo"))
    assert [item.id for item in listed] == [rule.id]
