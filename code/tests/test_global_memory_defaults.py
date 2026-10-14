"""Global defaults read only current SQLite knowledge without project setup."""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import read_query_support, read_search_handlers, read_wake_handlers, server
from harness_mem.mcp.read_projection import reading_tokens
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    instance = LocalMemoryBackend(tmp_path / "isolated-data")
    asyncio.run(instance.init())
    server.set_backend_override(instance)
    # No active project or readable project configuration is needed to recall.
    workspace = tmp_path / "unrelated-workspace"
    workspace.mkdir()
    (workspace / ".harness-mem.toml").write_text("invalid = [", encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        read_wake_handlers, "get_active_project",
        Mock(side_effect=AssertionError("global recall must not resolve a project")),
    )
    monkeypatch.setattr(
        read_wake_handlers, "_build_distill_maintenance_offer",
        Mock(side_effect=AssertionError("global recall must not read project profiles")),
    )
    try:
        yield instance
    finally:
        server.set_backend_override(None)
        asyncio.run(instance.close())


def _seed(backend, project, title, statement, *, module="retrieval"):
    entry = KnowledgeEntry(
        project_name=project, module_path=[module], title=title, statement=statement,
    )
    candidate = KnowledgeCandidate(
        project_name=project, candidate_type="memory", statement=statement,
    )
    source = backend.data_dir / "fixture-source.md"
    source.write_text("Isolated fictional fixture.\n", encoding="utf-8")
    store = backend.structured_store.knowledge_store
    asyncio.run(store.apply_current_change(
        candidate_before=candidate,
        candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=AssimilationDecision(
            project_name=project, candidate_id=candidate.id, disposition="add",
            canonical_truth_ids=[entry.id], reason="Isolated global recall fixture.",
        ),
        added_entries=[entry], predecessor_entries=[],
        source_refs_by_entry={entry.id: [ProjectKnowledgeSourceRef(
            label=source.name, target=source.as_uri(), kind="repository", digest="b" * 64,
        )]},
    ))
    return entry


@pytest.mark.parametrize("context_project", [None, "alpha", "unknown-project"])
def test_search_defaults_all_even_with_project_context(backend, context_project):
    _seed(backend, "alpha", "Weak hit", "sqlite advice")
    _seed(backend, "zeta", "Strong hit", "sqlite sqlite sqlite advice")
    payload = server.tool_search_memory(query="sqlite", project_name=context_project)
    assert payload["project_name"] is None
    assert payload["status"] == "answered"
    assert [item["project_name"] for item in payload["memories"]] == ["zeta", "alpha"]
    assert set(payload) == {"project_name", "query", "status", "memories"}
    assert all(set(item) == {"title", "statement", "project_name"} for item in payload["memories"])


def test_global_dedup_and_limit_follow_relevance_across_module_labels(backend):
    first = _seed(backend, "alpha", "Shared procedure", "sqlite advice", module="storage")
    _seed(backend, "zeta", "Shared procedure", "sqlite advice", module="local storage")
    strongest = _seed(backend, "zeta", "Best match", "sqlite sqlite sqlite guidance")
    found = asyncio.run(search_current_knowledge(backend, query="sqlite", limit=2))
    assert found == [strongest, first]
    assert asyncio.run(search_current_knowledge(backend, query="sqlite", limit=1)) == [strongest]
    assert len(asyncio.run(list_current_knowledge(backend))) == 2
    assert len(asyncio.run(list_current_knowledge(backend, project_name="zeta"))) == 2


def test_project_scope_keeps_filter_and_blank_query_module_projection(backend):
    entry = _seed(backend, "alpha", "A decision", "sqlite alpha decision")
    _seed(backend, "zeta", "Z decision", "sqlite zeta decision")
    project = server.tool_search_memory(query="sqlite", project_name="alpha", scope="project")
    assert project["project_name"] == "alpha"
    assert project["memories"] == [{"title": entry.title, "statement": entry.statement}]
    library = server.tool_search_memory(query="", project_name="alpha", scope="project")
    assert library["memories"][0]["module"] == entry.module_path
    assert server.tool_search_memory(query="sqlite", scope="project")["success"] is False
    assert server.tool_search_memory(query="sqlite", scope="unexpected")["success"] is False


def test_global_empty_query_reads_all_current_knowledge(backend):
    _seed(backend, "alpha", "A decision", "sqlite alpha decision")
    _seed(backend, "zeta", "Z decision", "sqlite zeta decision")
    payload = server.tool_search_memory(query="", project_name="alpha")
    assert len(payload["memories"]) == 2
    assert all(item["module"] == ["retrieval"] for item in payload["memories"])
    assert all(set(item) == {"module", "title", "statement", "project_name"} for item in payload["memories"])


def test_empty_project_filter_guides_recovery_without_searching_outside_it(backend, monkeypatch):
    _seed(backend, "alpha", "Theme", "Use blue links.")
    entry = _seed(backend, "global", "Benchmark privacy", "Keep internal benchmark material private.")
    with monkeypatch.context() as filtered:
        filtered.setattr(backend.structured_store.knowledge_store, "known_projects",
                         AsyncMock(side_effect=AssertionError("explicit filtering must not search other projects")))
        result = server.tool_search_memory(query="benchmark", project_name="alpha", scope="project", budget_tokens=500)
    assert result["status"] == "empty"
    assert result["memories"] == []
    assert "scope='all'" in result["message"]
    assert "Unless the user requested project-only memory" in result["message"]
    assert entry.statement not in str(result)
    assert reading_tokens(result) <= 500

    recovered = server.tool_search_memory(query="benchmark", project_name="alpha")
    assert recovered["memories"] == [{"project_name": "global", "title": entry.title, "statement": entry.statement}]
    assert "message" not in recovered


def test_global_read_excludes_legacy_raw_and_job_material(backend):
    entry = _seed(backend, "alpha", "Current rule", "cleanrecalltoken current rule")
    asyncio.run(backend.structured_store.save_memory_entry(MemoryEntry(
        project_name="zeta", category="decision", source="fixture", status="user_confirmed",
        content="cleanrecalltoken obsolete compatibility material",
    )))
    asyncio.run(backend.verbatim_store.save(Observation(
        session_id="fictional-session", client="codex", content_type="turn",
        raw_content="cleanrecalltoken raw source material", metadata={"project_name": "zeta"},
    )))
    asyncio.run(backend.structured_store.knowledge_store.save_candidate(KnowledgeCandidate(
        project_name="zeta", candidate_type="memory",
        statement="cleanrecalltoken unfinished candidate material",
    )))
    payload = server.tool_search_memory(query="cleanrecalltoken", _include_diagnostics=True)
    assert payload["memories"] == [{
        "project_name": "alpha", "title": entry.title, "statement": entry.statement,
    }]
    for forbidden in ("obsolete compatibility material", "raw source material", "unfinished candidate material"):
        assert forbidden not in str(payload)
    assert payload["context_plan"]["source_ids"] == [entry.id]


@pytest.mark.parametrize("context_project", [None, "alpha", "unknown-project"])
def test_wake_defaults_all_without_active_project_or_profile(backend, context_project):
    _seed(backend, "alpha", "A decision", "sqlite alpha decision")
    _seed(backend, "zeta", "Z decision", "sqlite zeta decision")
    payload = server.tool_wake(project_name=context_project)
    assert payload["success"] is True
    assert payload["project_name"] is None
    assert payload["long_term_memory"] == []
    assert payload["available_count"] == 2
    current = server.tool_search_memory(**payload["continuation"]["arguments"])
    assert {item["project_name"] for item in current["memories"]} == {"alpha", "zeta"}
    assert payload["maintenance_available"] is False


def test_wake_explicit_project_filter_remains_available(backend, monkeypatch):
    entry = _seed(backend, "alpha", "A decision", "sqlite alpha decision")
    _seed(backend, "zeta", "Z decision", "sqlite zeta decision")
    monkeypatch.setattr(read_wake_handlers, "_build_distill_maintenance_offer", Mock(return_value={}))
    availability = server.tool_wake(project_name="alpha", scope="project")
    assert availability["long_term_memory"] == []
    assert availability["available_count"] == 1
    payload = server.tool_wake(project_name="alpha", scope="project", current_task="sqlite")
    assert payload["long_term_memory"] == [{"title": entry.title, "statement": entry.statement}]
    monkeypatch.setattr(read_wake_handlers, "get_active_project", lambda: "alpha")
    assert server.tool_wake(scope="project", current_task="sqlite")["long_term_memory"] == payload["long_term_memory"]
    monkeypatch.setattr(read_wake_handlers, "get_active_project", lambda: None)
    assert server.tool_wake(scope="project")["success"] is False
    assert server.tool_wake(scope="unexpected")["success"] is False


def test_wake_task_query_ranks_all_projects_and_excludes_unrelated(backend):
    _seed(backend, "alpha", "Weak hit", "sqlite advice")
    _seed(backend, "zeta", "Strong hit", "sqlite sqlite sqlite advice")
    _seed(backend, "beta", "Unrelated", "animation rules")
    payload = server.tool_wake(current_task="sqlite", project_name="beta")
    assert [item["project_name"] for item in payload["long_term_memory"]] == ["zeta", "alpha"]


def test_feedback_tracks_only_global_representatives_in_their_source_project(backend):
    a = _seed(backend, "alpha", "Shared rule", "sqlite shared rule")
    hidden = _seed(backend, "zeta", "Shared rule", "sqlite shared rule")
    z = _seed(backend, "zeta", "Z rule", "sqlite zeta rule")
    payload = server.tool_search_memory(
        query="sqlite", project_name="unrelated-workspace", _include_diagnostics=True,
        budget_tokens=4000,
    )
    assert payload["record_outcome_call"] is None  # Multiple project receipts cannot become one call.
    calls = payload["record_outcome_calls"]
    assert {call["arguments"]["project_name"] for call in calls} == {"alpha", "zeta"}
    assert set(payload["context_plan"]["source_ids"]) == {a.id, z.id}
    assert hidden.id not in str(payload)
    for call in calls:
        arguments = call["arguments"]
        assert arguments["surface"] == "search_all"
        assert "outcome" not in arguments
        recorded = server.tool_record_context_outcome(**arguments, outcome="used")
        replayed = server.tool_record_context_outcome(**arguments, outcome="used")
        assert recorded["success"] is True
        assert recorded["signal_ids"] == replayed["signal_ids"]
        assert recorded["truth_mutated"] is False
    wrong = server.tool_record_context_outcome(
        project_name="alpha", surface="search_all", outcome="used",
        source_ids=[z.id], retrieval_id=payload["retrieval_id"],
    )
    assert wrong["success"] is False
    signals = asyncio.run(backend.structured_store.query_retrieval_signals(
        "unrelated-workspace", limit=20,
    ))
    assert signals == []


@pytest.mark.parametrize("context_project", [None, "alpha", "unknown-project"])
def test_autopilot_searches_all_and_preserves_feedback_bindings(backend, context_project):
    _seed(backend, "alpha", "Timeout alpha", "pytest timeout alpha fix")
    _seed(backend, "zeta", "Timeout zeta", "pytest timeout zeta fix")
    payload = server.tool_autopilot_search_tick(
        event_name="tool_result", project_name=context_project,
        tool_name="pytest", tool_result="TimeoutError", is_error=True,
    )
    assert payload["success"] is True
    assert payload["search_executed"] is True
    injection = payload["context_injection"]
    assert {item["project_name"] for item in injection["memories"]} == {"alpha", "zeta"}
    assert injection["record_outcome_call"] is None
    assert len(injection["record_outcome_calls"]) == 2
    assert len(injection["source_ids"]) == 2
    for call in injection["record_outcome_calls"]:
        assert server.tool_record_context_outcome(**call["arguments"], outcome="ignored")["success"] is True


@pytest.mark.parametrize("failed_reader", ["known_projects", "list_entries"])
@pytest.mark.parametrize("error_type", [ValueError, OSError, sqlite3.DatabaseError])
def test_global_read_fault_is_unavailable_not_partial_or_empty(backend, monkeypatch, failed_reader, error_type):
    _seed(backend, "alpha", "A decision", "sqlite alpha decision")
    _seed(backend, "zeta", "Z decision", "sqlite zeta decision")
    store = backend.structured_store.knowledge_store
    original = getattr(store, failed_reader)

    async def failing_reader(*args, **kwargs):
        if failed_reader == "known_projects" or args[0] == "zeta":
            raise error_type("private storage details")
        return await original(*args, **kwargs)

    monkeypatch.setattr(store, failed_reader, failing_reader)
    search = server.tool_search_memory(query="sqlite")
    assert search["status"] == "unavailable"
    assert search["memories"] == []
    assert "private storage details" not in str(search)
    wake = server.tool_wake(current_task="sqlite")
    assert wake["success"] is False
    assert "could not be read" in wake["message"]
    autopilot = server.tool_autopilot_search_tick(
        event_name="tool_result", tool_name="sqlite", tool_result="TimeoutError", is_error=True,
    )
    assert autopilot["success"] is False
    assert autopilot["context_injection"] is None
    assert asyncio.run(backend.structured_store.query_retrieval_signals("alpha")) == []


def test_global_failed_signal_write_preserves_memory_but_no_false_feedback(backend, monkeypatch):
    a = _seed(backend, "alpha", "A rule", "sqlite alpha rule")
    z = _seed(backend, "zeta", "Z rule", "sqlite zeta rule")
    actual_writer = read_query_support.record_retrieval_signal

    async def fail_one(backend, **kwargs):
        if kwargs["target_id"] == z.id:
            return None
        return await actual_writer(backend, **kwargs)

    monkeypatch.setattr(read_query_support, "record_retrieval_signal", fail_one)
    payload = server.tool_search_memory(query="sqlite", _include_diagnostics=True, budget_tokens=4000)
    assert len(payload["memories"]) == 2
    assert payload["retrieval_receipt"]["state"] == "degraded"
    assert payload["retrieval_receipt"]["failed"] == 1
    assert payload["context_plan"]["source_ids"] == [a.id]
    assert [call["arguments"]["project_name"] for call in payload["record_outcome_calls"]] == ["alpha"]


@pytest.mark.parametrize("handler", [read_search_handlers, read_wake_handlers])
def test_global_backend_failures_are_plain_and_distinct_from_empty(monkeypatch, handler):
    monkeypatch.setattr(handler, "_get_backend", Mock(side_effect=OSError("private details")))
    result = handler.tool_search_memory(query="sqlite") if handler is read_search_handlers else handler.tool_wake()
    assert result.get("status") == "unavailable" or result.get("success") is False
    assert "private details" not in str(result)
    monkeypatch.setattr(handler, "_get_backend", lambda: SimpleNamespace(
        runtime_state="degraded_fallback", runtime_error="private details",
    ))
    result = handler.tool_search_memory(query="sqlite") if handler is read_search_handlers else handler.tool_wake()
    assert result.get("status") == "unavailable" or result.get("success") is False


def test_empty_global_store_is_successful_without_feedback(backend):
    search = server.tool_search_memory(query="absent", _include_diagnostics=True)
    assert search["status"] == "empty"
    assert search["record_outcome_calls"] == []
    assert search["record_outcome_call"] is None
    assert search["context_plan"]["source_ids"] == []
    assert server.tool_wake()["long_term_memory"] == []
    assert server.tool_autopilot_search_tick(event_name="session_start")["search_executed"] is False


def test_reopened_global_search_retains_chinese_matching_without_source_files(backend):
    entry = _seed(
        backend, "fictional-project", "开启后台整理",
        "后台整理默认关闭，只有明确开启后才会自动整理会话。",
    )
    # The frozen current knowledge stays readable when its repository is gone.
    (backend.data_dir / "fixture-source.md").unlink()
    reopened = LocalMemoryBackend(backend.data_dir)
    asyncio.run(reopened.init())
    server.set_backend_override(reopened)
    try:
        for query in ("后台整理怎么开启？", "请问之前如何开启后台整理", "【后台整理】"):
            payload = server.tool_search_memory(query=query, project_name="different-workspace")
            assert payload["memories"] == [{
                "title": entry.title, "statement": entry.statement, "project_name": entry.project_name,
            }]
        assert server.tool_search_memory(query="自动删除怎么开启？")["status"] == "empty"
        assert server.tool_search_memory(query=".env")["status"] == "empty"
    finally:
        server.set_backend_override(backend)
        asyncio.run(reopened.close())
