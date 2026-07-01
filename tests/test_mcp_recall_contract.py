from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.recall_result import RECALL_RESULT_SCHEMA_VERSION
from harness_mem.core.schemas.relation_fact import RelationFact
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
                status="user_confirmed",
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
    assert payload["recall"]["schema_version"] == RECALL_RESULT_SCHEMA_VERSION
    assert payload["recall"]["status"] in {"partial", "answered"}
    assert [step["tier"] for step in payload["recall"]["steps"]] == [
        "filter",
        "fts",
        "vector",
        "merge",
        "hydrate",
        "context",
    ]
    assert payload["recall"]["steps"][0]["metadata"]["current_only_default"] is True
    assert payload["recall"]["steps"][2]["status"] == "skipped"
    evidence = payload["recall"]["evidence"][0]
    assert evidence["source_kind"] == "memory_entry"
    assert "score_details" in evidence["metadata"]
    assert evidence["metadata"]["score_details"]["fts_score"] is not None
    assert evidence["metadata"]["score_details"]["confidence_tier"] in {
        "low",
        "medium",
        "high",
    }


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
                status="user_confirmed",
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


def test_mcp_search_memory_deep_recall_surfaces_history_opt_in(backend) -> None:
    import asyncio

    past = datetime.now(timezone.utc) - timedelta(days=1)
    entry_id = asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpdeeprecalltoken historical memory",
                source="test",
                status="user_confirmed",
                valid_to=past,
            )
        )
    )

    default_payload = server.tool_search_memory(
        query="mcpdeeprecalltoken",
        project_name="demo",
    )
    deep_payload = server.tool_search_memory(
        query="mcpdeeprecalltoken",
        project_name="demo",
        deep_recall=True,
    )

    assert default_payload["memory_entries"] == []
    assert [entry["id"] for entry in deep_payload["memory_entries"]] == [entry_id]
    assert deep_payload["recall"]["evidence"][0]["metadata"]["valid_to"] is not None


def test_mcp_confirm_supersede_writes_audit_and_links_truth(backend) -> None:
    import asyncio

    old_id = asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpsupersedetoken old decision",
                source="test",
                status="user_confirmed",
            )
        )
    )
    new_id = asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="decision",
                content="mcpsupersedetoken new decision",
                source="test",
                status="user_confirmed",
            )
        )
    )

    suggested = server.tool_suggest_supersede(
        project_name="demo",
        target_type="memory_entry",
        target_id=old_id,
        replacement_type="memory_entry",
        replacement_id=new_id,
        reason="New decision replaces old decision.",
        evidence="test evidence",
    )
    confirmed = server.tool_confirm_supersede(suggested["candidate_id"])

    old_entry = asyncio.run(backend.structured_store.get_memory_entry(old_id))
    new_entry = asyncio.run(backend.structured_store.get_memory_entry(new_id))
    events = list(iter_state_events(backend.data_dir, project_name="demo"))

    assert confirmed["success"] is True
    assert confirmed["status"] == "user_confirmed"
    assert old_entry is not None
    assert old_entry.valid_to is not None
    assert old_entry.superseded_by == [new_id]
    assert new_entry is not None
    assert new_entry.supersedes == [old_id]
    assert [event["type"] for event in events] == [
        "candidate_created",
        "supersede_completed",
    ]
    assert [event["target_id"] for event in events] == [
        suggested["candidate_id"],
        suggested["candidate_id"],
    ]
