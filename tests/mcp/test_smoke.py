from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    MergeSuggestionCandidate,
    Observation,
    RelationFact,
    RuleCandidate,
    Skill,
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import (
    fake_embed_texts,
    patch_fake_embedding_loader,
    patch_cli_adapters,
    requires_embeddings,
    run,
    seed_persisted_embedding,
    seed_search_backend,
    write_codex_archive_session,
)

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
    from harness_mem import __version__

    resp = rpc("initialize", {"protocolVersion": "2024-11-05"})
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "harness-mem"
    # Pin serverInfo.version to the package's single source of truth so the
    # MCP handshake never drifts behind harness_mem.__version__ again.
    assert result["serverInfo"]["version"] == __version__
    assert result["serverInfo"]["wire_format_version"] == "hm-wire-v3.4"


def test_stdio_initialize_writes_json_rpc_to_stdout():
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }

    proc = subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server"],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 0
    assert '"jsonrpc"' not in proc.stderr
    response = json.loads(proc.stdout.strip())
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "harness-mem"


def test_stdio_initialize_fails_before_handshake_when_launch_target_is_invalid():
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }

    proc = subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server_missing"],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
    assert "No module named harness_mem.mcp.server_missing" in proc.stderr


def test_tools_list():
    resp = rpc("tools/list")
    tools = resp["result"]["tools"]
    assert len(tools) == 59
    names = {tool["name"] for tool in tools}
    expected = {
        "search_memory", "timeline", "get_observations",
        "search_raw", "search_skills", "get_skill",
        "temporal_query",
        "get_task_handoffs", "get_confirmed_rules", "get_project_profile",
        "file_context",
        "get_project_status", "set_active_project", "update_project_profile", "wake",
        "ingest_sessions", "prepare_session_distill",
        "list_candidates", "auto_review_candidates",
        "trace_relations",
        "create_rule_candidate", "confirm_rule", "reject_rule", "suggest_rule",
        "suggest_supersede", "confirm_supersede", "reject_supersede", "suggest_correction",
        "suggest_skill", "confirm_skill", "reject_skill", "record_skill_result",
        "suggest_skill_promotion", "confirm_skill_promotion", "reject_skill_promotion",
        "detect_skill_improvements", "confirm_skill_revision", "reject_skill_revision",
        "detect_skill_deprecations", "confirm_skill_deprecation", "reject_skill_deprecation",
        "suggest_memory_entry", "confirm_memory_entry", "reject_memory_entry",
        "suggest_relation_fact", "confirm_relation_fact", "reject_relation_fact",
        "create_task_handoff",
        "metabolism_preview", "metabolism_run",
        "dream_ledger", "dream_run", "dream_auto_tick", "undo_dream_item",
        "list_reflection_jobs", "get_reflection_job",
        "health_summary", "surface_cost_report", "benchmark_matrix_report",
    }
    assert expected.issubset(names)
    benchmark_tool = next(tool for tool in tools if tool["name"] == "benchmark_matrix_report")
    assert "public-claim readiness gates" in benchmark_tool["description"]
    assert "token/cost saving" in benchmark_tool["description"]
    assert "true vector-hybrid latency" in benchmark_tool["description"]


def test_file_context_tool(mcp_backend: LocalMemoryBackend):
    run(
        LocalProjectProfileStore(mcp_backend.data_dir).save(
            ProjectProfile(
                project_name="test-project",
                key_files=["harness_mem/mcp/server.py"],
            )
        )
    )
    run(
        mcp_backend.verbatim_store.save(
            Observation(
                id="obs-file-context",
                session_id="mcp-file-context-session",
                client="codex",
                raw_content="Edited harness_mem/mcp/server.py to add file_context support.",
                content_type="transcript",
                metadata={"project_name": "test-project"},
            )
        )
    )
    run(
        mcp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="test-project",
                category="architecture",
                content="harness_mem/mcp/server.py owns MCP tool registration.",
                source="manual",
            )
        )
    )

    data = call_tool(
        "file_context",
        {
            "project_name": "test-project",
            "path": "harness_mem/mcp/server.py",
            "project_root": str(Path(__file__).resolve().parents[2]),
        },
    )

    assert data["success"] is True
    assert data["item_count"] >= 2
    assert data["normalized_path"] == "harness_mem/mcp/server.py"
    assert any(item["kind"] == "observation" for item in data["items"])
    assert data["file_fingerprint"]["source_id"].startswith("code-file:")
    assert data["file_fingerprint"]["sha256"]
    assert data["code_symbols"]
    assert any(item["stale_status"] == "current" for item in data["code_evidence"])


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


def test_mcp_surface_cost_observer_logs_local_metadata_without_content(
    mcp_backend: LocalMemoryBackend,
):
    data = call_tool(
        "search_memory",
        {"project_name": "test-project", "query": "SQLite FTS5"},
    )
    assert data["memory_entry_count"] >= 1

    events_path = mcp_backend.data_dir / "events.log"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    cost_events = [event for event in events if event["type"] == "mcp_surface_cost"]
    assert cost_events, "MCP tools/call should record a best-effort local cost event"
    latest = cost_events[-1]
    assert latest["project_name"] == "test-project"
    assert latest["command"] == "mcp.search_memory"
    assert latest["extra"]["tool_name"] == "search_memory"
    assert latest["extra"]["surface"] == "search"
    assert latest["extra"]["output_tokens"] > 0
    assert "query_chars" in latest["extra"]["argument_shape"]

    serialized_event = json.dumps(latest, ensure_ascii=False)
    assert "SQLite FTS5" not in serialized_event
    assert "Use SQLite FTS5 for full-text search indexing" not in serialized_event


def test_surface_cost_report_aggregates_recent_high_output_calls(
    mcp_backend: LocalMemoryBackend,
):
    from harness_mem.runtime_cost import analyze_mcp_surface_cost
    from harness_mem.runtime_cost import observe_mcp_surface_cost

    high_output = " ".join(f"wake-cost-token-{idx}" for idx in range(5000))
    assert analyze_mcp_surface_cost(
        "wake",
        {"project_name": "test-project", "renderer": "default"},
        {"success": True, "output": high_output},
        duration_ms=42,
    )["high_output"] is True

    observe_mcp_surface_cost(
        data_dir=mcp_backend.data_dir,
        tool_name="wake",
        arguments={"project_name": "test-project", "renderer": "default"},
        result={"success": True, "output": high_output},
        duration_ms=42,
    )
    observe_mcp_surface_cost(
        data_dir=mcp_backend.data_dir,
        tool_name="search_memory",
        arguments={"project_name": "other-project", "query": "all", "scope": "all"},
        result={"success": True, "memory_entry_count": 20, "observations": []},
        duration_ms=5,
    )

    data = call_tool(
        "surface_cost_report",
        {"project_name": "test-project", "days": 30},
    )

    assert data["success"] is True
    assert data["project_name"] == "test-project"
    assert data["summary"]["total_calls"] >= 1
    assert data["summary"]["high_output_calls"] >= 1
    wake_surface = next(surface for surface in data["surfaces"] if surface["surface"] == "wake")
    assert wake_surface["high_output_calls"] >= 1
    assert any(
        item["kind"] == "compact_context"
        for item in data["top_opportunities"]
    )
    assert all(
        call["project_name"] == "test-project"
        for call in data["recent_high_output_calls"]
    )


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


def test_trace_relations_tool_returns_bounded_path(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_relation_fact(
            RelationFact(
                project_name="test-project",
                source_entity="Parser",
                target_entity="StructuredStore",
                relation_type="feeds",
                evidence="Parser feeds structured facts into StructuredStore.",
                source="manual",
            )
        )
    )
    run(
        mcp_backend.structured_store.save_relation_fact(
            RelationFact(
                project_name="test-project",
                source_entity="StructuredStore",
                target_entity="SQLiteIndex",
                relation_type="feeds",
                evidence="StructuredStore feeds accepted facts into SQLiteIndex.",
                source="manual",
            )
        )
    )

    data = call_tool(
        "trace_relations",
        {
            "project_name": "test-project",
            "source_entity": "Parser",
            "relation_type": "feeds",
            "max_depth": 2,
        },
    )
    assert data["success"] is True
    assert data["path_count"] == 2
    assert data["paths"][1]["entities"] == [
        "Parser",
        "StructuredStore",
        "SQLiteIndex",
    ]

    rejected = call_tool(
        "trace_relations",
        {
            "project_name": "test-project",
            "source_entity": "Parser",
            "max_depth": 4,
        },
    )
    assert rejected["success"] is False
    assert "max_depth must be <= 3" in rejected["error"]


def test_search_raw_tool_returns_exact_snippet(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.verbatim_store.save(
            Observation(
                id="obs-mcp-raw",
                session_id="mcp-raw-session",
                client="codex",
                raw_content="MCP raw evidence includes ERROR-5001.",
                content_type="transcript",
                metadata={"project_name": "test-project"},
            )
        )
    )

    data = call_tool(
        "search_raw",
        {
            "project_name": "test-project",
            "pattern": r"ERROR-\d+",
        },
    )
    assert data["success"] is True
    assert data["count"] == 1
    assert data["matches"][0]["id"] == "obs-mcp-raw"
    assert "ERROR-5001" in data["matches"][0]["snippet"]

    rejected = call_tool(
        "search_raw",
        {
            "project_name": "test-project",
            "pattern": r"ERROR-[",
        },
    )
    assert rejected["success"] is False
    assert "invalid regex" in rejected["error"]

def test_search_memory_include_history_returns_historical_structured_truth(
    mcp_backend: LocalMemoryBackend,
):
    run(
        mcp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="test-project",
                category="decision",
                content="Historical MCP temporal sentinel used Vue.",
                source="manual",
                valid_to=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    default_data = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "MCP temporal sentinel",
            "mode": "fts",
        },
    )
    assert default_data["memory_entry_count"] == 0

    history_data = call_tool(
        "search_memory",
        {
            "project_name": "test-project",
            "query": "MCP temporal sentinel",
            "mode": "fts",
            "include_history": True,
        },
    )
    assert history_data["include_history"] is True
    assert history_data["memory_entry_count"] == 1
    assert history_data["memory_entries"][0]["is_historical"] is True


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


def test_suggest_confirm_search_and_record_skill(mcp_backend: LocalMemoryBackend):
    suggested = call_tool(
        "suggest_skill",
        {
            "project_name": "test-project",
            "activation_condition": "Focused MCP runtime change needs validation",
            "steps": ["Run focused tests", "Run full pytest"],
            "termination_condition": "All validation commands pass",
            "success_examples": ["tests/mcp/test_smoke.py passes"],
            "source_session_id": "test-session-001",
        },
    )
    assert suggested["success"] is True

    listed = call_tool("list_candidates", {"project_name": "test-project"})
    assert listed["procedural_count"] >= 1
    assert any(
        candidate["id"] == suggested["candidate_id"]
        for candidate in listed["procedural_candidates"]
    )

    confirmed = call_tool("confirm_skill", {"candidate_id": suggested["candidate_id"]})
    assert confirmed["success"] is True
    skill_id = confirmed["skill"]["id"]

    searched = call_tool(
        "search_skills",
        {
            "project_name": "test-project",
            "query": "MCP validation",
        },
    )
    assert searched["success"] is True
    assert searched["skills"][0]["id"] == skill_id

    recorded = call_tool(
        "record_skill_result",
        {
            "skill_id": skill_id,
            "success": True,
        },
    )
    assert recorded["success"] is True
    assert recorded["skill"]["usage_count"] == 1
    assert recorded["skill"]["success_rate"] == 1.0

    loaded = call_tool("get_skill", {"skill_id": skill_id})
    assert loaded["success"] is True
    assert loaded["skill"]["id"] == skill_id
    assert loaded["skill"]["steps"] == ["Run focused tests", "Run full pytest"]


def test_list_candidates_returns_pending_review_items(mcp_backend: LocalMemoryBackend):
    rule = call_tool(
        "create_rule_candidate",
        {
            "project_name": "test-project",
            "session_id": "test-session-001",
            "pattern": "Review candidates through the MCP review surface",
            "trigger": "When humans need to approve memory",
        },
    )
    entry = call_tool(
        "suggest_memory_entry",
        {
            "project_name": "test-project",
            "category": "decision",
            "content": "Candidate review should not require the CLI to list pending memory.",
            "source": "test-session-001",
        },
    )
    fact = call_tool(
        "suggest_relation_fact",
        {
            "project_name": "test-project",
            "source_entity": "SlashReview",
            "target_entity": "MCPListCandidates",
            "relation_type": "uses",
            "evidence": "The slash review flow lists candidates through MCP.",
            "source": "test-session-001",
        },
    )

    supersede = call_tool(
        "suggest_supersede",
        {
            "project_name": "test-project",
            "target_type": "confirmed_rule",
            "target_id": "rule-old",
            "replacement_type": "confirmed_rule",
            "replacement_id": "rule-new",
            "reason": "The new rule replaced the old one.",
            "evidence": "Project docs now point to the new rule.",
            "source": "test-session-001",
        },
    )
    run(
        mcp_backend.structured_store.save_merge_suggestion_candidate(
            MergeSuggestionCandidate(
                project_name="test-project",
                target_a_id="entry-a",
                target_a_kind="memory_entry",
                target_b_id="entry-b",
                target_b_kind="memory_entry",
                similarity_score=0.91,
                evidence_signal_ids=["sig-1"],
                metabolism_run_id="run-1",
            )
        )
    )
    run(
        mcp_backend.structured_store.save_stale_truth_suggestion_candidate(
            StaleTruthSuggestionCandidate(
                project_name="test-project",
                target_id="rule-old",
                target_kind="confirmed_rule",
                last_surfaced_at=None,
                days_since_last_surface=90,
                evidence_signal_ids=[],
                metabolism_run_id="run-1",
            )
        )
    )

    data = call_tool("list_candidates", {"project_name": "test-project"})

    assert data["success"] is True
    assert data["status"] == "pending"
    assert data["count"] == 6
    assert data["total_count"] == 6
    assert data["rule_count"] == 1
    assert data["memory_entry_count"] == 1
    assert data["relation_fact_count"] == 1
    assert data["supersede_count"] == 1
    assert data["merge_suggestion_count"] == 1
    assert data["stale_truth_suggestion_count"] == 1
    ids_by_type = {candidate["type"]: candidate["id"] for candidate in data["candidates"]}
    assert ids_by_type["rule"] == rule["candidate_id"]
    assert ids_by_type["memory_entry"] == entry["entry_id"]
    assert ids_by_type["relation_fact"] == fact["fact_id"]
    assert ids_by_type["supersede"] == supersede["candidate_id"]
    assert ids_by_type["merge_suggestion"]
    assert ids_by_type["stale_truth_suggestion"]
    tools_by_type = {
        candidate["type"]: candidate["confirm_tool"]
        for candidate in data["candidates"]
        if "confirm_tool" in candidate
    }
    assert tools_by_type == {
        "rule": "confirm_rule",
        "memory_entry": "confirm_memory_entry",
        "relation_fact": "confirm_relation_fact",
        "supersede": "confirm_supersede",
    }
    merge_item = next(candidate for candidate in data["candidates"] if candidate["type"] == "merge_suggestion")
    stale_item = next(
        candidate for candidate in data["candidates"] if candidate["type"] == "stale_truth_suggestion"
    )
    assert "confirm_tool" not in merge_item
    assert "reject_tool" not in merge_item
    assert "confirm_tool" not in stale_item
    assert "reject_tool" not in stale_item

    confirmed = call_tool("confirm_memory_entry", {"entry_id": entry["entry_id"]})
    assert confirmed["success"] is True

    after_confirm = call_tool("list_candidates", {"project_name": "test-project"})
    pending_ids = {candidate["id"] for candidate in after_confirm["candidates"]}
    assert entry["entry_id"] not in pending_ids
    assert after_confirm["count"] == 5


def test_skill_promotion_review_flow(mcp_backend: LocalMemoryBackend):
    suggested = call_tool(
        "suggest_skill",
        {
            "project_name": "test-project",
            "activation_condition": "When preparing a Python release",
            "steps": ["Run pytest", "Update changelog"],
            "termination_condition": "Release checks pass",
            "source_session_id": "promotion-session-1",
        },
    )
    confirmed = call_tool("confirm_skill", {"candidate_id": suggested["candidate_id"]})
    project_skill_id = confirmed["skill"]["id"]

    promotion = call_tool(
        "suggest_skill_promotion",
        {
            "skill_id": project_skill_id,
            "target_scope": "global",
            "portability_notes": "Only reuse in repos with pytest and a changelog.",
            "disabled_assumptions": ["Do not assume CI job names are identical."],
        },
    )
    assert promotion["success"] is True

    listed = call_tool("list_candidates", {"project_name": "test-project"})
    assert listed["skill_promotion_count"] == 1
    promotion_candidate = next(
        candidate for candidate in listed["candidates"] if candidate["type"] == "skill_promotion"
    )
    assert promotion_candidate["id"] == promotion["candidate_id"]
    assert promotion_candidate["source_skill_id"] == project_skill_id
    assert promotion_candidate["requested_scope"] == "global"
    assert promotion_candidate["confirm_tool"] == "confirm_skill_promotion"
    assert promotion_candidate["reject_tool"] == "reject_skill_promotion"

    shared = call_tool(
        "confirm_skill_promotion",
        {"candidate_id": promotion["candidate_id"]},
    )
    assert shared["success"] is True
    assert shared["skill"]["scope"] == "global"
    assert shared["skill"]["origin_project"] == "test-project"
    assert shared["skill"]["portability_notes"] == "Only reuse in repos with pytest and a changelog."
    assert shared["skill"]["disabled_assumptions"] == [
        "Do not assume CI job names are identical."
    ]
    assert project_skill_id in shared["skill"]["source_ids"]

    default_search = call_tool(
        "search_skills",
        {
            "project_name": "test-project",
            "query": "Python release changelog",
        },
    )
    assert [skill["scope"] for skill in default_search["skills"]] == ["project"]

    shared_search = call_tool(
        "search_skills",
        {
            "project_name": "test-project",
            "query": "Python release changelog",
            "include_shared": True,
        },
    )
    assert shared_search["success"] is True
    assert shared_search["shared_scope"] == "include"
    assert [skill["scope"] for skill in shared_search["skills"]] == [
        "project",
        "global",
    ]
    assert shared_search["skills"][1]["origin_project"] == "test-project"
    assert project_skill_id in shared_search["skills"][1]["source_ids"]
    assert (
        shared_search["skills"][1]["portability_notes"]
        == "Only reuse in repos with pytest and a changelog."
    )
    assert shared_search["skills"][1]["disabled_assumptions"] == [
        "Do not assume CI job names are identical."
    ]
    assert shared_search["skills"][1]["activation_warnings"] == [
        "Only reuse in repos with pytest and a changelog.",
        "Do not assume CI job names are identical.",
    ]

    shared_only = call_tool(
        "search_skills",
        {
            "project_name": "test-project",
            "query": "Python release changelog",
            "shared_scope": "only",
        },
    )
    assert [skill["scope"] for skill in shared_only["skills"]] == ["global"]

    recorded_shared = call_tool(
        "record_skill_result",
        {
            "skill_id": shared["skill"]["id"],
            "success": True,
        },
    )
    assert recorded_shared["success"] is True
    assert recorded_shared["skill"]["usage_count"] == 1

    project_skill = run(mcp_backend.structured_store.get_skill(project_skill_id))
    shared_skill = run(mcp_backend.structured_store.get_skill(shared["skill"]["id"]))
    assert project_skill is not None
    assert project_skill.usage_count == 0
    assert shared_skill is not None
    assert shared_skill.usage_count == 1


def test_reject_skill_promotion_candidate(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_skill(
            Skill(
                project_name="test-project",
                name="Deploy smoke loop",
                activation_condition="When deploying",
                steps=["Run smoke tests"],
                termination_condition="Smoke tests pass",
            )
        )
    )
    project_skill = run(mcp_backend.structured_store.search_skills("Deploy smoke", project_name="test-project"))[0]
    promotion = call_tool(
        "suggest_skill_promotion",
        {
            "skill_id": project_skill.id,
            "target_scope": "workspace",
        },
    )

    rejected = call_tool(
        "reject_skill_promotion",
        {"candidate_id": promotion["candidate_id"]},
    )
    assert rejected["success"] is True

    listed = call_tool("list_candidates", {"project_name": "test-project"})
    assert listed["skill_promotion_count"] == 0
    all_skills = call_tool(
        "search_skills",
        {
            "query": "Deploy smoke",
            "scope": "all",
        },
    )
    assert [skill["scope"] for skill in all_skills["skills"]] == ["project"]


def test_search_skills_rejects_invalid_shared_scope(mcp_backend: LocalMemoryBackend):
    data = call_tool(
        "search_skills",
        {
            "project_name": "test-project",
            "query": "release hygiene",
            "shared_scope": "surprise",
        },
    )

    assert data["success"] is False
    assert "shared_scope must be one of: exclude, include, only" in data["error"]


def test_detect_skill_improvements_creates_review_candidates_without_rewriting_skill(
    mcp_backend: LocalMemoryBackend,
):
    suggested = call_tool(
        "suggest_skill",
        {
            "project_name": "test-project",
            "activation_condition": "When preparing a release",
            "steps": ["Run tests", "Update changelog"],
            "termination_condition": "Release checks pass",
            "source_session_id": "skill-revision-session",
        },
    )
    confirmed = call_tool("confirm_skill", {"candidate_id": suggested["candidate_id"]})
    skill_id = confirmed["skill"]["id"]

    for _ in range(5):
        payload = call_tool(
            "record_skill_result",
            {
                "skill_id": skill_id,
                "success": False,
                "surface": "search_skills",
                "source_ids": ["obs-skill-failure"],
                "reason": "missed release checklist precondition",
            },
        )
        assert payload["success"] is True

    detected = call_tool(
        "detect_skill_improvements",
        {
            "project_name": "test-project",
        },
    )
    assert detected["success"] is True
    assert detected["matched_skill_count"] >= 1
    assert detected["created_count"] == 1

    repeated = call_tool(
        "detect_skill_improvements",
        {
            "project_name": "test-project",
        },
    )
    assert repeated["success"] is True
    assert repeated["created_count"] == 0
    assert repeated["skipped_existing_count"] >= 1

    listed = call_tool("list_candidates", {"project_name": "test-project"})
    assert listed["skill_revision_suggestion_count"] == 1
    candidate = next(
        item for item in listed["candidates"] if item["type"] == "skill_revision_suggestion"
    )
    assert candidate["source_skill_id"] == skill_id
    assert candidate["trigger"] == "zero_success_after_repeated_use"
    assert candidate["failure_count"] == 5
    assert candidate["success_count"] == 0
    assert len(candidate["recent_failure_signal_ids"]) == 5
    failure_signals = run(
        mcp_backend.structured_store.query_retrieval_signals(
            "test-project",
            signal_type="skill_result_failure",
            target_kind="skill",
            target_id=skill_id,
        )
    )
    assert failure_signals
    assert failure_signals[0].context == {
        "surface": "search_skills",
        "source_ids": ["obs-skill-failure"],
        "reason": "missed release checklist precondition",
    }
    assert candidate["confirm_tool"] == "confirm_skill_revision"
    assert candidate["reject_tool"] == "reject_skill_revision"

    accepted = call_tool(
        "confirm_skill_revision",
        {"candidate_id": candidate["id"]},
    )
    assert accepted["success"] is True
    assert accepted["status"] == "accepted"
    assert accepted["skill"]["id"] == skill_id
    assert accepted["skill"]["steps"] == ["Run tests", "Update changelog"]

    still_same_skill = call_tool("get_skill", {"skill_id": skill_id})
    assert still_same_skill["skill"]["steps"] == ["Run tests", "Update changelog"]


def test_detect_skill_deprecations_retires_stale_shared_skill(
    mcp_backend: LocalMemoryBackend,
):
    stale_shared_skill = Skill(
        project_name="test-project",
        name="Old shared release hygiene",
        activation_condition="When preparing a release",
        steps=["Run tests", "Update changelog"],
        termination_condition="Release checks pass",
        scope="global",
        origin_project="test-project",
        created_at=datetime.now(timezone.utc) - timedelta(days=120),
        updated_at=datetime.now(timezone.utc) - timedelta(days=120),
    )
    run(mcp_backend.structured_store.save_skill(stale_shared_skill))

    detected = call_tool(
        "detect_skill_deprecations",
        {
            "project_name": "test-project",
            "stale_days": 60,
        },
    )
    assert detected["success"] is True
    assert detected["created_count"] == 1

    listed = call_tool("list_candidates", {"project_name": "test-project"})
    assert listed["skill_deprecation_suggestion_count"] == 1
    candidate = next(
        item for item in listed["candidates"] if item["type"] == "skill_deprecation_suggestion"
    )
    assert candidate["source_skill_id"] == stale_shared_skill.id
    assert candidate["trigger"] == "stale_shared_skill"
    assert candidate["confirm_tool"] == "confirm_skill_deprecation"
    assert candidate["reject_tool"] == "reject_skill_deprecation"

    confirmed = call_tool(
        "confirm_skill_deprecation",
        {"candidate_id": candidate["id"]},
    )
    assert confirmed["success"] is True
    assert confirmed["status"] == "accepted"
    assert confirmed["skill"]["status"] == "retired"

    loaded = call_tool("get_skill", {"skill_id": stale_shared_skill.id})
    assert loaded["success"] is True
    assert loaded["skill"]["status"] == "retired"


def test_auto_review_candidates_preview_and_apply(mcp_backend: LocalMemoryBackend):
    """auto_review_candidates returns the spec-shaped summary and respects apply."""
    # Seed three pending entries: one obvious noise, one auto-confirm target,
    # one bug entry that should defer.
    call_tool(
        "suggest_memory_entry",
        {
            "project_name": "test-project",
            "category": "decision",
            "content": "Glad we got that one nailed down — that was a tricky one.",
            "confidence": 0.85,
            "source": "test-session-auto-review",
        },
    )
    call_tool(
        "suggest_memory_entry",
        {
            "project_name": "test-project",
            "category": "decision",
            "content": (
                "We decided to use invoke for all data-shaped IPC and reserve "
                "emit only for fire-and-forget UI events because Tauri v1 "
                "emit deadlocked on Windows for payloads >1MB."
            ),
            "confidence": 0.9,
            "source": "test-session-auto-review",
        },
    )
    call_tool(
        "suggest_memory_entry",
        {
            "project_name": "test-project",
            "category": "bug",
            "content": (
                "The root cause was a missing JWT exp validation; the fix "
                "was to check the exp claim before any authenticated call."
            ),
            "confidence": 0.95,
            "source": "test-session-auto-review",
        },
    )

    preview = call_tool(
        "auto_review_candidates",
        {"project_name": "test-project", "apply": False},
    )
    assert preview["success"] is True
    assert preview["applied"] is False
    assert preview["auto_confirmed"] >= 1
    assert preview["auto_rejected"] >= 1
    assert preview["kept_pending"] >= 1
    assert preview["new_candidates"] == (
        preview["auto_confirmed"] + preview["auto_rejected"] + preview["kept_pending"]
    )
    # Preview must not mutate.
    assert preview["applied_decisions"] == []

    applied = call_tool(
        "auto_review_candidates",
        {"project_name": "test-project", "apply": True},
    )
    assert applied["success"] is True
    assert applied["applied"] is True
    assert applied["auto_confirmed"] == preview["auto_confirmed"]
    assert applied["auto_rejected"] == preview["auto_rejected"]
    assert len(applied["applied_decisions"]) == (
        applied["auto_confirmed"] + applied["auto_rejected"]
    )
    actions = {d["action"] for d in applied["applied_decisions"]}
    assert {"auto_confirm", "auto_reject"}.issubset(actions)


def test_confirm_supersede_marks_truth_historical(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                id="rule-old",
                project_name="test-project",
                pattern="Use the old route.",
                trigger="When editing API clients",
                source_candidate_id="candidate-old",
            )
        )
    )
    run(
        mcp_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                id="rule-new",
                project_name="test-project",
                pattern="Use the new route.",
                trigger="When editing API clients",
                source_candidate_id="candidate-new",
            )
        )
    )

    created = call_tool(
        "suggest_supersede",
        {
            "project_name": "test-project",
            "target_type": "confirmed_rule",
            "target_id": "rule-old",
            "replacement_type": "confirmed_rule",
            "replacement_id": "rule-new",
            "reason": "The new route replaces the old one.",
            "evidence": "Docs point to the new route now.",
            "source": "test-session-001",
        },
    )
    assert created["success"] is True

    confirmed = call_tool("confirm_supersede", {"candidate_id": created["candidate_id"]})
    assert confirmed["success"] is True

    old_rule = run(mcp_backend.structured_store.get_confirmed_rule("rule-old"))
    new_rule = run(mcp_backend.structured_store.get_confirmed_rule("rule-new"))
    assert old_rule is not None
    assert new_rule is not None
    assert old_rule.valid_to is not None
    assert new_rule.supersedes == ["rule-old"]


def test_reject_supersede_keeps_truth_current(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                id="rule-old-reject",
                project_name="test-project",
                pattern="Use the old route.",
                trigger="When editing API clients",
                source_candidate_id="candidate-old",
            )
        )
    )
    run(
        mcp_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                id="rule-new-reject",
                project_name="test-project",
                pattern="Use the new route.",
                trigger="When editing API clients",
                source_candidate_id="candidate-new",
            )
        )
    )

    created = call_tool(
        "suggest_supersede",
        {
            "project_name": "test-project",
            "target_type": "confirmed_rule",
            "target_id": "rule-old-reject",
            "replacement_type": "confirmed_rule",
            "replacement_id": "rule-new-reject",
            "reason": "The new route replaces the old one.",
            "evidence": "Docs point to the new route now.",
            "source": "test-session-001",
        },
    )
    assert created["success"] is True

    rejected = call_tool("reject_supersede", {"candidate_id": created["candidate_id"]})
    assert rejected["success"] is True

    old_rule = run(mcp_backend.structured_store.get_confirmed_rule("rule-old-reject"))
    new_rule = run(mcp_backend.structured_store.get_confirmed_rule("rule-new-reject"))
    assert old_rule is not None and old_rule.valid_to is None
    assert new_rule is not None and new_rule.supersedes == []


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


def test_get_confirmed_rules_include_history(mcp_backend: LocalMemoryBackend):
    run(
        mcp_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                project_name="test-project",
                pattern="Historical MCP rule used the old route.",
                trigger="When checking MCP temporal history",
                source_candidate_id="candidate-old",
                valid_to=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    default_data = call_tool(
        "get_confirmed_rules",
        {"project_name": "test-project"},
    )
    assert all(
        rule["pattern"] != "Historical MCP rule used the old route."
        for rule in default_data["rules"]
    )

    history_data = call_tool(
        "get_confirmed_rules",
        {"project_name": "test-project", "include_history": True},
    )
    old_rule = next(
        rule
        for rule in history_data["rules"]
        if rule["pattern"] == "Historical MCP rule used the old route."
    )
    assert history_data["include_history"] is True
    assert old_rule["is_historical"] is True


def test_temporal_query_current_history_as_of_and_supersede_explanation(
    mcp_backend: LocalMemoryBackend,
):
    old_valid_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old_valid_to = datetime(2026, 3, 1, tzinfo=timezone.utc)
    new_valid_from = datetime(2026, 3, 1, tzinfo=timezone.utc)
    recorded_at = datetime(2026, 3, 2, tzinfo=timezone.utc)
    run(
        mcp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="temporal-old-entry",
                project_name="temporal-project",
                category="decision",
                content="Temporal sentinel route used HTTP polling.",
                source="obs-old",
                valid_from=old_valid_from,
                valid_to=old_valid_to,
                recorded_at=old_valid_from,
                superseded_by=["temporal-new-entry"],
            )
        )
    )
    run(
        mcp_backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="temporal-new-entry",
                project_name="temporal-project",
                category="decision",
                content="Temporal sentinel route uses WebSocket streaming.",
                source="obs-new",
                valid_from=new_valid_from,
                recorded_at=recorded_at,
                supersedes=["temporal-old-entry"],
            )
        )
    )

    current = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "Temporal sentinel route",
            "mode": "current",
        },
    )
    assert current["success"] is True
    assert current["abstain"] is False
    assert [record["id"] for record in current["records"]] == ["temporal-new-entry"]
    assert current["records"][0]["valid_from"] == new_valid_from.isoformat()
    assert current["records"][0]["recorded_at"] == recorded_at.isoformat()
    assert [record["id"] for record in current["supersede_chain"]] == [
        "temporal-old-entry"
    ]
    assert current["timeline_count"] == 2
    assert current["explanations"][0]["old"][0]["id"] == "temporal-old-entry"
    assert current["explanations"][0]["policy_reason"].startswith("confirmed truth")

    history = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "Temporal sentinel route",
            "mode": "history",
        },
    )
    assert [record["id"] for record in history["records"]] == ["temporal-old-entry"]
    assert history["records"][0]["valid_to"] == old_valid_to.isoformat()

    as_of = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "Temporal sentinel route",
            "mode": "as_of",
            "as_of": "2026-02-01T00:00:00+00:00",
        },
    )
    assert [record["id"] for record in as_of["records"]] == ["temporal-old-entry"]

    as_of_recorded_out = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "Temporal sentinel route",
            "mode": "as_of",
            "as_of": "2026-02-01T00:00:00+00:00",
            "recorded_from": "2026-02-15T00:00:00+00:00",
        },
    )
    assert as_of_recorded_out["abstain"] is True
    assert as_of_recorded_out["abstention_reason"] == "no_evidence"

    missing_as_of = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "Temporal sentinel route",
            "mode": "as_of",
        },
    )
    assert missing_as_of["success"] is False
    assert missing_as_of["error"] == "as_of is required when mode=as_of"


def test_temporal_query_abstains_for_no_evidence_and_current_conflict(
    mcp_backend: LocalMemoryBackend,
):
    missing = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-project",
            "query": "no such temporal sentinel",
        },
    )
    assert missing["abstain"] is True
    assert missing["abstention_reason"] == "no_evidence"

    for entry_id, content in (
        ("conflict-a", "Conflict sentinel current value A."),
        ("conflict-b", "Conflict sentinel current value B."),
    ):
        run(
            mcp_backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id=entry_id,
                    project_name="temporal-conflict-project",
                    category="decision",
                    content=content,
                    source="manual",
                )
            )
        )

    conflict = call_tool(
        "temporal_query",
        {
            "project_name": "temporal-conflict-project",
            "subject": "decision",
            "predicate": "memory_entry",
            "mode": "current",
            "limit": 1,
            "require_unique_current": True,
        },
    )
    assert conflict["record_count"] == 1
    assert conflict["abstain"] is True
    assert conflict["abstention_reason"] == "temporal_conflict"


def test_get_project_profile(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "get_project_profile",
        "arguments": {"project_name": "nonexistent-project"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert data["found"] is False


def test_get_project_status_returns_counts_without_cli(mcp_backend: LocalMemoryBackend):
    data = call_tool("get_project_status", {"project_name": "test-project"})

    assert data["success"] is True
    assert data["project_name"] == "test-project"
    assert data["observation_count"] >= 1
    assert data["memory_entry_count"] >= 1
    assert data["phase"] == "ready"
    assert data["suggested_slash"] == "/hm:wake"
    assert data["generated_cache"]["generated_claim_count"] >= 0
    assert "stale_source_count" in data["generated_cache"]
    assert "cache_hit_ratio" in data["generated_cache"]
    assert data["runtime_versions"]["wire_format_version"] == "hm-wire-v3.4"
    assert "job_health" in data
    assert data["cost_budget"]["policy"]["policy_version"] == "cost-budget-v3.4.4"


def test_get_project_status_uses_project_cost_budget_config(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    project_root = tmp_path / "budget-project"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        "[cost_budget]\nsearch_tokens = 7\nwake_tokens = 11\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)

    data = call_tool("get_project_status", {"project_name": "budget-project"})

    budgets = data["cost_budget"]["policy"]["budgets"]
    assert budgets["search"] == 7
    assert budgets["wake"] == 11


def test_benchmark_matrix_report_exposes_surface_gates():
    data = call_tool("benchmark_matrix_report", {})

    assert data["success"] is True
    assert data["matrix_version"] == "v4.5.0"
    surfaces = {row["surface"]: row for row in data["surfaces"]}
    assert {
        "wake",
        "search",
        "file_context",
        "wiki_compact",
        "temporal_query",
        "storage_v2",
        "canonical_store",
        "rust_core",
        "index_fabric",
        "lifecycle_tiering",
        "context_sufficiency",
        "task_aware_wake",
        "memory_eval_matrix",
        "retrieval_quality_pack",
        "code_memory_federation",
        "claim_promotion",
        "release_evidence_pack",
    }.issubset(
        surfaces
    )
    assert "knowledge-update" in data["taxonomy"]["dimensions"]
    assert data["taxonomy"]["embedding_baseline"] == "all-MiniLM-L6-v2"
    assert "release_snapshot" in data
    assert "retrieval_shootout" in data
    assert "claim_readiness" in data
    assert "claim_promotion_gate" in data
    assert "release_evidence_pack" in data
    assert data["memory_eval_gate"]["passed"] is True
    assert data["retrieval_quality_pack"]["passed"] is True
    assert data["claim_promotion_gate"]["policy_enforced"] is True
    assert data["release_evidence_pack"]["collection_present"] is True
    for claim in (
        "token_cost_saving",
        "true_vector_hybrid_latency",
        "retrieval_recall",
    ):
        claim_data = data["claim_readiness"][claim]
        assert isinstance(claim_data["ready"], bool)
        assert isinstance(claim_data["blocking"], list)
        assert claim_data["dimension"]
        assert claim_data["source"]


def test_get_project_status_empty_project_suggests_distill(mcp_backend: LocalMemoryBackend):
    data = call_tool("get_project_status", {"project_name": "empty-project"})

    assert data["success"] is True
    assert data["project_name"] == "empty-project"
    assert data["observation_count"] == 0
    assert data["phase"] == "needs-distill"
    assert data["suggested_slash"] == "/hm:distill"
    assert data["repair_hint"] is None


def test_get_project_status_pending_candidates_adds_review_hint(
    mcp_backend: LocalMemoryBackend,
):
    run(
        mcp_backend.verbatim_store.save(
            Observation(
                id="obs-status-pending",
                session_id="status-pending-session",
                client="codex",
                raw_content="Pending candidate project has usable memory context.",
                content_type="transcript",
                metadata={"project_name": "pending-project"},
            )
        )
    )
    run(
        mcp_backend.structured_store.save_rule_candidate(
            RuleCandidate(
                project_name="pending-project",
                session_id="status-pending-session",
                pattern="Review pending status candidates before promoting them.",
                trigger="When older pending items remain after distill",
                examples=["obs-status-pending"],
                confidence=0.6,
            )
        )
    )

    data = call_tool("get_project_status", {"project_name": "pending-project"})

    assert data["success"] is True
    assert data["phase"] == "ready"
    assert data["suggested_slash"] == "/hm:wake"
    assert data["repair_hint"] == "/hm:review"
    assert "Pending candidates remain" in data["repair_reason"]


def test_ingest_sessions_mcp_uses_project_scoped_codex_archive(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive_root = tmp_path / "archives"
    project_root = tmp_path / "demo-project"
    other_root = tmp_path / "other-project"
    project_root.mkdir()
    other_root.mkdir()
    write_codex_archive_session(
        archive_root,
        "2026-05-17-project",
        user_text="Project archive session",
        assistant_text="Archived answer for the current project",
        cwd=str(project_root),
    )
    write_codex_archive_session(
        archive_root,
        "2026-05-17-other",
        user_text="Other archive session",
        assistant_text="Archived answer for another project",
        cwd=str(other_root),
    )
    patch_cli_adapters(monkeypatch, codex_archive_root=archive_root)
    monkeypatch.chdir(project_root)

    data = call_tool(
        "ingest_sessions",
        {
            "project_name": "demo",
            "client": "codex-archive",
            "limit": 10,
        },
    )

    assert data["success"] is True
    assert "Project-scope sessions: 1" in data["output"]
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert [observation.session_id for observation in observations] == [
            "2026-05-17-project",
        ]
    finally:
        run(backend.close())


def test_prepare_session_distill_returns_one_call_evidence_packet(
    mcp_backend: LocalMemoryBackend,
):
    data = call_tool(
        "prepare_session_distill",
        {
            "project_name": "test-project",
            "run_ingest": False,
            "observation_limit": 1,
            "max_chars_per_observation": 80,
        },
    )

    assert data["success"] is True
    assert data["ingest"]["skipped"] is True
    assert data["observation_count"] == 1
    assert data["observations"][0]["source"].startswith("observation:")
    assert "SQLite FTS5" in data["observations"][0]["raw_content"]
    assert any("Do not call Bash" in item for item in data["distill_instructions"])


@pytest.mark.parametrize(
    "client",
    ["cursor", "antigravity", "opencode", "hermes", "agent"],
)
def test_prepare_session_distill_accepts_generic_agent_clients(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for key in list(os.environ):
        if key.startswith("CLAUDE_CODE"):
            monkeypatch.delenv(key, raising=False)

    data = call_tool(
        "prepare_session_distill",
        {
            "project_name": "test-project",
            "client": client,
            "run_ingest": False,
        },
    )

    assert data["success"] is True
    assert data["client"] == client
    assert data["resolved_client"] == "claude-code"


def test_search_memory_no_project(mcp_backend: LocalMemoryBackend):
    resp = rpc("tools/call", {
        "name": "search_memory",
        "arguments": {"project_name": "test-project", "query": "SQLite"},
    })
    result = resp["result"]["content"][0]["text"]
    data = json.loads(result)
    assert "memory_entries" in data


def test_search_memory_scope_all_includes_project_context(mcp_backend: LocalMemoryBackend):
    run(
        LocalProjectProfileStore(mcp_backend.data_dir).save(
            ProjectProfile(
                project_name="test-project",
                stacks=["python", "sqlite"],
            )
        )
    )

    data = call_tool(
        "search_memory",
        {
            "query": "SQLite",
            "scope": "all",
            "mode": "fts",
        },
    )

    assert data["memory_entries"][0]["project_name"] == "test-project"
    assert data["memory_entries"][0]["tech_stack"] == ["python", "sqlite"]
    assert data["observations"][0]["project_name"] == "test-project"
    assert data["observations"][0]["tech_stack"] == ["python", "sqlite"]


@requires_embeddings
def test_search_memory_reports_effective_mode(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    entries = run(mcp_backend.structured_store.list_memory_entries("test-project", limit=10))
    seed_persisted_embedding(mcp_backend, entries[0].id, (1.0, 3.0))
    patch_fake_embedding_loader(monkeypatch)
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


def test_tool_error_message_includes_class_and_message(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing tool must surface its exception class + message to the client.

    Regression guard for v2.2 release: an external tester reported every
    ``suggest_*`` write returning ``Internal tool error`` with no further
    information, which made root-causing impossible without SSH'ing into
    the MCP server's stderr stream. The handler still hides the full
    traceback, but the JSON-RPC error message must now carry enough text
    that an agent can debug from the client side.
    """
    from harness_mem.mcp import server as mcp_server

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("structured store offline")

    # Patch the registered handler so we don't depend on which production
    # path happens to fail. Restoring in monkeypatch teardown keeps the
    # other tests in this module insulated.
    original = mcp_server.TOOLS["suggest_memory_entry"]["handler"]
    monkeypatch.setitem(
        mcp_server.TOOLS["suggest_memory_entry"], "handler", boom
    )
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "suggest_memory_entry",
                "arguments": {
                    "project_name": "release-gate",
                    "category": "decision",
                    "content": "anything long enough to be valid input",
                    "source": "observation:gate",
                },
            },
        }
        response = handle_request(request)
    finally:
        monkeypatch.setitem(
            mcp_server.TOOLS["suggest_memory_entry"], "handler", original
        )

    assert response is not None
    assert response["error"]["code"] == -32000
    message = response["error"]["message"]
    assert "suggest_memory_entry" in message
    assert "RuntimeError" in message
    assert "structured store offline" in message
