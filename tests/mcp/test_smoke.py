from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, Observation, RelationFact
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import (
    fake_embed_texts,
    patch_cli_adapters,
    run,
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


def test_tools_list():
    resp = rpc("tools/list")
    tools = resp["result"]["tools"]
    assert len(tools) == 33
    names = {tool["name"] for tool in tools}
    expected = {
        "search_memory", "timeline", "get_observations",
        "search_raw", "search_skills",
        "get_task_handoffs", "get_confirmed_rules", "get_project_profile",
        "get_project_status", "ingest_sessions", "prepare_session_distill",
        "list_candidates", "auto_review_candidates",
        "trace_relations",
        "create_rule_candidate", "confirm_rule", "reject_rule", "suggest_rule",
        "suggest_supersede", "confirm_supersede", "reject_supersede", "suggest_correction",
        "suggest_skill", "confirm_skill", "reject_skill", "record_skill_result",
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

    data = call_tool("list_candidates", {"project_name": "test-project"})

    assert data["success"] is True
    assert data["status"] == "pending"
    assert data["count"] == 4
    assert data["total_count"] == 4
    assert data["rule_count"] == 1
    assert data["memory_entry_count"] == 1
    assert data["relation_fact_count"] == 1
    assert data["supersede_count"] == 1
    ids_by_type = {candidate["type"]: candidate["id"] for candidate in data["candidates"]}
    assert ids_by_type == {
        "rule": rule["candidate_id"],
        "memory_entry": entry["entry_id"],
        "relation_fact": fact["fact_id"],
        "supersede": supersede["candidate_id"],
    }
    tools_by_type = {candidate["type"]: candidate["confirm_tool"] for candidate in data["candidates"]}
    assert tools_by_type == {
        "rule": "confirm_rule",
        "memory_entry": "confirm_memory_entry",
        "relation_fact": "confirm_relation_fact",
        "supersede": "confirm_supersede",
    }

    confirmed = call_tool("confirm_memory_entry", {"entry_id": entry["entry_id"]})
    assert confirmed["success"] is True

    after_confirm = call_tool("list_candidates", {"project_name": "test-project"})
    pending_ids = {candidate["id"] for candidate in after_confirm["candidates"]}
    assert entry["entry_id"] not in pending_ids
    assert after_confirm["count"] == 3


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
