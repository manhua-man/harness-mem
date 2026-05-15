from __future__ import annotations

import json

import pytest

from harness_mem.core.schemas import RelationFact
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import fake_embed_texts, run, seed_search_backend

pytestmark = pytest.mark.mcp


@pytest.fixture
def seeded_backend(backend: LocalMemoryBackend):
    run(seed_search_backend(backend))
    return backend


@pytest.fixture
def mcp_backend(seeded_backend: LocalMemoryBackend):
    set_backend_override(seeded_backend)
    try:
        yield seeded_backend
    finally:
        set_backend_override(None)


def rpc(method: str, params: dict | None = None) -> dict:
    req = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    resp = handle_request(req)
    assert resp is not None, f"No response for {method}"
    assert "error" not in resp, f"RPC error: {resp.get('error')}"
    return resp


def call_tool(name: str, arguments: dict) -> dict:
    resp = rpc("tools/call", {"name": name, "arguments": arguments})
    result = resp["result"]["content"][0]["text"]
    return json.loads(result)


def test_initialize():
    resp = rpc("initialize", {"protocolVersion": "2024-11-05"})
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "harness-mem"


def test_tools_list():
    resp = rpc("tools/list")
    tools = resp["result"]["tools"]
    assert len(tools) == 17
    names = {tool["name"] for tool in tools}
    expected = {
        "search_memory", "timeline", "get_observations",
        "get_task_handoffs", "get_confirmed_rules", "get_project_profile",
        "create_rule_candidate", "confirm_rule", "reject_rule", "suggest_rule",
        "suggest_memory_entry", "confirm_memory_entry", "reject_memory_entry",
        "suggest_relation_fact", "confirm_relation_fact", "reject_relation_fact",
        "create_task_handoff",
    }
    assert expected.issubset(names)


def test_search_memory(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "SQLite FTS5"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["memory_entry_count"] >= 1
    assert data["observation_count"] >= 1
    entries = run(mcp_backend.structured_store.list_memory_entries("test-project", limit=10))
    assert entries[0].usage_count == 1
    assert entries[0].last_accessed_at is not None


def test_search_memory_returns_relation_facts(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_relation_fact(
            RelationFact(
                project_name="test-project",
                source_entity="HybridSearchLayer",
                target_entity="SQLiteIndex",
                relation_type="delegates_to",
                evidence="HybridSearchLayer delegates relation search reads to SQLiteIndex.",
                source="manual",
            )
        )
    )

    resp = rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "delegates relation"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["relation_fact_count"] == 1
    assert data["relation_facts"][0]["relation_type"] == "delegates_to"
    assert data["relation_facts"][0]["search_mode"] == "fts"


def test_timeline(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "timeline",
        "arguments": {"project_name": "test-project", "limit": 5},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["count"] >= 1


def test_get_observations(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "get_observations",
        "arguments": {"project_name": "test-project", "session_id": "test-session-001"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["count"] >= 1


def test_create_rule_candidate(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "create_rule_candidate",
        "arguments": {
            "project_name": "test-project",
            "session_id": "test-session-001",
            "pattern": "Use SQLite FTS5 for full-text search",
            "trigger": "When setting up search indexing",
        },
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["success"] is True
    assert "candidate_id" in data


def test_suggest_memory_entry_pending_hidden_until_confirmed(mcp_backend: LocalMemoryBackend):
    suggested = call_tool(
        "suggest_memory_entry",
        {
            "project_name": "test-project",
            "category": "decision",
            "content": "AI candidate lifecycle sentinel alphaomega-memory",
            "source": "test-session-001",
        },
    )
    assert suggested["success"] is True
    assert suggested["status"] == "pending"

    pending_search = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "alphaomega-memory",
            "mode": "fts",
        },
    )
    assert pending_search["memory_entry_count"] == 0

    confirmed = call_tool("confirm_memory_entry", {"entry_id": suggested["entry_id"]})
    assert confirmed["success"] is True
    assert confirmed["status"] == "accepted"

    accepted_search = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "alphaomega-memory",
            "mode": "fts",
        },
    )
    assert accepted_search["memory_entry_count"] == 1
    assert accepted_search["memory_entries"][0]["id"] == suggested["entry_id"]


def test_suggest_relation_fact_rejected_remains_hidden(mcp_backend: LocalMemoryBackend):
    suggested = call_tool(
        "suggest_relation_fact",
        {
            "project_name": "test-project",
            "source_entity": "SessionDistill",
            "target_entity": "CandidateLayer",
            "relation_type": "feeds",
            "evidence": "AI relation candidate lifecycle sentinel alphaomega-relation",
            "source": "test-session-001",
        },
    )
    assert suggested["success"] is True
    assert suggested["status"] == "pending"

    pending_search = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "alphaomega-relation",
            "mode": "fts",
        },
    )
    assert pending_search["relation_fact_count"] == 0

    rejected = call_tool("reject_relation_fact", {"fact_id": suggested["fact_id"]})
    assert rejected["success"] is True
    assert rejected["status"] == "rejected"

    rejected_search = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "alphaomega-relation",
            "mode": "fts",
        },
    )
    assert rejected_search["relation_fact_count"] == 0


def test_confirm_rule(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "create_rule_candidate",
        "arguments": {
            "project_name": "test-project",
            "session_id": "test-session-001",
            "pattern": "Always validate JWT before API calls",
            "trigger": "Before any authenticated API call",
        },
    })
    result = resp["result"]["content"][0]["text"]
    candidate_id = json.loads(result)["candidate_id"]

    resp = rpc("tools/call", {
        "name": "confirm_rule",
        "arguments": {"rule_id": candidate_id},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["success"] is True
    assert "confirmed_rule_id" in data


def test_get_confirmed_rules(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "get_confirmed_rules",
        "arguments": {"project_name": "test-project"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert "rules" in data


def test_get_project_profile(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "get_project_profile",
        "arguments": {"project_name": "nonexistent-project"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["found"] is False


def test_search_memory_no_project(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "SQLite"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert "memory_entries" in data


def test_search_memory_reports_effective_mode(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", fake_embed_texts)

    resp = rpc("tools/call", {
        "name": "search_memory",
        "arguments": {
            "project_name": "test-project",
            "query": "SQLite FTS5",
            "mode": "hybrid",
        },
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["effective_mode"] == "hybrid"
    assert data["memory_entries"][0]["search_mode"] == "hybrid"
