from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.skill import Skill
from harness_mem.event_log import iter_state_events
from harness_mem.mcp import server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def _build():
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        return backend

    import asyncio

    backend = asyncio.run(_build())
    server.set_backend_override(backend)
    try:
        yield backend
    finally:
        server.set_backend_override(None)
        asyncio.run(backend.close())


def test_search_memory_adds_recall_without_removing_legacy_arrays(backend) -> None:
    import asyncio

    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="Use SQLite for local-first memory.",
                source="test",
                status="accepted",
            )
        )
    )

    payload = server.tool_search_memory(
        query="SQLite local-first",
        project_name="demo",
    )

    assert "memory_entries" in payload
    assert "relation_facts" in payload
    assert "observations" in payload
    assert payload["recall"]["contract"] == "harness_mem.recall_result"
    assert payload["recall"]["status"] in {"partial", "answered"}
    assert payload["recall"]["evidence"][0]["source_kind"] == "memory_entry"


def test_trace_relations_adds_weighted_recall(backend) -> None:
    import asyncio

    asyncio.run(
        backend.structured_store.save_relation_fact(
            RelationFact(
                project_name="demo",
                source_entity="incident",
                target_entity="root_cause",
                relation_type="caused_by",
                evidence="Incident was caused by root cause.",
                source="test",
                confidence=0.9,
                status="accepted",
            )
        )
    )

    payload = server.tool_trace_relations(
        project_name="demo",
        source_entity="incident",
    )

    assert payload["path_count"] == 1
    assert payload["paths"][0]["score"] > 0
    assert payload["paths"][0]["edges"][0]["relation_family"] == "causal"
    assert payload["recall"]["contract"] == "harness_mem.recall_result"
    assert payload["recall"]["evidence"][0]["source_kind"] == "relation_fact"


def test_mcp_review_writes_state_audit_events(backend) -> None:
    suggested = server.tool_suggest_memory_entry(
        project_name="demo",
        category="decision",
        content="State audit events are append-only.",
        source="test",
    )
    confirmed = server.tool_confirm_memory_entry(suggested["entry_id"])

    events = list(iter_state_events(backend.data_dir, project_name="demo"))

    assert suggested["state_event_id"]
    assert confirmed["state_event_id"]
    assert [event["type"] for event in events] == [
        "candidate_created",
        "truth_confirmed",
    ]
    assert [event["target_id"] for event in events] == [
        suggested["entry_id"],
        suggested["entry_id"],
    ]


def test_mcp_skill_lifecycle_writes_state_audit_events(backend) -> None:
    suggested = server.tool_suggest_skill(
        project_name="demo",
        activation_condition="When release checks fail",
        steps=["Inspect failing check", "Patch the smallest broken path"],
        termination_condition="All checks pass",
        source_session_id="session-1",
    )
    confirmed = server.tool_confirm_skill(suggested["candidate_id"])
    rejected_suggestion = server.tool_suggest_skill(
        project_name="demo",
        activation_condition="When an obsolete workflow appears",
        steps=["Do not use the obsolete workflow"],
        termination_condition="Workflow is ignored",
    )
    rejected = server.tool_reject_skill(rejected_suggestion["candidate_id"])

    promotion = server.tool_suggest_skill_promotion(
        confirmed["skill"]["id"],
        "workspace",
    )
    promoted = server.tool_confirm_skill_promotion(promotion["candidate_id"])
    rejected_promotion = server.tool_suggest_skill_promotion(
        confirmed["skill"]["id"],
        "global",
    )
    promotion_rejected = server.tool_reject_skill_promotion(
        rejected_promotion["candidate_id"],
    )

    assert suggested["state_event_id"]
    assert confirmed["state_event_id"]
    assert rejected["state_event_id"]
    assert promotion["state_event_id"]
    assert promoted["state_event_id"]
    assert promotion_rejected["state_event_id"]

    surfaces = {
        event["source_surface"]
        for event in iter_state_events(backend.data_dir, project_name="demo")
    }
    assert {
        "mcp.suggest_skill",
        "mcp.confirm_skill",
        "mcp.reject_skill",
        "mcp.suggest_skill_promotion",
        "mcp.confirm_skill_promotion",
        "mcp.reject_skill_promotion",
    } <= surfaces


def test_mcp_skill_review_suggestions_write_state_audit_events(backend) -> None:
    import asyncio

    suggested = server.tool_suggest_skill(
        project_name="demo",
        activation_condition="When a repeated repair fails",
        steps=["Run the repair", "Record the result"],
        termination_condition="Repair result is known",
    )
    confirmed = server.tool_confirm_skill(suggested["candidate_id"])
    skill_id = confirmed["skill"]["id"]
    for _ in range(5):
        assert server.tool_record_skill_result(skill_id, success=False)["success"]

    improvement = server.tool_detect_skill_improvements("demo", limit=1)
    revision_confirmed = server.tool_confirm_skill_revision(
        improvement["candidate_ids"][0],
    )
    second_improvement = server.tool_detect_skill_improvements("demo", limit=1)
    revision_rejected = server.tool_reject_skill_revision(
        second_improvement["candidate_ids"][0],
    )

    old = datetime.now(timezone.utc) - timedelta(days=90)
    shared_skill = Skill(
        project_name="demo",
        name="Old shared workflow",
        activation_condition="When stale shared guidance appears",
        steps=["Prefer newer project guidance"],
        termination_condition="Stale guidance is retired",
        scope="workspace",
        origin_project="demo",
        created_at=old,
        updated_at=old,
    )
    asyncio.run(backend.structured_store.save_skill(shared_skill))
    deprecation = server.tool_detect_skill_deprecations("demo", limit=1, stale_days=30)
    deprecation_confirmed = server.tool_confirm_skill_deprecation(
        deprecation["candidate_ids"][0],
    )
    second_shared_skill = Skill(
        project_name="demo",
        name="Second old shared workflow",
        activation_condition="When another stale shared guidance appears",
        steps=["Prefer the replacement guidance"],
        termination_condition="Second stale guidance is reviewed",
        scope="workspace",
        origin_project="demo",
        created_at=old,
        updated_at=old,
    )
    asyncio.run(backend.structured_store.save_skill(second_shared_skill))
    second_deprecation = server.tool_detect_skill_deprecations(
        "demo",
        limit=1,
        stale_days=30,
    )
    deprecation_rejected = server.tool_reject_skill_deprecation(
        second_deprecation["candidate_ids"][0],
    )

    assert improvement["state_event_ids"]
    assert revision_confirmed["state_event_id"]
    assert second_improvement["state_event_ids"]
    assert revision_rejected["state_event_id"]
    assert deprecation["state_event_ids"]
    assert deprecation_confirmed["state_event_id"]
    assert second_deprecation["state_event_ids"]
    assert deprecation_rejected["state_event_id"]

    surfaces = {
        event["source_surface"]
        for event in iter_state_events(backend.data_dir, project_name="demo")
    }
    assert {
        "mcp.detect_skill_improvements",
        "mcp.confirm_skill_revision",
        "mcp.reject_skill_revision",
        "mcp.detect_skill_deprecations",
        "mcp.confirm_skill_deprecation",
        "mcp.reject_skill_deprecation",
    } <= surfaces
