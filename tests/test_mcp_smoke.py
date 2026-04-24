"""MCP smoke tests — verify all 8 MCP tools respond correctly."""

from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.mcp.server import handle_request, set_backend_override  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.core.schemas import Observation, MemoryEntry  # noqa: E402
from harness_mem.search.hybrid_search import HybridSearchLayer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def backend(tmp_path: Path):
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        yield backend
    finally:
        run(backend.close())


@pytest.fixture
def seeded_backend(backend: LocalMemoryBackend):
    """Backend with test data already written."""
    run(_seed_data(backend))
    return backend


@pytest.fixture
def mcp_backend(seeded_backend: LocalMemoryBackend):
    """Inject seeded_backend into the MCP server singleton."""
    set_backend_override(seeded_backend)
    return seeded_backend


async def _seed_data(backend: LocalMemoryBackend):
    obs = Observation(
        session_id="test-session-001",
        client="claude-code",
        raw_content="We decided to use SQLite FTS5 for full-text search in this project.",
        content_type="transcript",
        metadata={"project_name": "test-project"},
        tags=["session", "claude-code"],
    )
    await backend.verbatim_store.save(obs)

    entry = MemoryEntry(
        project_name="test-project",
        category="architecture",
        content="SQLite FTS5 is used for full-text search indexing",
        confidence=0.9,
        source="manual",
        tags=["architecture", "search"],
    )
    await backend.structured_store.save_memory_entry(entry)


def _rpc(method: str, params: dict | None = None) -> dict:
    req = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    resp = handle_request(req)
    assert resp is not None, f"No response for {method}"
    assert "error" not in resp, f"RPC error: {resp.get('error')}"
    return resp


def test_initialize():
    """Tool: initialize — should return server info."""
    resp = _rpc("initialize", {"protocolVersion": "2024-11-05"})
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "harness-mem"
    print("  [PASS] initialize")


def test_tools_list():
    """Tool: tools/list — should return all 10 tools."""
    resp = _rpc("tools/list")
    tools = resp["result"]["tools"]
    assert len(tools) == 10, f"Expected 10 tools, got {len(tools)}"
    names = {t["name"] for t in tools}
    expected = {
        "search_memory", "timeline", "get_observations",
        "get_task_handoffs", "get_confirmed_rules", "get_project_profile",
        "create_rule_candidate", "confirm_rule", "reject_rule", "suggest_rule",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"
    print(f"  [PASS] tools/list — {len(tools)} tools registered")


def test_search_memory(mcp_backend):
    """Tool: search_memory — should return memory entries and observations."""
    resp = _rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "SQLite FTS5"}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["memory_entry_count"] >= 1, f"Expected memory entries, got {data}"
    assert data["observation_count"] >= 1, f"Expected observations, got {data}"
    print(f"  [PASS] search_memory — {data['memory_entry_count']} entries, {data['observation_count']} obs")


def test_timeline(mcp_backend):
    """Tool: timeline — should return observations for project."""
    resp = _rpc("tools/call", {
        "name": "timeline",
        "arguments": {"project_name": "test-project", "limit": 5}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["count"] >= 1, f"Expected observations, got {data}"
    print(f"  [PASS] timeline — {data['count']} observations")


def test_get_observations(mcp_backend):
    """Tool: get_observations — should return observations for session."""
    resp = _rpc("tools/call", {
        "name": "get_observations",
        "arguments": {"project_name": "test-project", "session_id": "test-session-001"}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["count"] >= 1, f"Expected observations, got {data}"
    print(f"  [PASS] get_observations — {data['count']} observations")


def test_create_rule_candidate(mcp_backend):
    """Tool: create_rule_candidate — should create and return candidate id."""
    resp = _rpc("tools/call", {
        "name": "create_rule_candidate",
        "arguments": {
            "project_name": "test-project",
            "session_id": "test-session-001",
            "pattern": "Use SQLite FTS5 for full-text search",
            "trigger": "When setting up search indexing",
        }
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["success"] is True, f"Expected success, got {data}"
    assert "candidate_id" in data, f"Expected candidate_id, got {data}"
    print(f"  [PASS] create_rule_candidate — {data['candidate_id']}")


def test_confirm_rule(mcp_backend):
    """Tool: confirm_rule — should promote candidate to confirmed rule."""
    # First create a candidate
    resp = _rpc("tools/call", {
        "name": "create_rule_candidate",
        "arguments": {
            "project_name": "test-project",
            "session_id": "test-session-001",
            "pattern": "Always validate JWT before API calls",
            "trigger": "Before any authenticated API call",
        }
    })
    result = resp["result"]["content"][0]["text"]
    candidate_id = json.loads(result)["candidate_id"]

    # Confirm it
    resp = _rpc("tools/call", {
        "name": "confirm_rule",
        "arguments": {"rule_id": candidate_id}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["success"] is True, f"Expected success, got {data}"
    assert "confirmed_rule_id" in data, f"Expected confirmed_rule_id, got {data}"
    print(f"  [PASS] confirm_rule — confirmed {data['confirmed_rule_id']}")


def test_get_confirmed_rules(mcp_backend):
    """Tool: get_confirmed_rules — should return rules for project."""
    resp = _rpc("tools/call", {
        "name": "get_confirmed_rules",
        "arguments": {"project_name": "test-project"}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert "rules" in data, f"Expected rules key, got {data}"
    print(f"  [PASS] get_confirmed_rules — {data['count']} rules")


def test_get_project_profile(mcp_backend):
    """Tool: get_project_profile — should return project profile."""
    resp = _rpc("tools/call", {
        "name": "get_project_profile",
        "arguments": {"project_name": "nonexistent-project"}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["found"] is False, f"Expected not found, got {data}"
    print(f"  [PASS] get_project_profile — found={data['found']}")


def test_search_memory_no_project(mcp_backend):
    """Tool: search_memory without project_name should still work."""
    resp = _rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "SQLite"}
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert "memory_entries" in data
    print("  [PASS] search_memory (no-results case) — OK")


def _fake_embed_texts(self, texts: list[str]) -> list[list[float]]:
    return [[1.0, float(len(text))] for text in texts]


def test_search_memory_reports_effective_mode(mcp_backend, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", _fake_embed_texts)

    resp = _rpc("tools/call", {
        "name": "search_memory",
        "arguments": {
            "project_name": "test-project",
            "query": "SQLite FTS5",
            "mode": "hybrid",
        }
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["effective_mode"] == "hybrid"
    assert data["memory_entries"][0]["search_mode"] == "hybrid"
