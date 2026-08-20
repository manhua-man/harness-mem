from __future__ import annotations

import asyncio

import pytest

from harness_mem.autopilot_search import plan_autopilot_search
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.mcp import server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def _build():
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        return backend

    backend = asyncio.run(_build())
    server.set_backend_override(backend)
    try:
        yield backend
    finally:
        server.set_backend_override(None)
        asyncio.run(backend.close())


def test_session_start_uses_wake_not_autopilot_search() -> None:
    decision = plan_autopilot_search(
        event_name="before_agent_start",
        current_task="remember the previous convention before editing",
    )

    assert decision.should_search is False
    assert decision.trigger is None
    assert "wake" in decision.reason


def test_context_event_detects_project_convention_uncertainty() -> None:
    decision = plan_autopilot_search(
        event_name="context",
        current_task=(
            "Implement the runtime hook boundary in harness_mem/mcp/tool_specs.py; "
            "not sure about the existing project convention."
        ),
        changed_files=["harness_mem/mcp/tool_specs.py"],
    )

    assert decision.should_search is True
    assert decision.trigger == "project_convention_uncertainty"
    assert decision.query is not None
    assert "harness_mem/mcp/tool_specs.py" in decision.query


def test_save_point_claims_trigger_prewrite_grounding() -> None:
    decision = plan_autopilot_search(
        event_name="prepareNextTurn",
        current_task="Distill accepted project memory after a session.",
        candidate_claims=[
            "The runtime search scheduler only searches on concrete uncertainty.",
        ],
    )

    assert decision.should_search is True
    assert decision.trigger == "prewrite_claim_grounding"
    assert decision.include_history is True


def test_autopilot_tick_skips_duplicate_recent_query() -> None:
    first = plan_autopilot_search(
        event_name="PostToolUse",
        current_task="Fix pytest timeout in Windows harness.",
        tool_name="pytest",
        tool_result="TimeoutError: pytest failed on Windows.",
        is_error=True,
    )
    assert first.should_search is True
    assert first.query is not None

    second = plan_autopilot_search(
        event_name="PostToolUse",
        current_task="Fix pytest timeout in Windows harness.",
        tool_name="pytest",
        tool_result="TimeoutError: pytest failed on Windows.",
        is_error=True,
        recent_queries=[first.query],
    )

    assert second.should_search is False
    assert second.trigger == "tool_failure"
    assert second.reason == "duplicate_recent_search"


def test_mcp_autopilot_tick_executes_search_on_tool_failure(backend) -> None:
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="demo",
                category="bug",
                content=(
                    "pytest Windows timeout prior fix: disable embeddings and "
                    "isolate USERPROFILE before running memory tests."
                ),
                source="test",
                status="user_confirmed",
            )
        )
    )

    payload = server.tool_autopilot_search_tick(
        event_name="PostToolUse",
        project_name="demo",
        current_task="Fix pytest timeout in Windows harness.",
        tool_name="pytest",
        tool_result={"stderr": "TimeoutError: pytest failed on Windows."},
        is_error=True,
    )

    assert payload["success"] is True
    assert payload["search_executed"] is True
    assert payload["decision"]["trigger"] == "tool_failure"
    assert payload["search"]["memory_entry_count"] >= 1
    assert payload["context_injection"]["target"] == "next_context"
    assert payload["context_injection"]["record_outcome_call"]["tool"] == "record_context_outcome"


def test_mcp_autopilot_tick_skips_session_start_even_with_recall_words(backend) -> None:
    payload = server.tool_autopilot_search_tick(
        event_name="SessionStart",
        project_name="demo",
        current_task="Remember the previous convention.",
    )

    assert payload["success"] is True
    assert payload["search_executed"] is False
    assert payload["decision"]["trigger"] is None
    assert "wake" in payload["decision"]["reason"]
