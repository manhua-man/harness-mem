from __future__ import annotations

import asyncio
import json

import pytest

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.mcp import server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_MEM_MCP_TOOL_PROFILE", raising=False)
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


def _tool_result(response: dict) -> dict:
    assert "error" not in response
    return json.loads(response["result"]["content"][0]["text"])


def test_default_mcp_profile_lists_only_read_prepare_list_detail_tools(
    backend,
) -> None:
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )

    assert response is not None
    result = response["result"]
    tool_names = {tool["name"] for tool in result["tools"]}

    assert result["profile"] == "core-read"
    assert result["profile_source"] == "default"
    assert {
        "wake",
        "search_memory",
        "prepare_session_distill",
        "list_candidates",
        "get_candidate_detail",
    } <= tool_names
    assert "auto_review_candidates" not in tool_names
    assert "suggest_memory_entry" not in tool_names
    assert "suggest_rule" not in tool_names
    assert "suggest_relation_fact" not in tool_names
    assert "create_task_handoff" not in tool_names
    assert "confirm_memory_entry" not in tool_names
    assert "reject_memory_entry" not in tool_names
    assert "confirm_rule" not in tool_names
    assert "reject_rule" not in tool_names
    assert "trace_relations" not in tool_names
    assert "search_raw" not in tool_names
    assert "search_skills" not in tool_names
    assert "get_skill" not in tool_names
    assert "ingest_sessions" not in tool_names
    assert "dream_run" not in tool_names
    assert "metabolism_run" not in tool_names


def test_review_read_profile_exposes_read_drilldowns_without_write_or_labs(
    backend,
) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/list",
            "params": {"mcp_tool_profile": "review-read"},
        }
    )

    assert response is not None
    result = response["result"]
    tool_names = {tool["name"] for tool in result["tools"]}

    assert result["profile"] == "review-read"
    assert {
        "search_memory",
        "trace_relations",
        "search_raw",
        "search_skills",
        "get_skill",
    } <= tool_names
    trace_tool = next(tool for tool in result["tools"] if tool["name"] == "trace_relations")
    assert trace_tool["annotations"]["harness_mem"]["cluster"] == "review_read"
    assert "auto_review_candidates" not in tool_names
    assert "suggest_memory_entry" not in tool_names
    assert "confirm_memory_entry" not in tool_names
    assert "metabolism_run" not in tool_names
    assert "dream_run" not in tool_names


def test_default_mcp_profile_hides_durable_write_tools(backend) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "confirm_memory_entry",
                "arguments": {"entry_id": "mem-1"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["data"]["error_code"] == "HM-MCP-TOOL-HIDDEN"
    assert response["error"]["data"]["profile"] == "core-read"


def test_default_mcp_profile_allows_candidate_detail_read(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="Candidate detail is a read-only review drilldown.",
        source="observation:detail",
        confidence=0.9,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "get_candidate_detail",
                "arguments": {
                    "candidate_id": entry.id,
                    "candidate_kind": "memory_entry",
                },
            },
        }
    )

    payload = _tool_result(response)

    assert payload["success"] is True
    assert payload["candidate_kind"] == "memory_entry"
    assert payload["candidate"]["id"] == entry.id
    assert payload["candidate"]["status"] == "pending"


def test_distill_suggest_profile_exposes_suggest_and_forces_apply_to_preview(
    backend,
) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content=(
            "Use the local SQLite derived index only as a rebuildable read "
            "model while canonical project truth remains in the structured store."
        ),
        source="observation:1",
        confidence=0.9,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "auto_review_candidates",
                "mcp_tool_profile": "distill-suggest",
                "arguments": {"project_name": "demo", "apply": True},
            },
        }
    )

    payload = _tool_result(response)
    reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))

    assert payload["success"] is True
    assert payload["auto_confirmed"] == 1
    assert payload["applied"] is False
    assert payload["applied_decisions"] == []
    assert payload["profile_enforcement"] == {
        "profile": "distill-suggest",
        "reason": "auto_review_apply_requires_review_write_profile",
        "requested_apply": True,
        "effective_apply": False,
    }
    assert reloaded is not None
    assert reloaded.status == "pending"

    listed = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/list",
            "params": {"mcp_tool_profile": "distill-suggest"},
        }
    )
    tool_names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "suggest_memory_entry" in tool_names
    assert "auto_review_candidates" in tool_names
    assert "confirm_memory_entry" not in tool_names


def test_review_write_profile_allows_explicit_confirm(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="Keep review-write as the explicit durable review profile.",
        source="observation:2",
        confidence=0.9,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "confirm_memory_entry",
                "mcp_tool_profile": "review-write",
                "arguments": {"entry_id": entry.id},
            },
        }
    )

    payload = _tool_result(response)
    reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))

    assert payload["success"] is True
    assert payload["status"] == "accepted"
    assert "profile_enforcement" not in payload
    assert reloaded is not None
    assert reloaded.status == "accepted"
