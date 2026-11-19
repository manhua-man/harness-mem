"""Whole-fact reading through the current store and read handlers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from harness_mem.agent_runtime import active_backend
from harness_mem.commands import token_estimator
from harness_mem import read_knowledge
from harness_mem.commands.wake import build_wake_injection
from harness_mem.core.schemas import (
    AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
)
from harness_mem.mcp import read_query_support, tool_handlers
from harness_mem.mcp.read_projection import reading_tokens
from harness_mem.mcp.response_budget import serialize_mcp_result
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    store = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(store.init())
    binding = active_backend.set(store)
    try:
        yield store
    finally:
        active_backend.reset(binding)
        asyncio.run(store.close())


def add_memories(backend, statements, *, project="demo", title="Reading rule", number_titles=True):
    entries = [
        KnowledgeEntry(
            project_name=project, title=f"{title} {index:03}" if number_titles else title, statement=statement,
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
    return tool_handlers.tool_search_memory(**{
        **{key: payload[key] for key in continuation.get("reuse_arguments", [])},
        **continuation["arguments"],
    })


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


def _read_candidate(candidate, *, query, expected, budget=2000, feedback=True):
    assert "statement" not in candidate
    assert candidate["project_name"] == expected.project_name
    full = tool_handlers.tool_search_memory(
        query=query, scope="all", detail="full", cursor=candidate["read_cursor"],
        budget_tokens=budget, _include_diagnostics=True,
    )
    assert full["detail"] == "full", full
    assert full["memories"] == [{
        "title": expected.title, "statement": expected.statement,
        "project_name": expected.project_name,
    }]
    call = full["record_outcome_call"]
    if feedback:
        assert call["tool"] == "record_context_outcome"
        assert call["arguments"]["source_ids"] == [expected.id]
        assert call["arguments"]["retrieval_id"] == full["retrieval_id"]
        recorded = tool_handlers.tool_record_context_outcome(**call["arguments"], outcome="used")
        assert recorded["success"] is True
        assert recorded["truth_mutated"] is False
    else:
        assert call is None
        assert full["retrieval_receipt"]["state"] == "degraded"
        assert full["retrieval_receipt"]["source_ids"] == []
    return full


def _hook_candidates(text):
    query = json.loads(re.search(r"^query: (.+)$", text, flags=re.MULTILINE).group(1))
    candidates = []
    for heading, block in re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL):
        title, project = heading.rsplit(" (", 1)
        cursor = re.search(r"^read_cursor: (.+)$", block, flags=re.MULTILINE).group(1)
        candidates.append({"title": title, "project_name": project.removesuffix(")"), "read_cursor": cursor})
    return query, candidates


def test_paged_search_reaches_all_facts_and_applies_the_requested_budget(backend):
    expected = _many()
    add_memories(backend, expected)
    first = tool_handlers.tool_search_memory(query="paginationtoken", budget_tokens=600)
    text = serialize_mcp_result(first)
    large = tool_handlers.tool_search_memory(query="paginationtoken", budget_tokens=1800)
    assert 0 < len(first["memories"]) < len(large["memories"]) <= len(expected)
    assert reading_tokens(text) <= 600
    assert reading_tokens(large) <= 1800
    assert first["memories"][0]["statement"].endswith("end-marker-000")
    actual = _read_all(first, budget=600)
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


def test_short_search_can_preview_candidates_then_read_only_the_selected_fact(backend):
    entries = add_memories(backend, [
        "routingtoken: recovery requires checking the queue before retrying.",
        "routingtoken: the settings page has a blue background.",
    ], title="routingtoken")
    page = tool_handlers.tool_search_memory(query="routingtoken", detail="candidates", budget_tokens=1200)
    assert page["status"] == "available" and page["detail"] == "candidates"
    assert len(page["memories"]) == 2
    assert all("statement" not in row for row in page["memories"])
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []
    selected = next(row for row in page["memories"] if row["title"] == entries[0].title)
    _read_candidate(selected, query="routingtoken", expected=entries[0])
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert {signal.target_id for signal in signals} == {entries[0].id}
    # Existing short-search behavior remains available when previews are not requested.
    assert any("statement" in row for row in tool_handlers.tool_search_memory(query="routingtoken")["memories"])


def test_focused_candidate_search_can_open_a_cross_project_rule(backend):
    add_memories(backend, ["迁移笔记前先备份数据库和附件目录。"],
                 project="reader", title="迁移前的资料备份", number_titles=False)
    shared = add_memories(backend, ["迁移完成并验证前保留原始备份，不要覆盖它。"],
                          project="global", title="跨设备保留原备份", number_titles=False)[0]
    task = "迁移 备份"
    page = tool_handlers.tool_search_memory(query=task, scope="all", detail="candidates", budget_tokens=4000)
    assert page["detail"] == "candidates"
    match = next(item for item in page["memories"] if item["title"] == shared.title)
    assert match["project_name"] == "global" and "statement" not in match
    assert asyncio.run(backend.structured_store.query_retrieval_signals("global", signal_type="search_hit")) == []
    _read_candidate(match, query=task, expected=shared)
    restricted = tool_handlers.tool_search_memory(query=task, project_name="reader", scope="project",
                                           detail="candidates", budget_tokens=4000)
    assert all(item["project_name"] == "reader" for item in restricted["memories"])


def test_equal_text_keeps_each_project_identity_and_selected_read(backend):
    statement = "Before moving this dataset, retain and verify a backup."
    project_entry = add_memories(backend, [statement], project="reader",
                                 title="Backup rule", number_titles=False)[0]
    global_entry = add_memories(backend, [statement], project="global",
                                title="Backup rule", number_titles=False)[0]
    other_case_entry = add_memories(backend, [statement], project="Reader",
                                    title="Backup rule", number_titles=False)[0]
    page = tool_handlers.tool_search_memory(query="Backup rule", scope="all",
                                     detail="candidates", budget_tokens=2500)
    by_project = {item["project_name"]: item for item in page["memories"]}
    assert set(by_project) == {"reader", "Reader", "global"}
    for entry in (project_entry, global_entry, other_case_entry):
        _read_candidate(by_project[entry.project_name], query="Backup rule", expected=entry)
    restricted = tool_handlers.tool_search_memory(query="Backup rule", scope="project", project_name="reader",
                                           detail="candidates", budget_tokens=2500)
    assert len(restricted["memories"]) == 1
    assert restricted["memories"][0]["project_name"] == "reader"


def test_missing_task_candidates_offer_focused_search_without_widening_scope(backend):
    add_memories(backend, ["A different fact."], project="other")
    query = "unmatched-topic-2048"
    text = asyncio.run(build_wake_injection(backend, "reader", current_task=query, budget_tokens=500))
    assert "No lexical candidates matched" in text
    assert "each unanswered aspect" in text
    assert reading_tokens(text) <= 500
    wake = tool_handlers.tool_wake(current_task=query, project_name="reader", scope="project", budget_tokens=500)
    assert wake["long_term_memory"] == []
    assert "No lexical candidates matched" in wake["message"]
    assert "each unanswered aspect" in wake["message"]
    assert "respect explicit exclusions and scope" in wake["message"].casefold()
    assert reading_tokens(wake) <= 500
    assert "continuation" not in wake
    search = tool_handlers.tool_search_memory(query=query, scope="all", detail="candidates", budget_tokens=500)
    assert search["status"] == "empty" and search["memories"] == []
    assert "No lexical candidates matched" in search["message"]
    tiny_hook = asyncio.run(build_wake_injection(backend, "reader", current_task=query, budget_tokens=15))
    assert reading_tokens(tiny_hook) <= 15
    tiny_wake = tool_handlers.tool_wake(current_task=query, project_name="reader", scope="project", budget_tokens=80)
    assert tiny_wake["success"] is True and tiny_wake["long_term_memory"] == []
    assert reading_tokens(tiny_wake) <= 80
    assert tool_handlers.tool_wake(current_task=query, budget_tokens="invalid")["success"] is False
    assert tool_handlers.tool_wake(current_task=query, budget_tokens=0)["success"] is False


def test_focused_compound_search_can_review_partial_topic_in_named_project(backend):
    target = add_memories(backend, ["每次交付前核对签名并归档记录。"],
                          project="build-hub", title="交付流程约定", number_titles=False)[0]
    add_memories(backend, ["签名校验页面的按钮为绿色。"],
                 project="other", title="签名校验按钮", number_titles=False)
    query = "build-hub 签名校验"
    page = tool_handlers.tool_search_memory(query=query, scope="all", budget_tokens=3000)
    assert page["detail"] == "candidates"
    candidate = next(row for row in page["memories"] if row["title"] == target.title)
    assert any(row["project_name"] == "other" for row in page["memories"])
    assert candidate["project_name"] == "build-hub" and "statement" not in candidate
    assert asyncio.run(backend.structured_store.query_retrieval_signals("build-hub", signal_type="search_hit")) == []
    _read_candidate(candidate, query=query, expected=target)
    restricted = tool_handlers.tool_search_memory(query=query, scope="project", project_name="other", budget_tokens=3000)
    assert all(row["project_name"] == "other" for row in restricted["memories"])


def test_medium_chinese_question_can_discover_a_matching_step(backend):
    entry = add_memories(backend, ["回滚插件时先停用，再从受控目录恢复上一版并检查功能。"],
                         project="fictional", title="插件版本回退", number_titles=False)[0]
    query = "项目如何安全回滚插件更新？"
    page = tool_handlers.tool_search_memory(query=query, scope="project", project_name="fictional", budget_tokens=3000)
    assert page["detail"] == "candidates"
    candidate = next(row for row in page["memories"] if row["title"] == entry.title)
    opened = tool_handlers.tool_search_memory(query=query, scope="project", project_name="fictional",
                                       detail="full", cursor=candidate["read_cursor"])
    assert opened["memories"] == [{"title": entry.title, "statement": entry.statement}]


def test_natural_search_keeps_explicit_parts_in_order_and_reads_original_query(backend, monkeypatch):
    add_memories(backend, ["回滚插件时先停用，再核对恢复的签名。"],
                 project="fictional", title="插件版本回退", number_titles=False)
    query = "怎么回滚插件更新？回滚完成后用什么证据核验签名？"
    splitter = Mock(wraps=read_knowledge._QUESTION_PART_BREAK)
    monkeypatch.setattr(read_knowledge, "_QUESTION_PART_BREAK", splitter)
    first = tool_handlers.tool_search_memory(query=query, budget_tokens=2500)
    splitter.split.assert_called_once_with(query)
    assert first["query"] == query
    assert first["question_parts"] == ["怎么回滚插件更新？", "回滚完成后用什么证据核验签名？"]
    assert "each part" in first["answer_guidance"]
    assert "question_parts" not in tool_handlers.tool_search_memory(query="插件版本回退")


def test_markdown_only_reads_project_sources_once_for_details(backend):
    add_memories(backend, ["First fact.", "Second fact."])
    add_memories(backend, ["Other fact."], project="other")
    store = backend.structured_store
    queries = []
    store._canonical._conn.set_trace_callback(queries.append)
    try:
        plain = asyncio.run(store.knowledge_store.render_markdown("demo"))
        assert not any("from knowledge_sources" in query.lower() for query in queries)
        queries.clear()
        detailed = asyncio.run(store.knowledge_store.render_markdown("demo", include_details=True))
    finally:
        store._canonical._conn.set_trace_callback(None)
    source_queries = [query.lower() for query in queries if "from knowledge_sources" in query.lower()]
    assert len(source_queries) == 1 and "project_id = 'demo'" in source_queries[0]
    assert "demo-source.txt" not in plain
    assert detailed.count("demo-source.txt") == 2 and "other-source.txt" not in detailed


def test_configured_tight_natural_search_keeps_reading_link_without_optional_tokenizer(backend, monkeypatch):
    monkeypatch.setattr(
        "harness_mem.mcp.read_projection.count_response_tokens", lambda text: (0, "char-heuristic")
    )
    entry = add_memories(
        backend, ["回滚插件时先停用，再从目录恢复上一版，并核对签名与运行结果。" * 20],
        title="插件版本回退", number_titles=False,
    )[0]
    query = (
        "上次项目里的插件更新出了问题，我们当时是怎么回滚插件更新的？"
        "恢复上一版以后又用什么证据核验插件签名，怎么确认已经正常运行？"
    )
    user_config = Path.home() / ".harness-mem/config.toml"
    user_config.parent.mkdir(exist_ok=True)
    user_config.write_text("[cost_budget]\nsearch_tokens=1200\n", encoding="utf-8")
    first = tool_handlers.tool_search_memory(query=query)
    assert first["status"] == "available"
    assert reading_tokens(first) <= 1200
    continuation = first.get("continuation")
    if continuation:
        arguments = {"query": query, **continuation["arguments"]}
    else:
        arguments = {"query": query, "detail": "full", "read_cursor": first["memories"][0]["read_cursor"]}
    assert arguments["query"] == query
    second = tool_handlers.tool_search_memory(**arguments)
    assert any(row["statement"] == entry.statement for row in second["memories"])


def test_multipart_search_delivers_whole_statements_for_distinct_parts(backend, monkeypatch):
    monkeypatch.setattr(
        "harness_mem.mcp.read_projection.count_response_tokens", lambda text: (0, "char-heuristic")
    )
    rows = [
        add_memories(backend, [body], title=title, number_titles=False)[0]
        for title, body in (
            ("插件版本回滚", "插件版本回滚先停用更新器，再恢复上一版。"),
            ("插件签名核验", "插件签名核验需要已发行制品的签名和证书指纹。"),
            ("回滚失败恢复", "回滚失败时保留原目录，恢复锁文件后可安全重试。"),
        )
    ]
    add_memories(backend, _many(), project="unrelated")
    original = "插件版本怎么回滚？用什么凭据核验插件签名？回滚失败时怎么恢复？"
    result = tool_handlers.tool_search_memory(query=original)
    assert result["query"] == original
    assert len(result["question_parts"]) == 3
    assert reading_tokens(result) <= 3600
    texts = [item["statement"] for item in result["memories"]]
    for part, row in enumerate(rows):
        assert texts.index(row.statement) + 1 in result["question_part_matches"][part]
    assert "only suggest relevance" in result["answer_guidance"]


def test_multipart_search_marks_questions_after_context_and_subjectless_followups(backend):
    walk, remit, proof, mode = [
        add_memories(backend, [body], title=title, number_titles=False)[0]
        for title, body in (
            ("Canvas Desk 主动走查", "应用能用但优化方向不明时，主动沿用户任务做产品走查。"),
            ("走查发现的产品评估与迭代", "产品评估保留走查发现的场景和证据，持续迭代安排优先级。"),
            ("Canvas Desk 走查验收层级", "验证了入口与独立试用，实际产品体验尚未验证。"),
            ("Canvas Desk 分析模式", "深度分析模式加载清单。模型、推理档位和权限沿用当前设置。"),
        )
    ]
    cases = [
        ("应用已经能用了，但不知道该怎么打磨。Canvas Desk 当时是怎么走查的，发现怎么交给产品评估和持续迭代？",
         ["Canvas Desk 当时是怎么走查的", "发现怎么交给产品评估和持续迭代？"], [walk, remit]),
        ("那次 Canvas Desk 走查验收到了哪一层，能说明实际产品体验变好吗？",
         ["那次 Canvas Desk 走查验收到了哪一层", "能说明实际产品体验变好吗？"], [proof, proof]),
        ("Canvas Desk 的深度分析模式有什么区别？会自动切模型或改权限吗？",
         ["Canvas Desk 的深度分析模式有什么区别？", "会自动切模型或改权限吗？"], [mode, mode]),
    ]
    for query, parts, expected in cases:
        result = tool_handlers.tool_search_memory(query=query)
        assert result["query"] == query
        assert result["question_parts"] == parts
        assert reading_tokens(result) <= 3600
        statements = [item["statement"] for item in result["memories"]]
        for matches, row in zip(result["question_part_matches"], expected):
            assert statements.index(row.statement) + 1 in matches


def test_multipart_continuation_keeps_ranked_facts_and_original_request(backend, monkeypatch):
    monkeypatch.setattr(
        "harness_mem.mcp.read_projection.count_response_tokens", lambda text: (0, "char-heuristic")
    )
    originals = _many(10)
    add_memories(backend, originals)
    query = "How do I use paginationtoken? How do I preserve supporting context?"
    first = tool_handlers.tool_search_memory(query=query)
    assert 1 < len(first["memories"]) <= 6
    assert first["continuation"]["arguments"]["query"] == query
    actual = _read_all(first, budget=3600)
    assert len(actual) == len(originals)
    assert set(actual) == set(originals)


def test_existing_full_statement_can_be_matched_to_a_short_part_without_a_separate_subject(backend):
    saved = add_memories(backend, ["旧版可进到结案。生产构建、规则测试和浏览器验收均通过。"
                                  "用户看过后拒绝文字勾选，后续提议进入场景观察。"],
                         title="《玻璃档案》原型验收和反馈", number_titles=False)[0]
    query = "用户看过《玻璃档案》之后，原来第一版做到哪一层，怎么验过能走通？"
    result = tool_handlers.tool_search_memory(query=query)
    assert result["query"] == query
    assert result["question_parts"] == ["原来第一版做到哪一层", "怎么验过能走通？"]
    position = next(i for i, row in enumerate(result["memories"], 1) if row.get("statement") == saved.statement)
    assert position in result["question_part_matches"][1]


def test_multipart_hint_prefers_the_question_subject_to_unrelated_literal_hits(backend):
    evidence = add_memories(backend, ["Aurora 的启动脚本只通过静态检查，真机验收仍待执行。"],
                            title="Aurora 启动脚本验收", number_titles=False)[0]
    competing = add_memories(backend, ["地图切换的回归怎么验过：检查换图是否保留进度。"],
                             title="地图切换回归怎么验过", number_titles=False)[0]
    result = tool_handlers.tool_search_memory(query="那次 Aurora 启动回归改到了哪里，怎么验过？")
    statements = [row["statement"] for row in result["memories"]]
    assert statements.index(evidence.statement) + 1 in result["question_part_matches"][1]
    assert statements.index(competing.statement) + 1 not in result["question_part_matches"][1]


def test_explicit_candidate_mode_survives_pagination_and_empty_query(backend):
    entries = add_memories(backend, _many())
    first = tool_handlers.tool_search_memory(query="paginationtoken", detail="candidates", budget_tokens=900)
    assert first["detail"] == "candidates" and first["continuation"]["arguments"]["detail"] == "candidates"
    seen = []
    page = first
    for _ in range(30):
        assert page["detail"] == "candidates" and reading_tokens(page) <= 900
        assert all("statement" not in item for item in page["memories"])
        seen.extend(row["title"] for row in page["memories"])
        if "continuation" not in page:
            break
        page = _continue(page)
    else:
        pytest.fail("candidate continuation did not finish")
    assert set(seen) == {entry.title for entry in entries}
    browse = tool_handlers.tool_search_memory(query="", detail="candidates", budget_tokens=900)
    assert browse["detail"] == "candidates" and browse["memories"]
    assert all("statement" not in item for item in browse["memories"])


@pytest.mark.parametrize("task", [None, " \n\t "])
def test_taskless_wake_offers_global_reading_without_dumping_statements(backend, task):
    add_memories(backend, ["First private-sized fact."])
    add_memories(backend, ["Second project fact."], project="other")
    payload = tool_handlers.tool_wake(project_name="unrelated", current_task=task)
    assert payload["success"] is True
    assert payload["long_term_memory"] == []
    assert payload["available_count"] == 2
    assert "First private-sized fact" not in json.dumps(payload)
    assert reading_tokens(payload) <= 2000
    assert len(_read_all(_continue(payload), budget=2000)) == 2


def test_task_wake_candidates_open_whole_facts_and_search_reaches_all_matches(backend):
    expected = _many()
    entries = add_memories(backend, expected)
    wake = tool_handlers.tool_wake(current_task="paginationtoken", budget_tokens=650)
    assert reading_tokens(wake) <= 650
    assert wake["detail"] == "candidates"
    assert wake["long_term_memory"]
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []
    by_title = {entry.title: entry for entry in entries}
    for candidate in wake["long_term_memory"]:
        _read_candidate(candidate, query="paginationtoken", expected=by_title[candidate["title"]], budget=650)
    actual = _read_all(tool_handlers.tool_search_memory(query="paginationtoken", budget_tokens=650), budget=650)
    assert len(actual) == len(expected)
    assert set(actual) == set(expected)


def test_empty_query_browses_natural_modules_across_all_projects(backend):
    left = add_memories(backend, _many(12))
    right = add_memories(backend, ["A distinct cross-project rule."], project="other")
    page = tool_handlers.tool_search_memory(query="", budget_tokens=650)
    assert page["memories"][0]["module"] == ["Reading", "Recovery"]
    actual = _read_all(page, budget=650)
    assert set(actual) == {entry.statement for entry in [*left, *right]}


def test_long_fact_gets_whole_entry_reading_and_preserves_complete_prose(backend):
    statement = "longfacttoken " + "完整知识段落。" * 200 + "最后的独立条件。"
    add_memories(backend, [statement])
    index = tool_handlers.tool_search_memory(query="longfacttoken", budget_tokens=500)
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
    index = tool_handlers.tool_search_memory(query="hugetitletoken", budget_tokens=400)
    assert index["status"] == "available"
    assert reading_tokens(index) <= 400
    assert index["memories"] == []
    full = _continue(index)
    assert full["memories"][0]["title"] == title + " 000"


def test_candidate_search_keeps_a_reading_link_when_no_title_fits(backend):
    entry, = add_memories(
        backend, ["The hidden-reading fixture contains one complete fact."],
        title="A deliberately long title " * 2000, number_titles=False,
    )
    result = tool_handlers.tool_search_memory(
        query="hidden-reading", detail="candidates", budget_tokens=1600,
    )
    assert result["status"] == "available"
    assert result["detail"] == "index"
    assert result["memories"] == []
    assert reading_tokens(result) <= 1600
    full = _continue(result)
    assert full["memories"] == [{
        "title": entry.title.strip(), "statement": entry.statement, "project_name": entry.project_name,
    }]


def test_public_search_opens_the_selected_nonfirst_candidate_by_read_cursor(backend):
    add_memories(backend, ["selectionfixture first fact.", "selectionfixture second fact."])
    query = "selectionfixture"
    page = tool_handlers.tool_search_memory(query=query, detail="candidates", budget_tokens=4000)
    chosen = page["memories"][1]
    payload = tool_handlers.tool_search_memory(query=query, detail="full", read_cursor=chosen["read_cursor"])
    assert [row["title"] for row in payload["memories"]] == [chosen["title"]]
    assert payload["memories"][0]["statement"] == "selectionfixture second fact."


def test_saved_revision_change_restarts_reading_instead_of_using_an_old_offset(backend):
    add_memories(backend, _many())
    first = tool_handlers.tool_search_memory(query="", budget_tokens=600)
    add_memories(backend, ["The newly saved first fact."], title="AAA new fact")
    restarted = _continue(first)
    assert "Memory changed" in restarted["message"]
    assert restarted["memories"][0]["statement"] == "The newly saved first fact."
    assert reading_tokens(restarted) <= 600


def test_cursor_is_bound_to_query_and_explicit_project_filter(backend):
    add_memories(backend, _many())
    first = tool_handlers.tool_search_memory(query="paginationtoken", budget_tokens=600)
    arguments = first["continuation"]["arguments"]
    other_query = tool_handlers.tool_search_memory(**{**arguments, "query": "other"})
    other_scope = tool_handlers.tool_search_memory(**{**arguments, "scope": "project", "project_name": "demo"})
    assert other_query["status"] == other_scope["status"] == "invalid"


@pytest.mark.parametrize("cursor", ["not-a-position", "W10", "Wy0xLDEsMl0", "W3RydWUsMSwyXQ"])
def test_malformed_positions_are_readable_errors(backend, cursor):
    payload = tool_handlers.tool_search_memory(query="", cursor=cursor)
    assert payload["status"] == "invalid"
    assert payload["memories"] == []


def test_explicit_project_filter_is_kept_across_every_page(backend):
    expected = _many()
    add_memories(backend, expected)
    add_memories(backend, ["paginationtoken other project."], project="other")
    first = tool_handlers.tool_search_memory(
        query="paginationtoken", scope="project", project_name="demo", budget_tokens=600,
    )
    assert set(_read_all(first, budget=600)) == set(expected)


def test_optional_tokenizer_fallback_uses_utf8_size_not_quarter_characters(backend, monkeypatch):
    add_memories(backend, [f"中文知识 第 {index} 条。" + "完整来源与准确知识。" * 12 for index in range(10)])
    monkeypatch.setattr(token_estimator, "_get_encoder", lambda: None)
    payload = tool_handlers.tool_search_memory(query="", budget_tokens=1800)
    assert len(serialize_mcp_result(payload).encode("utf-8")) <= 1800
    assert len(payload["memories"]) < 10


def test_special_token_spelling_is_counted_as_ordinary_memory_text():
    encoder = token_estimator._get_encoder()
    if encoder is None:
        pytest.skip("optional tokenizer is unavailable")
    text = "A literal <|endoftext|> is part of this memory."
    assert token_estimator.count_tokens(text) == len(encoder.encode(text, disallowed_special=()))
    assert token_estimator.tokenizer_kind == "tiktoken"


def test_autopilot_counts_the_whole_envelope_and_records_only_opened_candidates(backend):
    entries = add_memories(backend, _many())
    payload = tool_handlers.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", tool_name="pytest",
        tool_result="paginationtoken failed", is_error=True, budget_tokens=1400,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1400
    injection = payload["context_injection"]
    assert injection["detail"] == "candidates"
    assert injection["source_ids"] == []
    assert injection["record_outcome_call"] is None
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert signals == []
    by_title = {entry.title: entry for entry in entries}
    assert injection["memories"]
    expected_ids = set()
    for candidate in injection["memories"]:
        expected = by_title[candidate["title"]]
        assert expected.statement not in json.dumps(injection)
        _read_candidate(candidate, query=injection["query"], expected=expected, budget=1400)
        expected_ids.add(expected.id)
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert {signal.target_id for signal in signals} == expected_ids
    outcomes = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="context_outcome"))
    assert {signal.target_id for signal in outcomes} == expected_ids
    assert "continuation" not in injection
    # Candidate discovery stays bounded. A deliberate ordinary search still
    # supports complete, budgeted pagination across the matching library.
    ordinary = tool_handlers.tool_search_memory(query="paginationtoken", budget_tokens=1400)
    assert set(_read_all(ordinary, budget=1400)) == {entry.statement for entry in entries}


def test_signal_failure_keeps_the_actual_output_within_autopilot_size(backend, monkeypatch):
    entries = add_memories(backend, _many())
    failed_signal = AsyncMock(return_value=None)
    monkeypatch.setattr(read_query_support, "record_retrieval_signal", failed_signal)
    payload = tool_handlers.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", is_error=True, budget_tokens=1200,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1200
    injection = payload["context_injection"]
    assert injection["source_ids"] == []
    assert injection["record_outcome_call"] is None
    failed_signal.assert_not_awaited()
    by_title = {entry.title: entry for entry in entries}
    assert injection["memories"]
    for candidate in injection["memories"]:
        _read_candidate(
            candidate, query=injection["query"], expected=by_title[candidate["title"]],
            budget=1200, feedback=False,
        )
    assert failed_signal.await_count >= len(injection["memories"])
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []


def test_minimal_install_autopilot_keeps_a_usable_reading_result(backend, monkeypatch):
    entries = add_memories(backend, _many())
    monkeypatch.setattr(token_estimator, "_get_encoder", lambda: None)
    payload = tool_handlers.tool_autopilot_search_tick(
        event_name="tool_result", current_task="paginationtoken", is_error=True, budget_tokens=1400,
    )
    assert payload["success"] is True
    assert reading_tokens(payload) <= 1400
    injection = payload["context_injection"]
    assert injection["status"] == "available"
    assert injection["detail"] in {"candidates", "index"}
    assert injection["source_ids"] == []
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []
    if not injection["memories"]:
        assert injection["record_outcome_call"] is None
        opened = _continue(injection)
        assert len(opened["memories"]) == 1
        assert opened["memories"][0]["statement"] in {entry.statement for entry in entries}
        return
    by_title = {entry.title: entry for entry in entries}
    assert injection["memories"]
    for candidate in injection["memories"]:
        _read_candidate(candidate, query=injection["query"], expected=by_title[candidate["title"]], budget=1400)


def test_hook_candidates_only_record_feedback_after_mcp_full_read(backend):
    entries = add_memories(backend, _many())
    text = asyncio.run(build_wake_injection(backend, "demo", current_task="paginationtoken", budget_tokens=650))
    assert reading_tokens(text) <= 650
    assert all(entry.statement not in text for entry in entries)
    assert "# Memory candidates" in text
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")) == []
    query, candidates = _hook_candidates(text)
    assert query == "paginationtoken"
    assert candidates
    by_title = {entry.title: entry for entry in entries}
    for candidate in candidates:
        _read_candidate(candidate, query=query, expected=by_title[candidate["title"]], budget=650)
    signals = asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit"))
    assert {signal.target_id for signal in signals} == {by_title[row["title"]].id for row in candidates}
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []


@pytest.mark.parametrize("task,title", [("配音", "配音"), (".env", ".env")])
def test_exact_short_task_is_still_a_candidate_until_explicitly_read(backend, task, title):
    entry = add_memories(backend, ["A complete prior rule from a different task."],
                         title=title, number_titles=False)[0]
    text = asyncio.run(build_wake_injection(backend, "demo", current_task=task, budget_tokens=1200))
    assert entry.statement not in text
    query, candidates = _hook_candidates(text)
    assert len(candidates) == 1
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
    _read_candidate(candidates[0], query=query, expected=entry)
    # An explicit focused search keeps its direct whole-fact behavior.
    assert tool_handlers.tool_search_memory(query=task)["memories"][0]["statement"] == entry.statement


@pytest.mark.parametrize("task", [None, "paginationtoken"])
def test_small_hook_page_supplies_a_usable_mcp_reading_call(backend, task):
    entries = add_memories(backend, [f"paginationtoken short fact {index}." for index in range(12)])
    text = asyncio.run(build_wake_injection(backend, "demo", current_task=task, budget_tokens=150))
    assert reading_tokens(text) <= 150
    if task is None:
        assert "Continue reading:" not in text and "paginationtoken" not in text
        assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
        # Explicit browse remains available through the ordinary MCP surface.
        assert len(_read_all(tool_handlers.tool_search_memory(query="", budget_tokens=650), budget=650)) == 12
        return
    assert all(entry.statement not in text for entry in entries)
    assert "Continue reading:" not in text
    assert asyncio.run(backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced")) == []
    # A budget too small for the scoped cursor stays quiet; a larger page must
    # expose actual selected cursors that the ordinary MCP reader can open.
    text = asyncio.run(build_wake_injection(backend, "demo", current_task=task, budget_tokens=800))
    assert reading_tokens(text) <= 800
    query, candidates = _hook_candidates(text)
    assert candidates
    by_title = {entry.title: entry for entry in entries}
    for candidate in candidates:
        _read_candidate(candidate, query=query, expected=by_title[candidate["title"]], budget=800)


@pytest.mark.parametrize("surface", ["search", "wake", "automatic", "hook"])
def test_short_answer_remains_readable_next_to_a_full_term_reference(backend, surface):
    short = add_memories(backend, ["Fourteen days."], title="Lease timeout")[0]
    add_memories(backend, ["See the deployment handbook."], title="Aurora lease timeout")
    task = "Aurora lease timeout"
    if surface == "hook":
        result = asyncio.run(build_wake_injection(backend, "demo", current_task=task))
        assert short.statement not in result
        query, candidates = _hook_candidates(result)
        assert candidates
        expected = {entry.title: entry for entry in asyncio.run(
            backend.structured_store.knowledge_store.list_entries("demo")
        )}
        opened = [_read_candidate(row, query=query, expected=expected[row["title"]]) for row in candidates]
        assert any(short.statement in str(page) for page in opened)
        return
    elif surface == "wake":
        result = tool_handlers.tool_wake(current_task=task)
        assert short.statement not in str(result)
        candidates = result["long_term_memory"]
        assert candidates
        expected = {entry.title: entry for entry in asyncio.run(
            backend.structured_store.knowledge_store.list_entries("demo")
        )}
        opened = [_read_candidate(row, query=task, expected=expected[row["title"]]) for row in candidates]
        assert any(short.statement in str(page) for page in opened)
        return
    elif surface == "automatic":
        result = tool_handlers.tool_autopilot_search_tick(event_name="tool_result", current_task=task, is_error=True)
        injection = result["context_injection"]
        assert short.statement not in str(injection)
        assert injection["source_ids"] == []
        assert injection["memories"]
        expected = {entry.title: entry for entry in asyncio.run(
            backend.structured_store.knowledge_store.list_entries("demo")
        )}
        opened = [_read_candidate(row, query=injection["query"], expected=expected[row["title"]])
                  for row in injection["memories"]]
        assert any(short.statement in str(page) for page in opened)
        return
    else:
        result = tool_handlers.tool_search_memory(query=task)
    assert "Fourteen days." in str(result)


def test_sql_keyword_lookup_through_the_current_knowledge_reader(backend):
    add_memories(backend, ["Use WITH for a CTE and WHERE for filtering."], title="SQL clauses")
    # Keyword variants belong to the ranking unit tests; one proves MCP wiring.
    result = tool_handlers.tool_search_memory(query="WITH")
    assert result["status"] == "answered"
    assert result["memories"][0]["statement"] == "Use WITH for a CTE and WHERE for filtering."
