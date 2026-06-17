from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas.observation import Observation
from harness_mem.search.backend import (
    BackendSearchResult,
    SearchBackendResponse,
    SQLiteSearchBackend,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


async def _seed_observation(backend: LocalMemoryBackend) -> None:
    await backend.verbatim_store.save(
        Observation(
            id="obs-backend-mainline",
            session_id="session-backend-mainline",
            client="pytest",
            raw_content="backend topic match observation",
            content_type="transcript",
            timestamp=datetime(2026, 6, 12, tzinfo=timezone.utc),
            metadata={"project_name": "demo"},
        )
    )


def test_context_assembly_query_layers_consume_backend_response(
    backend: LocalMemoryBackend,
    monkeypatch,
) -> None:
    run(_seed_observation(backend))

    async def _fake_search(self, query, *, filters, mode="auto", limit=20, budget_tokens=None):
        return SearchBackendResponse(
            query=query,
            requested_mode="auto",
            effective_mode="fts",
            results=[
                BackendSearchResult(
                    source_id="mem-backend-mainline",
                    source_kind="memory_entry",
                    score=1.0,
                    preview="backend memory entry preview",
                    metadata={"search_mode": "fts"},
                ),
                BackendSearchResult(
                    source_id="rel-backend-mainline",
                    source_kind="relation_fact",
                    score=0.9,
                    preview="storage implemented_by sqlite",
                    metadata={"search_mode": "fts"},
                ),
                BackendSearchResult(
                    source_id="skill-backend-mainline",
                    source_kind="skill",
                    score=0.8,
                    preview="skill skill-backend-mainline: backend verify | when: validating backend recall",
                    metadata={"search_mode": "fts"},
                ),
                BackendSearchResult(
                    source_id="obs-backend-mainline",
                    source_kind="observation",
                    score=0.7,
                    preview="backend topic match observation",
                    metadata={"search_mode": "fts"},
                ),
            ],
            fallback_metadata={
                "backend": "sqlite",
                "requested_mode": "auto",
                "effective_mode": "fts",
                "fallback_reason": "forced-test",
            },
            budget={"requested_tokens": budget_tokens, "estimated_tokens": 50, "result_limit": limit},
            truncation={"available": 4, "included": 4, "dropped": 0, "truncated": False},
            source_coverage={
                "memory_entry": 1,
                "relation_fact": 1,
                "skill": 1,
                "observation": 1,
            },
            drilldown_hints=[],
        )

    monkeypatch.setattr(SQLiteSearchBackend, "search", _fake_search)

    plan = run(assemble_context_plan(backend, project_name="demo", query="backend"))
    l3 = plan.layer("L3")
    l4 = plan.layer("L4")

    assert [entry.source_ids[0] for entry in l3.entries] == [
        "mem-backend-mainline",
        "rel-backend-mainline",
        "skill-backend-mainline",
    ]
    assert [entry.why_included for entry in l3.entries] == [
        "topic_recall:search_memory",
        "topic_recall:relation_fact",
        "topic_recall:skill",
    ]
    topic_match_ids = [
        entry.source_ids[0]
        for entry in l4.entries
        if entry.why_included == "evidence:topic_match"
    ]
    assert topic_match_ids == ["obs-backend-mainline"]
