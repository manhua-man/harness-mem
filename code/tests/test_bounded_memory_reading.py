"""Whole-fact reading through the real current store and MCP consumer."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from harness_mem.commands import token_estimator
from harness_mem.commands.wake import build_wake_injection
from harness_mem.core.schemas import (
    AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
)
from harness_mem.mcp import read_query_support, server
from harness_mem.mcp.read_projection import reading_tokens
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    store = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(store.init())
    server.set_backend_override(store)
    try:
        yield store
    finally:
        server.set_backend_override(None)
        asyncio.run(store.close())


def add_memories(backend, statements, *, project="demo", title="Reading rule"):
    entries = [
        KnowledgeEntry(
            project_name=project, title=f"{title} {index:03}", statement=statement,
            module_path=["Reading", "Recovery"],
        )
        for index, statement in enumerate(statements)
    ]
    source = backend.data_dir / f"{project}-source.txt"
    source.write_text("Fictional reading examples.\n", encoding="utf-8")
    reference = ProjectKnowledgeSourceRef(
        label=source.name, target=source.as_uri(), kind="repository",
        digest=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    async def save():
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            project_name=project, candidate_type="memory", statement="Fictional reading examples.",
        )
        decision = AssimilationDecision(
            project_name=project, candidate_id=candidate.id, disposition="add",
            canonical_truth_ids=[entry.id for entry in entries], reason="Isolated test fixture.",
        )
        await store.save_candidate(candidate)
        await store.apply_current_change(
            candidate_before=candidate,
            candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision, added_entries=entries, predecessor_entries=[],
            source_refs_by_entry={entry.id: [reference] for entry in entries},
        )
        await store.cleanup_candidate(candidate.id)

    asyncio.run(save())
    return entries


def _many(count=12):
    return [
        f"paginationtoken independent rule {index:03}. "
        + "Read the whole fact and preserve its supporting context. " * 8
        + f"end-marker-{index:03}"
        for index in range(count)
    ]


def _continue(payload):
    continuation = payload["continuation"]
    assert continuation["tool"] == "search_memory"
    return server.tool_search_memory(**continuation["arguments"])


def _read_all(first, *, budget):
    page = first
    statements = []
    for _ in range(200):
        assert page.get("status") in {"answered", "available", "empty"}, page
        if page.get("detail") != "full":
            assert reading_tokens(page) <= budget
        statements.extend(row["statement"] for row in page["memories"] if "statement" in row)
        if "continuation" not in page:
            return statements
        page = _continue(page)
    pytest.fail("continuation did not finish")


def test_paged_mcp_search_reaches_all_facts_and_applies_the_requested_budget(backend):
    expected = _many()
    add_memories(backend, expected)
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "search_memory", "arguments": {"query": "paginationtoken", "budget_tokens": 600}},
    })
    text = response["result"]["content"][0]["text"]
    first = json.loads(text)
    large = server.tool_search_memory(query="paginationtoken", budget_tokens=1800)
    assert 0 < len(first["memories"]) < len(large["memories"]) <= len(expected)
    assert reading_tokens(text) <= 600
    assert reading_tokens(large) <= 1800
    assert first["memories"][0]["statement"].endswith("end-marker-000")
    actual = _read_all(first, budget=600)
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


@pytest.mark.parametrize("task", [None, " \n\t "])
def test_taskless_wake_offers_global_reading_without_dumping_statements(backend, task):
    add_memories(backend, ["First private-sized fact."])
    add_memories(backend, ["Second project fact."], project="other")
    payload = server.tool_wake(project_name="unrelated", current_task=task)
    assert payload["success"] is True
    assert payload["long_term_memory"] == []
    assert payload["available_count"] == 2
    assert "First private-sized fact" not in json.dumps(payload)
    assert reading_tokens(payload) <= 2000
    assert len(_read_all(_continue(payload), budget=2000)) == 2


def test_task_wake_and_its_continuation_reach_all_matching_facts(backend):
    expected = _many()
    add_memories(backend, expected)
    wake = server.tool_wake(current_task="paginationtoken", budget_tokens=650)
    assert reading_tokens(wake) <= 650
    first = [row["statement"] for row in wake["long_term_memory"]]
    remaining = _read_all(_continue(wake), budget=650)
    assert len(first + remaining) == len(expected)
    assert set(first + remaining) == set(expected)


def test_empty_query_browses_natural_modules_across_all_projects(backend):
    left = add_memories(backend, _many(12))
    right = add_memories(backend, ["A distinct cross-project rule."], project="other")
    page = server.tool_search_memory(query="", budget_tokens=650)
    assert page["memories"][0]["module"] == ["Reading", "Recovery"]
    actual = _read_all(page, budget=650)
    assert set(actual) == {entry.statement for entry in [*left, *right]}


def test_long_fact_gets_whole_entry_reading_and_preserves_complete_prose(backend):
    statement = "longfacttoken " + "完整知识段落。" * 200 + "最后的独立条件。"
    add_memories(backend, [statement])
    index = server.tool_search_memory(query="longfacttoken", budget_tokens=500)
    assert reading_tokens(index) <= 500
    assert index["status"] == "available"
    assert index["detail"] == "index"
    assert "statement" not in index["memories"][0]
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []
    full = _continue(index)
    assert full["detail"] == "full"
    assert full["memories"][0]["statement"] == statement
    assert reading_tokens(full) > 500
    assert "continuation" not in full


def test_very_long_title_is_not_silently_clipped(backend):
    title = "完整标题" * 200
    add_memories(backend, ["hugetitletoken complete fact."], title=title)
    index = server.tool_search_memory(query="hugetitletoken", budget_tokens=400)
    assert index["status"] == "available"
    assert reading_tokens(index) <= 400
    assert index["memories"] == []
    full = _continue(index)
    assert full["memories"][0]["title"] == title + " 000"


def test_saved_revision_change_restarts_reading_instead_of_using_an_old_offset(backend):
    add_memories(backend, _many())
    first = server.tool_search_memory(query="", budget_tokens=600)
    add_memories(backend, ["The newly saved first fact."], title="AAA new fact")
    restarted = _continue(first)
    assert "Memory changed" in restarted["message"]
    assert restarted["memories"][0]["statement"] == "The newly saved first fact."
    assert reading_tokens(restarted) <= 600


def test_cursor_is_bound_to_query_and_explicit_project_filter(backend):
    add_memories(backend, _many())
    first = server.tool_search_memory(query="paginationtoken", budget_tokens=600)
    arguments = first["continuation"]["arguments"]
    other_query = server.tool_search_memory(**{**arguments, "query": "other"})
    other_scope = server.tool_search_memory(**{**arguments, "scope": "project", "project_name": "demo"})
    assert other_query["status"] == other_scope["status"] == "invalid"


@pytest.mark.parametrize("cursor", ["not-a-position", "W10", "Wy0xLDEsMl0", "W3RydWUsMSwyXQ"])
def test_malformed_positions_are_readable_errors(backend, cursor):
    payload = server.tool_search_memory(query="", cursor=cursor)
    assert payload["status"] == "invalid"
    assert payload["memories"] == []


def test_explicit_project_filter_is_kept_across_every_page(backend):
    expected = _many()
    add_memories(backend, expected)
    add_memories(backend, ["paginationtoken other project."], project="other")
    first = server.tool_search_memory(
        query="paginationtoken", scope="project", project_name="demo", budget_tokens=600,
    )
    assert set(_read_all(first, budget=600)) == set(expected)


def test_optional_tokenizer_fallback_uses_utf8_size_not_quarter_characters(backend, monkeypatch):
    add_memories(backend, [f"中文知识 第 {index} 条。" + "完整来源与准确知识。" * 12 for index in range(10)])
    monkeypatch.setattr(token_estimator, "_get_encoder", lambda: None)
    payload = server.tool_search_memory(query="", budget_tokens=1800)
    assert len(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")) <= 1800
    assert len(payload["memories"]) < 10


def test_special_token_spelling_is_counted_as_ordinary_memory_text():
    encoder = token_estimator._get_encoder()
    if encoder is None:
        pytest.skip("optional tokenizer is unavailable")
    text = "A literal <|endoftext|> is part of this memory."
    assert token_estimator.count_tokens(text) == len(encoder.encode(text, disallowed_special=()))
    assert token_estimator.tokenizer_kind == "tiktoken"


def test_autopilot_counts_the_whole_envelope_and_records_only_returned_facts(backend):
    entries = add_memories(backend, _many())
    payload = server.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", tool_name="pytest",
        tool_result="paginationtoken failed", is_error=True, budget_tokens=1400,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1400
    injection = payload["context_injection"]
    shown = {row["statement"] for row in injection["memories"] if "statement" in row}
    expected_ids = {entry.id for entry in entries if entry.statement in shown}
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert {signal.target_id for signal in signals} == expected_ids
    assert set(injection["source_ids"]) == expected_ids
    assert "continuation" in injection


def test_signal_failure_keeps_the_actual_output_within_autopilot_size(backend, monkeypatch):
    add_memories(backend, _many())
    monkeypatch.setattr(read_query_support, "record_retrieval_signal", AsyncMock(return_value=None))
    payload = server.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", is_error=True, budget_tokens=1200,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1200
    assert payload["context_injection"]["retrieval_receipt"]["state"] == "degraded"
    assert payload["context_injection"]["source_ids"] == []


def test_minimal_install_autopilot_keeps_a_usable_reading_result(backend, monkeypatch):
    add_memories(backend, _many())
    monkeypatch.setattr(token_estimator, "_get_encoder", lambda: None)
    payload = server.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", is_error=True, budget_tokens=1400,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1400
    injection = payload["context_injection"]
    if injection["status"] == "available":
        expanded = _continue(injection)
        assert expanded["memories"][0]["statement"].startswith("paginationtoken")
    else:
        assert injection["memories"][0]["statement"].startswith("paginationtoken")


def test_hook_and_wake_feedback_match_the_actual_returned_statements(backend):
    entries = add_memories(backend, _many())
    text = asyncio.run(build_wake_injection(backend, "demo", current_task="paginationtoken", budget_tokens=650))
    assert reading_tokens(text) <= 650
    shown = {entry.id for entry in entries if entry.statement in text}
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced"))
    assert shown
    assert {signal.target_id for signal in signals} == shown


@pytest.mark.parametrize("task", [None, "paginationtoken"])
def test_small_hook_page_supplies_a_usable_mcp_reading_call(backend, task):
    add_memories(backend, [f"paginationtoken short fact {index}." for index in range(12)])
    text = asyncio.run(build_wake_injection(backend, "demo", current_task=task, budget_tokens=150))
    assert reading_tokens(text) <= 150
    if task is None:
        assert "12 current memories available" in text
        assert "paginationtoken" not in text
        assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
    arguments = json.loads(text.split("Continue reading: search_memory ")[1])
    page = server.tool_search_memory(**arguments)
    assert page["status"] in {"answered", "available"}
    assert len(_read_all(page, budget=arguments["budget_tokens"])) > 0


@pytest.mark.parametrize("surface", ["search", "wake", "automatic", "hook"])
def test_short_answer_remains_readable_next_to_a_full_term_reference(backend, surface):
    add_memories(backend, ["Fourteen days."], title="Lease timeout")
    add_memories(backend, ["See the deployment handbook."], title="Aurora lease timeout")
    task = "Aurora lease timeout"
    if surface == "hook":
        result = asyncio.run(build_wake_injection(backend, "demo", current_task=task))
    elif surface == "wake":
        result = server.tool_wake(current_task=task)
    elif surface == "automatic":
        result = server.tool_autopilot_search_tick(event_name="tool_result", current_task=task, is_error=True)
    else:
        result = server.tool_search_memory(query=task)
    assert "Fourteen days." in str(result)


def test_sql_keyword_lookup_through_the_real_mcp_reader(backend):
    add_memories(backend, ["Use WITH for a CTE and WHERE for filtering."], title="SQL clauses")
    # Keyword variants belong to the ranking unit tests; one proves MCP wiring.
    result = server.tool_search_memory(query="WITH")
    assert result["status"] == "answered"
    assert result["memories"][0]["statement"] == "Use WITH for a CTE and WHERE for filtering."
