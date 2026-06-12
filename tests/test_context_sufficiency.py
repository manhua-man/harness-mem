from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.context_sufficiency import assemble_task_aware_context_plan
from harness_mem.core.schemas.context_sufficiency import (
    ContextPlan,
    CorpusProfile,
    MetadataFilter,
    build_retrieval_plan,
    deterministic_query_rewrites,
    evaluate_sufficiency,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.search.backend import BackendSearchResult
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def test_v41_schema_round_trip() -> None:
    plan = build_retrieval_plan(
        query="compare storage v2 across corpora",
        project_name="demo",
        corpus_profiles=[
            CorpusProfile(
                corpus_id="truth",
                description="confirmed truth",
                entities=["Storage v2"],
                source_types=["memory_entry"],
            )
        ],
        metadata_filter=MetadataFilter(project_id="demo", corpus_id="truth"),
        budget_tokens=1200,
        deep_recall=True,
    )

    payload = plan.to_dict()
    restored = type(plan).from_dict(payload)

    assert restored.classifier == "cross_corpus"
    assert restored.corpora == ["truth"]
    assert restored.filters.tiers == ["hot", "warm", "cold", "archive"]


def test_sufficiency_reports_missing_and_direct_support() -> None:
    missing = evaluate_sufficiency(query="storage v2 checksum", results=[])
    assert missing.status == "insufficient"
    assert missing.safe_to_answer is False
    assert missing.missing_evidence

    direct = evaluate_sufficiency(
        query="storage v2 checksum",
        results=[
            BackendSearchResult(
                source_id="mem-1",
                source_kind="memory_entry",
                score=1.0,
                preview="storage v2 checksum migration evidence",
                metadata={"truth_status": "accepted"},
            )
        ],
    )
    assert direct.status == "sufficient"
    assert direct.support_level == "direct"
    assert direct.safe_to_answer is True


def test_v41x_retrieval_plan_records_rewrites_and_slot_gate() -> None:
    plan = build_retrieval_plan(
        query="compare storage v2 and rust core current behavior",
        project_name="demo",
    )

    assert plan.classifier in {"cross_corpus", "multi_hop", "temporal"}
    assert plan.query_rewrites
    assert "required_slots" in plan.quality_gates
    assert deterministic_query_rewrites(
        "why storage v2 then rust core",
        classifier="multi_hop",
    )[:2] == [
        "why storage v2 then rust core",
        "why storage v2",
    ]

    report = evaluate_sufficiency(
        query="storage v2 rust core",
        required_slots=["accepted decision ledger"],
        results=[
            BackendSearchResult(
                source_id="mem-slot",
                source_kind="memory_entry",
                score=1.0,
                preview="storage v2 checksum migration evidence",
                metadata={"truth_status": "accepted"},
            )
        ],
    )

    assert report.status == "insufficient"
    assert report.safe_to_answer is False
    assert report.missing_evidence == ["accepted decision ledger"]
    assert report.checks["missing_required_slots"] == ["accepted decision ledger"]


async def _seed(backend: LocalMemoryBackend) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-v41",
            project_name="demo",
            category="decision",
            content="task aware wake includes storage v2 checksum evidence",
            confidence=0.9,
            source="unit",
            created_at=now,
            updated_at=now,
        )
    )


def test_task_aware_context_plan_is_bounded_and_read_only(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))

    plan = run(
        assemble_task_aware_context_plan(
            backend,
            project_name="demo",
            query="storage v2 checksum",
            current_task="storage v2 checksum evidence",
            budget_tokens=400,
            limit=5,
        )
    )
    payload = plan.to_dict()
    restored = ContextPlan.from_dict(payload)

    assert restored.context_sufficiency.status == "sufficient"
    assert restored.wake_packet.budget_trace["requested"] == 400
    assert restored.iterative_retrieval_trace.rounds
    assert "mem-v41" in restored.source_ids
