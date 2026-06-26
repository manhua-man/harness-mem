from __future__ import annotations

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
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
