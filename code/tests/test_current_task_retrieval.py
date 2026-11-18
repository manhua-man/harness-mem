"""Explicit task discovery never leaks context or silently retargets reads."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.mcp import read_search_handlers as handlers
from harness_mem import read_knowledge


@pytest.fixture
def task_search(monkeypatch, tmp_path):
    from harness_mem.embedding import current_semantic

    entries = [
        KnowledgeEntry(id="literal", project_name="alpha", title="SQLite backup",
                       statement="Copy the database and attachments.", module_path=["Backup"]),
        KnowledgeEntry(id="global", project_name="global", title="Keep the recovery copy",
                       statement="Keep the original until restoration is verified. Never overwrite it.",
                       module_path=["Recovery"]),
        KnowledgeEntry(id="other", project_name="beta", title="Unrelated decision",
                       statement="A different project's rule.", module_path=["Other"]),
    ]
    backend = SimpleNamespace(data_dir=tmp_path, runtime_state="canonical", runtime_error=None)
    available = SimpleNamespace(ordered_ids=["global", "literal", "other"], binding="model-one",
                                status="available", reason=None)
    seen = []

    def semantic(documents, **kwargs):
        seen.append((documents, kwargs))
        return available

    async def current(_backend, *, project_name, **kwargs):
        return [entry for entry in entries if project_name is None or entry.project_name == project_name]

    monkeypatch.setattr(read_knowledge, "_current_entries", current)
    monkeypatch.setattr(current_semantic, "semantic_discovery", semantic)
    monkeypatch.setattr(handlers, "_get_backend", lambda: backend)
    monkeypatch.setattr(handlers, "_record_search_quality_signals", AsyncMock(return_value={
        "contract_version": "retrieval-signal-receipt-v1", "attempted": 1, "recorded": 1,
        "failed": 0, "state": "ok", "source_ids": [], "content_recorded": False,
    }))
    return entries, backend, available, seen


def _discover(**kwargs):
    return handlers.tool_search_memory(query="SQLite backup", task_context="Move alpha to a new machine.",
                                       budget_tokens=4000, **{"detail": "candidates", **kwargs})


def _open(cursor, **overrides):
    arguments = dict(query="SQLite backup", task_context="Move alpha to a new machine.",
                     cursor=cursor, detail="full", budget_tokens=4000)
    arguments.update(overrides)
    return handlers.tool_search_memory(**arguments)


def test_default_natural_question_can_open_optional_semantic_hit(task_search):
    _entries, _, available, seen = task_search
    available.ordered_ids = ["global"]
    query = "How can I safely move my files to another machine?"
    result = handlers.tool_search_memory(query=query, detail="candidates", budget_tokens=4000)
    assert seen[0][1]["task_context"] == ""
    assert seen[0][1]["minimum_score"] > 0
    hit, = result["memories"]
    assert hit["title"] == "Keep the recovery copy"
    opened = handlers.tool_search_memory(query=query, read_cursor=hit["read_cursor"], detail="full", budget_tokens=4000)
    assert "until restoration is verified" in opened["memories"][0]["statement"]


def test_unconfigured_search_can_use_several_topic_fragments_in_a_natural_question(task_search):
    entries, _, available, _ = task_search
    entries.extend([
        KnowledgeEntry(project_name="alpha", title="从条目归纳产品结构",
                       statement="把外部模型放在支撑层。先梳理稳定职责与依赖，决定先投哪里再交给迭代。",
                       module_path=["Structure"]),
        KnowledgeEntry(project_name="beta", title="模型价格",
                       statement="另一个产品有多种模型价格。", module_path=["Costs"]),
    ])
    available.status = "unavailable"
    question = "我手里只有一长串功能、模型和接口，想先看清产品到底分哪几大块、相互怎么配合。需要我先分组吗？这和决定接下来先做什么是一回事吗？"
    result = handlers.tool_search_memory(query=question, budget_tokens=4000)
    assert result["memories"][0]["title"] == "从条目归纳产品结构"
    assert not handlers.tool_search_memory(query="之前保存过 Fable 5 的发布日期吗？")["memories"]


def test_current_rows_union_cross_project_and_actual_full_read(task_search):
    entries, _, _, seen = task_search
    result = _discover()
    assert result["detail"] == "candidates"
    assert result["discovery"] == {"semantic": "available", "relevance": "unassessed"}
    assert result["memories"][0]["project_name"] == "alpha"  # exact-title readback priority
    global_candidate = next(row for row in result["memories"] if row["project_name"] == "global")
    assert all("statement" not in item for item in result["memories"])
    opened = _open(global_candidate["read_cursor"])
    assert opened["memories"][0]["statement"] == entries[1].statement
    assert opened["memories"][0]["statement"].endswith("Never overwrite it.")
    assert seen[0][1]["task_context"] == "Move alpha to a new machine."
    assert len(seen[0][0]) == 3


@pytest.mark.parametrize("context", [None, "Move beta to a new machine.", "Move alpha to a new machine.\n"])
def test_selected_read_requires_exact_supplied_context(task_search, context):
    result = _discover()
    response = _open(result["memories"][0]["read_cursor"], task_context=context)
    assert response["status"] == "invalid"
    assert not response["memories"]


@pytest.mark.parametrize("change", ["model", "backend", "scope"])
def test_selected_read_binds_retrieval_backend_model_and_project(task_search, change, tmp_path):
    _, backend, semantic, _ = task_search
    result = _discover()
    arguments = {}
    if change == "model":
        semantic.binding = "model-two"
    elif change == "backend":
        backend.data_dir = tmp_path / "different-store"
    else:
        arguments.update(project_name="alpha", scope="project")
    response = _open(result["memories"][0]["read_cursor"], **arguments)
    assert response["status"] == "invalid"
    assert not response["memories"]


def test_explicit_filter_is_applied_before_semantic_discovery(task_search):
    _, _, _, seen = task_search
    result = _discover(project_name="alpha", scope="project")
    assert [key for key, _ in seen[0][0]] == ["literal"]
    assert {row["project_name"] for row in result["memories"]} == {"alpha"}


def test_no_context_keeps_existing_exact_read_and_does_not_load_semantics(task_search):
    entries, _, _, seen = task_search
    result = handlers.tool_search_memory(query="SQLite backup", budget_tokens=4000)
    assert result["memories"][0]["statement"] == entries[0].statement
    assert "discovery" not in result
    assert seen == []


def test_unavailable_semantics_keeps_lexical_candidate_and_reports_limitation(task_search):
    _, _, semantic, _ = task_search
    semantic.status, semantic.reason = "unavailable", "Local model is not configured."
    result = _discover()
    assert [row["title"] for row in result["memories"]] == ["SQLite backup"]
    assert result["discovery"]["semantic"] == "unavailable"
    assert result["discovery"]["reason"] == "Local model is not configured."
    semantic.status, semantic.binding = "available", "newly-configured-model"
    assert _open(result["memories"][0]["read_cursor"])["status"] == "invalid"


def test_empty_semantic_and_lexical_results_do_not_claim_memory_absence(task_search):
    _, _, semantic, _ = task_search
    semantic.status, semantic.reason = "unavailable", "Local model unavailable."
    result = handlers.tool_search_memory(query="Unknown requested limit", task_context="An unrelated task.")
    assert result["memories"] == []
    assert result["status"] == "empty"
    assert "does not establish" in result["message"]
    assert result["discovery"]["semantic"] == "unavailable"


def test_calls_do_not_share_or_echo_full_task_context(task_search):
    entries, _, _, seen = task_search
    context = "Full task with an exclusion. " * 160
    result = handlers.tool_search_memory(query="SQLite backup", task_context=context, budget_tokens=1400,
                                        detail="candidates")
    assert result["detail"] == "candidates"
    assert context not in json.dumps(result)
    if "continuation" in result:
        assert result["continuation"]["reuse_arguments"] == ["task_context"]
    other = _discover()
    assert seen[-1][1]["task_context"] != context
    chosen = next(row for row in other["memories"] if row["project_name"] == "global")
    assert _open(chosen["read_cursor"])["memories"][0]["statement"] == entries[1].statement


def test_semantic_stale_identity_is_never_reintroduced(task_search):
    entries, backend, semantic, _ = task_search
    semantic.ordered_ids = ["deleted-id", "global"]
    result = asyncio.run(read_knowledge.search_current_knowledge(
        backend, query="SQLite backup", task_context="Migration"))
    assert {entry.id for entry in result} == {entries[0].id, entries[1].id}


def test_context_discovery_preserves_semantic_order_under_weak_lexical_noise(task_search, monkeypatch):
    entries, backend, semantic, _ = task_search
    semantic.ordered_ids = ["global", "literal", "other"]
    monkeypatch.setattr(read_knowledge, "_rank_current_entries", lambda *args, **kwargs: [entries[2], entries[0]])
    result = asyncio.run(read_knowledge.search_current_knowledge(
        backend, query="How should this migration proceed?", task_context="Move alpha to another machine."))
    assert [entry.id for entry in result] == ["global", "literal", "other"]


def test_nontext_context_is_rejected_before_backend_read():
    assert handlers.tool_search_memory("topic", task_context={})["success"] is False


def test_explicit_context_is_available_through_public_jsonrpc_schema(task_search):
    from harness_mem.mcp import server

    schema = server.TOOLS["search_memory"]["input_schema"]
    assert schema["properties"]["task_context"]["type"] == "string"
    assert "task_context" not in schema["required"]
    response = server.handle_request({"jsonrpc": "2.0", "id": 27, "method": "tools/call", "params": {
        "name": "search_memory", "arguments": {"query": "SQLite backup", "task_context": "Move alpha safely.",
                                                   "budget_tokens": 4000}}})
    assert "error" not in response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["discovery"]["semantic"] == "available"
    assert payload["detail"] == "mixed"
    assert all("statement" in item for item in payload["memories"])


def test_auto_returns_complete_facts_when_they_cost_less_than_preview_links(task_search):
    from harness_mem.mcp.read_projection import reading_tokens

    entries, _, _, _ = task_search
    previews = _discover()
    complete = _discover(detail="auto")
    assert complete["detail"] == "mixed"
    assert complete["status"] == "available"
    assert complete["discovery"]["relevance"] == "unassessed"
    expected = {(entry.project_name, entry.title): entry.statement for entry in entries}
    for actual, preview in zip(complete["memories"], previews["memories"]):
        assert actual["statement"] == expected[actual["project_name"], actual["title"]]
        assert "read_cursor" not in actual and "preview" not in actual
        assert reading_tokens(actual) < reading_tokens(preview)
    assert reading_tokens(complete) <= 4000


def test_mixed_page_keeps_long_facts_strict_and_does_not_record_unread_hits(task_search, monkeypatch):
    from harness_mem.mcp.read_projection import reading_tokens

    entries, _, semantic, _ = task_search
    long = KnowledgeEntry(id="long", project_name="gamma", title="Recovery condition",
        statement="Important recovery. " + "必须保留所有原始恢复条件。" * 500 + "FINAL: both owners must approve.",
        module_path=["Recovery"])
    entries.append(long)
    semantic.ordered_ids.append("long")
    recorder = handlers._record_search_quality_signals
    result = _discover(detail="auto", _include_diagnostics=True)
    assert result["detail"] == "mixed" and reading_tokens(result) <= 4000
    preview = next(row for row in result["memories"] if row["project_name"] == "gamma")
    assert "statement" not in preview and "read_cursor" in preview
    assert result["memory_count"] == 3
    assert {row["source_id"] for row in result["answer_ready_context"]["truth"]} == {"literal", "global", "other"}
    assert result["answer_ready_context"]["safe_to_answer"] is False
    assert {entry.id for call in recorder.await_args_list for entry in call.kwargs["entries"]} == {
        "literal", "global", "other"}
    assert all(call.kwargs["project_name"] != "gamma" for call in recorder.await_args_list)
    actual = _open(preview["read_cursor"])
    assert actual["memories"][0]["statement"] == long.statement
    assert actual["memories"][0]["statement"].endswith("FINAL: both owners must approve.")
    assert recorder.await_args_list[-1].kwargs["entries"] == [long]


def test_auto_complete_report_keeps_typed_author_period_and_final_conditions(task_search):
    from harness_mem.core.schemas.source_report import SourceReport

    entries, _, semantic, _ = task_search
    report = SourceReport(speaker="assistant", period="2026-10-01T00:00:00Z", session_id="s",
        source_id="source", source_revision="rev", exchange_indexes=[1], topic_title="Recovery suggestion",
        text="助手建议恢复前验证备份；只有隐私官签字且归档负责人确认后才可解除冻结，建议尚未批准。")
    entry = KnowledgeEntry(id="report", project_name="delta", module_path=["Recovery"],
                           title=report.render_title(), statement=report.render_statement(), source_report=report)
    entries.append(entry)
    semantic.ordered_ids.insert(0, "report")
    result = _discover(detail="auto")
    actual = next(row for row in result["memories"] if row["project_name"] == "delta")
    assert actual["statement"] == report.readable_statement()
    assert "助手记述" in actual["statement"] and report.period in actual["statement"]
    assert "未独立核实" in actual["statement"]
    assert actual["statement"].endswith(report.text)
    assert entry.statement == report.render_statement()
    assert "隐私官签字且归档负责人确认" in actual["statement"]


@pytest.mark.parametrize("internal_candidate_only", [False, True])
def test_explicit_or_automatic_candidate_consumers_still_get_only_previews(task_search, internal_candidate_only):
    result = _discover(detail="auto" if internal_candidate_only else "candidates",
                       _candidate_only=internal_candidate_only)
    assert result["detail"] == "candidates"
    assert all("statement" not in row and "read_cursor" in row for row in result["memories"])
    assert handlers._record_search_quality_signals.await_count == 0
