from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.context_sufficiency import assemble_task_aware_context_plan
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.search.retrieval_quality import (
    NoopReranker,
    build_quality_trace,
    build_query_variants,
    duplicate_rate,
    quality_profile_for_query,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def test_retrieval_quality_defaults_to_noop_light_path() -> None:
    profile = quality_profile_for_query(classifier="simple")

    assert profile.reranker_enabled is False
    assert profile.query_rewriting_enabled is False
    assert profile.multi_query_enabled is False
    assert profile.hyde_enabled is False
    assert profile.max_fanout == 1
    assert build_query_variants("plain search", classifier="simple", profile=profile) == [
        "plain search"
    ]
    assert NoopReranker().rerank("plain search", [3, 1, 2]) == [3, 1, 2]


def test_retrieval_quality_fanout_is_bounded_for_insufficiency() -> None:
    trace = build_quality_trace(
        query="why storage v2 then rust core",
        classifier="multi_hop",
        source_ids=["a", "a", "b"],
        insufficient=True,
        insufficiency_queries=["accepted decision ledger", "accepted decision ledger"],
    )

    assert trace.profile.query_rewriting_enabled is True
    assert trace.profile.multi_query_enabled is True
    assert trace.fanout_count <= trace.profile.max_fanout
    assert trace.query_variants[:2] == [
        "why storage v2 then rust core",
        "why storage v2",
    ]
    assert trace.duplicate_rate == duplicate_rate(["a", "a", "b"])
    assert "query variants are deterministic and fanout-capped" in trace.notes


async def _seed_insufficient_plan(backend: LocalMemoryBackend) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-v42-quality",
            project_name="demo",
            category="decision",
            content="storage v2 checksum migration evidence",
            confidence=0.9,
            source="unit",
            created_at=now,
            updated_at=now,
        )
    )


def test_task_aware_plan_records_retrieval_quality_trace(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed_insufficient_plan(backend))

    plan = run(
        assemble_task_aware_context_plan(
            backend,
            project_name="demo",
            query="why storage v2 then rust core",
            current_task="accepted decision ledger",
            budget_tokens=400,
            limit=5,
        )
    )

    quality = plan.iterative_retrieval_trace.retrieval_quality
    assert quality["profile"]["query_rewriting_enabled"] is True
    assert quality["fanout_count"] <= quality["profile"]["max_fanout"]
    assert quality["reranker"] == "noop"
