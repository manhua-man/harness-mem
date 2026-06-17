from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import server as mcp_server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


async def _seed(backend: LocalMemoryBackend) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    await backend.verbatim_store.save(
        Observation(
            id="obs-mcp-v41",
            session_id="session-mcp-v41",
            client="pytest",
            raw_content="context sufficiency raw observation for storage v2 evidence",
            content_type="transcript",
            timestamp=now,
            metadata={"project_name": "demo"},
        )
    )
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            id="mem-mcp-v41",
            project_name="demo",
            category="decision",
            content="context sufficiency surfaces storage v2 evidence",
            confidence=0.9,
            source="unit",
            created_at=now,
            updated_at=now,
            provenance={"observation_ids": ["obs-mcp-v41"]},
        )
    )


def test_mcp_search_memory_returns_context_sufficiency(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))
    mcp_server.set_backend_override(backend)
    try:
        result = mcp_server.tool_search_memory(
            query="context sufficiency storage v2 evidence",
            project_name="demo",
            mode="fts",
            task="storage v2 evidence",
            budget_tokens=500,
        )
    finally:
        mcp_server.set_backend_override(None)

    assert result["context_sufficiency"]["status"] == "sufficient"
    assert result["retrieval_plan"]["budget_tokens"] == 500
    assert result["context_plan"]["wake_packet"]["budget_trace"]["requested"] == 500
    assert result["effective_deep_recall"] is False
    assert "background_evidence_expansion" in result["orchestration_actions"]
    assert result["answer_ready_context"]["safe_to_answer"] is True
    assert result["answer_ready_context"]["supporting_evidence"]
    assert result["iterative_retrieval_trace"]["stopped_reason"] in {
        "sufficient",
        "budget_or_evidence_limit",
    }


def test_mcp_wake_returns_task_aware_packet(backend: LocalMemoryBackend) -> None:
    run(_seed(backend))
    mcp_server.set_backend_override(backend)
    try:
        result = mcp_server.tool_wake(
            project_name="demo",
            no_auto_ingest=True,
            current_task="storage v2 evidence",
            budget_tokens=700,
        )
    finally:
        mcp_server.set_backend_override(None)

    assert result["success"] is True
    assert "output" in result
    assert result["wake_packet"]["budget_tokens"] == 700
    assert result["effective_deep_recall"] is False
    assert "background_evidence_expansion" in result["orchestration_actions"]
    assert result["answer_ready_context"]["supporting_evidence"]
    assert result["context_sufficiency"]["status"] in {
        "sufficient",
        "partial",
        "insufficient",
    }


def test_mcp_search_and_wake_share_backend_runtime_metadata(
    backend: LocalMemoryBackend,
) -> None:
    run(_seed(backend))
    mcp_server.set_backend_override(backend)
    try:
        search_result = mcp_server.tool_search_memory(
            query="storage v2 evidence",
            project_name="demo",
            task="storage v2 evidence",
            budget_tokens=500,
        )
        wake_result = mcp_server.tool_wake(
            project_name="demo",
            no_auto_ingest=True,
            current_task="storage v2 evidence",
            budget_tokens=500,
        )
    finally:
        mcp_server.set_backend_override(None)

    assert search_result["requested_mode"] == wake_result["requested_mode"] == "auto"
    assert search_result["effective_mode"] == wake_result["effective_mode"]
    assert search_result["fallback_reason"] == wake_result["fallback_reason"]
    assert search_result["backend_budget"]["requested_tokens"] == 500
    assert wake_result["backend_budget"]["requested_tokens"] == 500
    assert search_result["backend_truncation"] == wake_result["backend_truncation"]
    assert search_result["source_coverage"] == wake_result["source_coverage"]
    assert search_result["effective_deep_recall"] is False
    assert wake_result["effective_deep_recall"] is False


def test_mcp_search_memory_auto_deep_recall_for_history_shaped_query(
    backend: LocalMemoryBackend,
) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-history",
                session_id="session-history",
                client="pytest",
                raw_content="previous rollout archive evidence for the legacy flow",
                content_type="transcript",
                timestamp=now,
                metadata={"project_name": "demo"},
            )
        )
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="mem-archive",
                project_name="demo",
                category="decision",
                content="previous rollout archive evidence for the legacy flow",
                confidence=0.9,
                source="unit",
                created_at=now,
                updated_at=now,
                tier="archive",
                provenance={"observation_ids": ["obs-history"]},
            )
        )
    )
    mcp_server.set_backend_override(backend)
    try:
        result = mcp_server.tool_search_memory(
            query="previous rollout archive evidence",
            project_name="demo",
            task="what changed before the rollout",
            budget_tokens=600,
        )
    finally:
        mcp_server.set_backend_override(None)

    assert result["effective_deep_recall"] is True
    assert "auto_deep_recall" in result["orchestration_actions"]
    assert result["answer_ready_context"]["effective_deep_recall"] is True
    assert any(entry["id"] == "mem-archive" for entry in result["memory_entries"])
