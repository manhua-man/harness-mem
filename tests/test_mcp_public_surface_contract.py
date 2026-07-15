from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from harness_mem.config.merge import MergedConfig
import harness_mem.commands.support as support_module
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import server
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


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

EXPECTED_PUBLIC_MCP_TOOLS = {
    "autopilot_search_tick",
    "auto_review_candidates",
    "confirm_memory_entry",
    "confirm_relation_fact",
    "confirm_rule",
    "confirm_supersede",
    "create_rule_candidate",
    "create_task_handoff",
    "dream_auto_tick",
    "dream_ledger",
    "dream_run",
    "file_context",
    "finalize_session_distill",
    "get_candidate_detail",
    "get_confirmed_rules",
    "get_observations",
    "get_project_profile",
    "get_project_status",
    "get_skill",
    "get_task_handoffs",
    "list_candidates",
    "prepare_session_distill",
    "record_context_outcome",
    "reject_memory_entry",
    "reject_relation_fact",
    "reject_rule",
    "reject_supersede",
    "search_memory",
    "search_raw",
    "search_skills",
    "suggest_correction",
    "suggest_memory_entry",
    "suggest_relation_fact",
    "suggest_rule",
    "suggest_supersede",
    "submit_distill_chunk",
    "temporal_query",
    "timeline",
    "trace_relations",
    "undo_dream_item",
    "wake",
}


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    monkeypatch.delenv("HARNESS_MEM_MCP_MAINTENANCE", raising=False)

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


def test_initialize_adopts_workspace_and_installs_recognized_host_hooks(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "cursor-workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    data_dir = tmp_path / "data"
    installs: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.setenv("HARNESS_MEM_PROJECT_ROOT", str(workspace))
    monkeypatch.setattr(
        server,
        "cmd_install_hook_suite",
        lambda client, root, force: installs.append((client, root, force)) or 0,
    )

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "Cursor"},
            },
        }
    )

    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "harness-mem"
    assert installs == [("cursor", str(workspace.resolve()), False)]
    assert support_module.get_active_project() == "cursor-workspace"

    async def _load_profile():
        store = LocalProjectProfileStore(data_dir)
        return await store.get("cursor-workspace")

    profile = asyncio.run(_load_profile())
    assert profile is not None
    assert profile.project_root == str(workspace.resolve())
    assert profile.project_id is not None


def test_public_mcp_surface_is_single_memory_entrypoint(backend) -> None:
    result, tool_names = _listed_tool_names()

    assert result["surface"] == "memory"
    assert tool_names == EXPECTED_PUBLIC_MCP_TOOLS
    assert "profile" not in result
    assert "degraded_reason" not in result
    assert {
        "wake",
        "autopilot_search_tick",
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
    assert "metabolism_preview" not in tool_names
    assert "list_reflection_jobs" not in tool_names
    assert "get_reflection_job" not in tool_names
    assert "list_metabolism_runs" not in tool_names
    assert "health_summary" not in tool_names
    assert "hidden_tool_count" not in result
    assert "total_tool_count" not in result
    assert not SKILL_GOVERNANCE_TOOLS.intersection(tool_names)
    tool_by_name = {tool["name"]: tool for tool in result["tools"]}
    for name in ("dream_ledger", "dream_run", "dream_auto_tick", "undo_dream_item"):
        assert tool_by_name[name]["annotations"]["harness_mem"]["cluster"] == "dream"
    assert "/hm:distill" in tool_by_name["prepare_session_distill"]["description"]
    assert "ingest_sessions" not in tool_by_name
    assert "set_active_project" not in tool_by_name


def test_get_observations_accepts_recent_context_ids(backend) -> None:
    asyncio.run(
        backend.verbatim_store.save(
            Observation(
                id="recent-context-observation-1234",
                session_id="session-1",
                client="cursor",
                raw_content="User: Build the recent context index.",
                content_type="transcript",
                timestamp=datetime(2026, 7, 12, tzinfo=timezone.utc),
                metadata={"project_name": "demo"},
            )
        )
    )

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "get_observations",
                "arguments": {
                    "project_name": "demo",
                    "observation_ids": ["O-recent-c"],
                },
            },
        }
    )

    assert response is not None
    payload = _tool_result(response)
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["unresolved_ids"] == []
    assert payload["observations"][0]["id"] == "recent-context-observation-1234"


def test_profile_parameters_do_not_create_a_second_mcp_surface(backend, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_MCP_MAINTENANCE", "1")
    default_result, default_names = _listed_tool_names()
    maintenance_result, maintenance_names = _listed_tool_names({"profile": "maintenance"})
    legacy_result, legacy_names = _listed_tool_names({"mcp_tool_profile": "full"})

    assert maintenance_result["surface"] == "memory"
    assert maintenance_names == default_names
    assert legacy_result["surface"] == "memory"
    assert legacy_names == default_names
    assert "surface_source" not in maintenance_result
    assert "surface_source" not in legacy_result
    assert "degraded_reason" not in maintenance_result
    assert "degraded_reason" not in legacy_result
    assert "hidden_tool_count" not in maintenance_result
    assert "total_tool_count" not in maintenance_result
    assert default_result["tool_count"] == maintenance_result["tool_count"]


def test_env_gate_does_not_enable_maintenance_mcp_tools(
    backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_MEM_MCP_MAINTENANCE", "1")

    result, tool_names = _listed_tool_names({"profile": "maintenance"})

    assert result["surface"] == "memory"
    assert "surface_source" not in result
    assert "degraded_reason" not in result
    assert "list_reflection_jobs" not in tool_names
    assert "get_reflection_job" not in tool_names
    assert "list_metabolism_runs" not in tool_names
    assert "health_summary" not in tool_names
    assert "surface_cost_report" not in tool_names
    assert "metabolism_preview" not in tool_names
    assert "metabolism_run" not in tool_names
    assert "hidden_tool_count" not in result
    assert "total_tool_count" not in result


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


def test_removed_standalone_maintenance_tool_call_is_unknown(backend) -> None:
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
    assert response["error"]["message"] == "Unknown tool: metabolism_run"


def test_public_maintenance_read_debug_tool_call_is_unknown(backend) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "list_reflection_jobs",
                "arguments": {"project_name": "demo"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Unknown tool: list_reflection_jobs"


def test_profile_parameter_keeps_mutating_metabolism_unknown(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_MCP_MAINTENANCE", "1")
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "profile": "maintenance",
                "name": "metabolism_run",
                "arguments": {"project_name": "demo"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Unknown tool: metabolism_run"


def test_profile_parameter_cannot_read_maintenance_debug_tools(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_MCP_MAINTENANCE", "1")

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "profile": "maintenance",
                "name": "list_metabolism_runs",
                "arguments": {"project_name": "demo", "kind": "preview"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Unknown tool: list_metabolism_runs"


def test_removed_project_profile_write_tool_call_is_unknown(backend) -> None:
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "update_project_profile",
                "arguments": {
                    "project_name": "demo",
                    "retrieval_profile": "quality",
                },
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Unknown tool: update_project_profile"
    assert "data" not in response["error"]


def test_public_auto_review_apply_promotes_candidates(backend) -> None:
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
    assert payload["applied"] is True
    assert len(payload["applied_decisions"]) == 1
    assert "surface_enforcement" not in payload
    assert reloaded is not None
    assert reloaded.status == "auto_confirmed"


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
    assert payload["status"] == "user_confirmed"
    assert "surface_enforcement" not in payload
    assert reloaded is not None
    assert reloaded.status == "user_confirmed"


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
