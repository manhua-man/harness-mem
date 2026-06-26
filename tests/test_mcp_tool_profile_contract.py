from __future__ import annotations

import asyncio
import json

import pytest

from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.mcp import server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


SKILL_GOVERNANCE_TOOLS = {
    "suggest_skill",
    "confirm_skill",
    "reject_skill",
    "suggest_skill_promotion",
    "confirm_skill_promotion",
    "reject_skill_promotion",
    "record_skill_result",
    "detect_skill_improvements",
    "confirm_skill_revision",
    "reject_skill_revision",
    "detect_skill_deprecations",
    "confirm_skill_deprecation",
    "reject_skill_deprecation",
}


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


def _listed_tool_names(params: dict | None = None) -> tuple[dict, set[str]]:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": params or {},
        }
    )
    assert response is not None
    result = response["result"]
    return result, {tool["name"] for tool in result["tools"]}


def test_public_mcp_surface_is_single_memory_entrypoint(backend) -> None:
    result, tool_names = _listed_tool_names()

    assert result["profile"] == "memory"
    assert result["profile_source"] == "single-public-surface"
    assert result["degraded_reason"] is None
    assert {
        "wake",
        "search_memory",
        "prepare_session_distill",
        "auto_review_candidates",
        "list_candidates",
        "get_candidate_detail",
        "suggest_memory_entry",
        "suggest_rule",
        "suggest_relation_fact",
        "confirm_memory_entry",
        "reject_memory_entry",
        "confirm_rule",
        "reject_rule",
        "confirm_relation_fact",
        "reject_relation_fact",
        "dream_ledger",
        "dream_run",
        "dream_auto_tick",
        "undo_dream_item",
    } <= tool_names
    assert "metabolism_run" not in tool_names
    assert "health_summary" not in tool_names
    assert not SKILL_GOVERNANCE_TOOLS.intersection(tool_names)


def test_historical_profile_requests_do_not_expand_mcp_surface(backend) -> None:
    default_result, default_names = _listed_tool_names()
    requested_result, requested_names = _listed_tool_names({"mcp_tool_profile": "full"})

    assert requested_result["profile"] == "memory"
    assert requested_result["profile_source"] == "single-public-surface"
    assert requested_result["degraded_reason"] == "profile_ignored_single_public_surface"
    assert requested_names == default_names
    assert "suggest_skill" not in requested_names
    assert default_result["tool_count"] == requested_result["tool_count"]


def test_skill_governance_is_not_registered_as_mcp_public_tools(backend) -> None:
    assert not SKILL_GOVERNANCE_TOOLS.intersection(server.TOOLS)
    for name in SKILL_GOVERNANCE_TOOLS:
        assert not hasattr(server, f"tool_{name}")

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "suggest_skill",
                "arguments": {
                    "project_name": "demo",
                    "activation_condition": "When a workflow repeats",
                    "steps": ["Run a dedicated skill optimizer"],
                    "termination_condition": "The skill inventory is reviewed",
                },
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Unknown tool: suggest_skill"


def test_mcp_keeps_only_read_only_procedural_skill_hints(backend) -> None:
    _result, tool_names = _listed_tool_names()

    assert {"search_skills", "get_skill"} <= tool_names
    assert not SKILL_GOVERNANCE_TOOLS.intersection(tool_names)


def test_non_public_maintenance_tool_call_is_hidden(backend) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "metabolism_run",
                "arguments": {"project_name": "demo"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["data"]["error_code"] == "HM-MCP-TOOL-HIDDEN"
    assert response["error"]["data"]["profile"] == "memory"


def test_public_auto_review_forces_apply_to_preview(backend) -> None:
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
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "auto_review_candidates",
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
        "profile": "memory",
        "reason": "auto_review_apply_is_preview_only_on_public_mcp",
        "requested_apply": True,
        "effective_apply": False,
    }
    assert reloaded is not None
    assert reloaded.status == "pending"


def test_public_confirm_remains_explicit_review_gate(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="The public MCP surface can confirm only through explicit review tools.",
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


def test_public_candidate_detail_is_limited_to_memory_review_kinds(backend) -> None:
    schema = server.TOOLS["get_candidate_detail"]["input_schema"]
    kind_enum = schema["properties"]["candidate_kind"]["enum"]

    assert "memory_entry" in kind_enum
    assert "procedural_candidate" not in kind_enum
    assert "skill_promotion_candidate" not in kind_enum
    assert "skill_revision_candidate" not in kind_enum
    assert "skill_deprecation_candidate" not in kind_enum


def test_dream_auto_is_enabled_by_default_config() -> None:
    assert MergedConfig().dream_auto_enabled is True
    assert MergedConfig().to_reflection_config()["dream"]["auto"]["enabled"] is True
