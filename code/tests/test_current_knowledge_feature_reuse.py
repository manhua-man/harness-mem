"""Call-local feature reuse against the unchanged scorer with uncached inputs."""

from __future__ import annotations

import asyncio
import sqlite3
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from harness_mem import read_knowledge
from harness_mem.core.schemas import KnowledgeEntry


def _entry(identifier, title, statement, *, project="alpha", module="Rules"):
    return KnowledgeEntry(
        id=identifier, project_name=project, module_path=[module],
        title=title, statement=statement,
    )


def _backend(entries):
    async def list_entries(project, **kwargs):
        return [entry for entry in entries if entry.project_name == project]

    async def known_projects():
        return sorted({entry.project_name for entry in entries})

    return SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=SimpleNamespace(
        list_entries=AsyncMock(side_effect=list_entries),
        known_projects=AsyncMock(side_effect=known_projects),
    )))


@pytest.fixture
def topic_entries():
    return [
        _entry("noise", "配色规则", "页面使用蓝色。"),
        _entry("logs", "日志保留十二天", "日志保留十二天。", project="beta"),
        _entry("export", "导出格式使用 TSV", "导出格式使用 TSV。"),
    ]


def _search(backend, query, **kwargs):
    return asyncio.run(read_knowledge.search_current_knowledge(backend, query=query, **kwargs))


def test_complete_source_context_does_not_change_ordinary_cjk_search():
    old = _entry("old", "原有约定", "星河读书会正文用简体中文，书名保留原文；页码须核实后再写。")
    weak = _entry("weak", "无关场景", "书名是一个标签。")
    unrelated = _entry("other", "配色", "页面使用蓝色。")
    backend = _backend([old, weak, unrelated])
    query = "改一下：书名先用中文译名，首次出现附原名，正文语言和页码规则不变。作者姓名写法还没决定。"
    assert _search(backend, query) == []
    assert _search(backend, query, source_context=False) == []
    assert _search(backend, query, source_context=True) == [old]
    assert _search(backend, query, source_context=True, project_name="other-project") == []


def _uncached_search(monkeypatch, backend, query, **kwargs):
    # Keep the real ranking/fallback implementation; bypass only the new memo
    # callback. This exercises the previous per-ranking tokenization behavior
    # without copying its scoring, filtering or sorting formulas into the test.
    rank = read_knowledge._rank_current_entries

    def uncached(entries, query, **_ignored):
        return rank(entries, query)

    with monkeypatch.context() as control:
        control.setattr(read_knowledge, "_rank_current_entries", uncached)
        return _search(backend, query, **kwargs)


@pytest.mark.parametrize("query, project, expected", [
    pytest.param("导出格式和日志保留期限", None, ["export", "logs"], id="both-topics"),
    pytest.param("导出格式和日志保留期限", "alpha", [], id="explicit-scope"),
    pytest.param("导出格式和火星着陆预算", None, [], id="missing-topic"),
    pytest.param("【导出格式和日志保留期限】", None, [], id="literal-query"),
    pytest.param("日志保留期限", None, ["logs"], id="single-topic"),
])
@pytest.mark.parametrize("limit", [None, 0, 1, 2, -1])
def test_five_query_classes_have_exact_uncached_ranking(
    monkeypatch, topic_entries, query, project, expected, limit,
):
    backend = _backend(topic_entries)
    before = _uncached_search(monkeypatch, backend, query, project_name=project, limit=limit)
    after = _search(backend, query, project_name=project, limit=limit)
    expected_ids = expected if limit is None else expected[:max(0, limit)]
    assert [entry.id for entry in before] == expected_ids
    assert after == before
    assert [entry.model_dump() for entry in after] == [entry.model_dump() for entry in before]


def test_fallback_really_reduces_tokenization_and_does_not_mutate_shared_counters(monkeypatch, topic_entries):
    original = read_knowledge._term_counts
    calls = Counter()
    produced = []

    def counted(text):
        calls[text] += 1
        result = original(text)
        produced.append((result, result.copy()))
        return result

    monkeypatch.setattr(read_knowledge, "_term_counts", counted)
    backend = _backend(topic_entries)
    before = _uncached_search(monkeypatch, backend, "导出格式和日志保留期限")
    before_calls = sum(calls.values())
    calls.clear()
    after = _search(backend, "导出格式和日志保留期限")
    assert after == before
    assert (before_calls, sum(calls.values())) == (20, 7)
    assert all(count == 1 for count in calls.values())
    assert all(result == snapshot for result, snapshot in produced)


def test_repeated_calls_recompute_features_and_observe_replacement_and_deletion(monkeypatch):
    entries = [_entry("logs", "日志保留策略", "日志保留十一天。")]
    backend = _backend(entries)
    original = read_knowledge._term_counts
    calls = Counter()

    def counted(text):
        calls[text] += 1
        return original(text)

    monkeypatch.setattr(read_knowledge, "_term_counts", counted)
    first = _search(backend, "日志保留期限")
    assert first == entries
    assert calls[entries[0].title] == 1
    assert _search(backend, "日志保留期限") == first
    assert calls[entries[0].title] == 2  # Even unchanged text is recomputed in a new call.

    entries[0] = entries[0].model_copy(update={"statement": "日志保留十二天。"})
    current = _search(backend, "日志保留期限")
    assert current == entries
    assert current[0].statement == "日志保留十二天。"
    assert first[0].statement == "日志保留十一天。"
    assert calls[entries[0].title] == 3
    entries.clear()
    assert _search(backend, "日志保留期限") == []
    assert backend.structured_store.knowledge_store.known_projects.await_count == 4


@pytest.mark.parametrize("project", [None, "alpha"])
@pytest.mark.parametrize("failure", [OSError("unreadable fixture"), sqlite3.DatabaseError("broken fixture")])
def test_source_read_errors_still_propagate(monkeypatch, topic_entries, project, failure):
    backend = _backend(topic_entries)
    store = backend.structured_store.knowledge_store
    store.list_entries.side_effect = failure
    tokenize = Mock()  # Reading must fail before any feature computation.
    monkeypatch.setattr(read_knowledge, "_term_counts", tokenize)
    with pytest.raises(type(failure)) as error:
        _search(backend, "导出格式和日志保留期限", project_name=project)
    assert error.value is failure
    tokenize.assert_not_called()


@pytest.mark.parametrize("query", ["", "  \n\t"])
def test_blank_browse_keeps_order_and_dedup_without_tokenization(monkeypatch, query):
    a = _entry("a", "A title", "First fact.")
    duplicate = a.model_copy(update={"id": "z", "project_name": "zeta"})
    b = _entry("b", "B title", "Second fact.")
    tokenize = Mock()
    monkeypatch.setattr(read_knowledge, "_term_counts", tokenize)
    assert _search(_backend([b, duplicate, a]), query) == [a, b]
    tokenize.assert_not_called()


def test_empty_feature_results_are_reused_by_exact_text(monkeypatch):
    original = read_knowledge._term_counts
    calls = Counter()

    def counted(text):
        calls[text] += 1
        return original(text)

    entries = [_entry("export", "!!!", "导出格式使用 TSV。", module="!!!"),
               _entry("logs", "!!!", "日志保留十二天。", module="!!!")]
    monkeypatch.setattr(read_knowledge, "_term_counts", counted)
    assert [entry.id for entry in _search(_backend(entries), "导出格式和日志保留期限")] == ["export", "logs"]
    assert calls["!!!"] == 1
