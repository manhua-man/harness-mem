from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.mcp import server as mcp_server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


async def _seed(backend: LocalMemoryBackend) -> None:
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
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
    assert result["context_sufficiency"]["status"] in {
        "sufficient",
        "partial",
        "insufficient",
    }
