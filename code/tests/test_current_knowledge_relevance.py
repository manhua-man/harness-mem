"""Fictional paired controls for current-knowledge lexical relevance."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.read_knowledge import _rank_current_entries, list_current_knowledge, search_current_knowledge


def _entry(identifier, title, statement, *, module="General", project="aurora"):
    return KnowledgeEntry(
        id=identifier, project_name=project, module_path=[module],
        title=title, statement=statement,
    )


def _backend(entries):
    async def list_entries(project, **kwargs):
        return [entry for entry in entries if entry.project_name == project]

    return SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=SimpleNamespace(
        list_entries=AsyncMock(side_effect=list_entries),
        known_projects=AsyncMock(return_value=sorted({entry.project_name for entry in entries})),
    )))


def _search(entries, query, **kwargs):
    return asyncio.run(search_current_knowledge(_backend(entries), query=query, **kwargs))


@pytest.fixture
def onboarding_examples():
    return [
        _entry("quickstart", "Quickstart entry", "Install /hm once for the current host.",
               module="Onboarding"),
        _entry("mcp", "Aurora MCP connections",
               "Aurora MCP routes the Aurora Agent memory product. Aurora MCP is shared.",
               module="Quickstart"),
        _entry("product", "Aurora product architecture",
               "Aurora Agent memory is a local product with pluggable storage.",
               module="Quickstart"),
    ]


@pytest.mark.parametrize("query, expected", [
    ("Aurora Quickstart", ["quickstart"]),
    ("Aurora MCP", ["mcp"]),
    ("Quickstart", ["quickstart"]),
    ("Aurora的Quickstart怎么安装？", ["quickstart"]),
    ("What is Aurora Quickstart?", ["quickstart"]),
])
def test_fixed_onboarding_pairs(onboarding_examples, query, expected):
    found = _search(onboarding_examples, query)
    assert [entry.id for entry in found] == expected


def test_title_match_beats_repeated_body_term_and_query_repetition():
    relevant = _entry("title", "Checkpoint recovery", "Reuse verified pages.")
    distractor = _entry("body", "General procedure", "checkpoint " * 30)
    assert _search([distractor, relevant], "checkpoint") == [relevant, distractor]
    assert _search([distractor, relevant], "checkpoint " * 20) == [relevant, distractor]


@pytest.mark.parametrize("title, statement", [
    ("Lease duration", "Fourteen days."), ("Duration", "Lease: fourteen days."),
])
def test_short_statement_survives_without_background_word(title, statement):
    short = _entry("short", title, statement)
    complete = _entry("complete", "Aurora retention", "Aurora keeps lease records for fourteen days.")
    noise = _entry("noise", "Aurora architecture", "Aurora is a local memory product.")
    found = _search([noise, complete, short], "Aurora lease fourteen")
    assert short in found
    assert complete in found
    assert noise not in found


def test_duplicate_current_facts_cannot_shift_content_relevance(onboarding_examples):
    duplicates = [
        onboarding_examples[1].model_copy(update={"id": f"copy-{index}", "project_name": "zeta"})
        for index in range(20)
    ]
    assert _search([*duplicates, *onboarding_examples], "Aurora Quickstart") == [onboarding_examples[0]]


def test_unrelated_projects_do_not_promote_a_background_word(onboarding_examples):
    unrelated = [
        _entry(f"other-{index}", f"Other subject {index}", "Unrelated independent guidance.", project="other")
        for index in range(100)
    ]
    assert _search([*unrelated, *onboarding_examples], "Aurora Quickstart") == [onboarding_examples[0]]


def test_full_term_reference_does_not_displace_a_short_direct_answer():
    short = _entry("short", "Lease timeout", "Fourteen days.")
    reference = _entry("reference", "Aurora lease timeout", "See the deployment handbook.")
    assert short in _search([short, reference], "Aurora lease timeout")


# Each case exercises a distinct way to retain an English stopword as a topic.
@pytest.mark.parametrize("query, keyword", [
    pytest.param("WITH", "WITH", id="standalone"),
    pytest.param("sql where", "WHERE", id="keyword-list"),
    pytest.param("What is SQL WHERE?", "WHERE", id="uppercase-in-question"),
    pytest.param("How do I use `with`?", "WITH", id="quoted-in-question"),
])
def test_explicit_sql_identifiers_survive_question_word_removal(query, keyword):
    # Do not let another query word (such as SQL) mask a lost clause identifier.
    entry = _entry("sql", "Query clauses", f"{keyword} defines this clause.")
    assert _search([entry], query) == [entry]


def test_meaningful_category_cannot_supply_content_relevance():
    relevant = _entry("lease", "Lease recovery", "Expired leases can be reclaimed.")
    noise = _entry("category", "Theme colors", "Use blue for links.", module="Lease recovery")
    assert _search([noise, relevant], "lease recovery") == [relevant]


@pytest.mark.parametrize("query", [
    "请问之前如何开启后台整理", "整理后台如何开启",
    "How do I enable 后台整理?", "Aurora 后台整理怎么开启？",
])
def test_chinese_and_mixed_question_pairs(query):
    relevant = _entry("background", "后台整理", "只有明确开启后才整理会话。")
    noise = _entry("music", "Aurora 后台音乐", "Aurora 可播放后台音乐。", module="后台整理")
    assert _search([noise, relevant], query) == [relevant]


@pytest.mark.parametrize("query", [
    "怎么开启飞船引擎？", "后台音乐怎么播放？",
    "请问这个问题怎么处理？", "How do I use it?",
])
def test_question_scaffolding_and_one_shared_cjk_pair_are_not_topics(query):
    entry = _entry("background", "开启后台整理", "后台整理默认关闭，只有明确开启后才会自动整理会话。")
    assert _search([entry], query) == []


@pytest.mark.parametrize("query, statement", [
    ("Honestly, how should I configure alerts for our service?",
     "Our editors use a compact layout for this handbook."),
    ("What's my alert policy?", "My report's cover uses blue links."),
])
def test_english_question_clauses_ignore_grammar_even_after_an_introduction(query, statement):
    relevant = _entry("alerts", "Service alert policy", "Send alert events to the on-call operator.")
    noise = _entry("layout", "Document layout", statement)
    assert _search([noise, relevant], query) == [relevant]


def test_each_explicit_mixed_case_identifier_survives_a_stronger_topic_match():
    errors = _entry("errors", "Frontend error handling",
                    "The frontend catches error handling exceptions from UI jobs.")
    storage = _entry("storage", "Storage choice", "CloudPebble collections reuse one connection.")
    language = _entry("language", "Service language", "TypedWeave uses checked values.")
    noise = _entry("layout", "Site layout", "Use a centered column.")
    query = ("When our RiftUI frontend catches error handling exceptions, how should "
             "the jobs running CloudPebble TypedWeave services report?")
    assert {entry.id for entry in _search([noise, errors, storage, language], query)} == {
        "errors", "storage", "language",
    }


def test_unique_lowercase_topic_survives_a_stronger_compound_question_match():
    deployment = _entry("deployment", "Atlas frontend deployment", "Reuse the frontend deployment plan.")
    failures = _entry("failures", "Failure policy", "Record failures before recovery.")
    background = _entry("theme", "Atlas colors", "Use blue links.")
    query = "Given Atlas frontend deployment, how should we report failures?"
    assert {entry.id for entry in _search([background, deployment, failures], query)} == {
        "deployment", "failures",
    }


@pytest.mark.parametrize("query", [
    "How should I handle alert failures when it's late and I'm away for a day?",
    "How should clients' alert failures appear in operators' reports for a day?",
])
def test_apostrophes_in_contractions_do_not_restore_grammar_as_quoted_topics(query):
    relevant = _entry("alerts", "Alert failures", "Record alert failures before recovery.")
    noise = _entry("decoration", "Decorations", "Choose a layout and colors for a card.")
    assert _search([noise, relevant], query) == [relevant]


@pytest.mark.parametrize("query", [
    "Thinking about telemetry and latency dashboards",
    "Set up telemetry with the on-call operator",
])
def test_nonquestion_grammar_cannot_establish_an_unrelated_topic(query):
    noise = _entry("decoration", "Decorations", "A card with the blue border and icons.")
    assert _search([noise], query) == []


@pytest.mark.parametrize("query", [
    "sql and", "sql with", "How do I use 'and'?", "How do I use ‘and’?",
    "How do I use 'it's and that's'?",
])
def test_explicit_sql_keywords_and_real_quotes_survive_grammar_filtering(query):
    keyword = "WITH" if "with" in query else "AND"
    relevant = _entry("clause", "Query clauses", f"{keyword} defines this clause.")
    assert _search([relevant], query) == [relevant]


# Keep every punctuation family, sampling both query forms without their cross-product.
@pytest.mark.parametrize("term, distractor, question", [
    (".env", "env", False), ("C++", "C", True), ("C#", "C", False),
    ("distill.autonomous.enabled=true", "distill autonomous enabled true", True),
    ("--dry-run", "dry run", False), ("source_ref", "source ref", True),
    ("guide/setup.md", "guide setup md", False), ("0.9.29", "0 9 29", True),
])
def test_technical_tokens_keep_internal_punctuation(term, distractor, question):
    relevant = _entry("technical", "Exact setting", f"Use {term} for this operation.")
    noise = _entry("similar", "Similar words", f"Use {distractor} for another operation.")
    query = f"How do I use 【{term}】？" if question else f"`{term}`"
    assert _search([noise, relevant], query) == [relevant]


def test_mixed_technical_question_and_token_boundaries():
    relevant = _entry("env", "Environment file", "Load settings from .env.")
    longer = _entry("local", "Local override", "Load settings from .env.local.")
    noise = _entry("environment", "Process environment", "Use env to inspect variables.")
    assert _search([noise, longer, relevant], "请问如何加载 `.ENV` 配置？") == [relevant]
    assert _search([noise, longer, relevant], ".env.local") == [longer]
    assert _search([noise, longer, relevant], "env") == [noise]


def test_explicit_single_cjk_character_remains_searchable():
    relevant = _entry("lock", "锁", "临界区使用互斥锁保护。")
    assert _search([relevant, _entry("theme", "Theme", "Use blue.")], "【 锁 】") == [relevant]


@pytest.mark.parametrize("query", ["", "  \n\t"])
def test_blank_query_keeps_existing_title_order_and_dedup(query):
    b = _entry("b", "B title", "Second fact.")
    a = _entry("a", "A title", "First fact.")
    duplicate = a.model_copy(update={"id": "duplicate", "project_name": "zeta"})
    assert _search([b, duplicate, a], query) == [a, b]


@pytest.mark.parametrize("query", ["unmatched-token", "!!!"])
def test_no_match_does_not_fall_back_to_listing(query):
    assert _search([_entry("one", "Ordinary fact", "Use blue links.")], query) == []


@pytest.mark.parametrize("conjunction", ["和", "与", "以及"])
def test_empty_conjoined_query_recovers_each_independently_supported_topic(conjunction):
    export = _entry("export", "导出格式使用 TSV", "导出格式使用 TSV。")
    logs = _entry("logs", "日志保留十二天", "日志保留十二天。")
    noise = _entry("noise", "配色规则", "页面使用蓝色。")
    assert _search([noise, logs, export], f"导出格式{conjunction}日志保留期限") == [export, logs]


def test_conjoined_fallback_requires_every_topic_and_keeps_explicit_scope():
    export = _entry("export", "导出格式使用 TSV", "导出格式使用 TSV。", project="alpha")
    logs = _entry("logs", "日志保留十二天", "日志保留十二天。", project="beta")
    assert _search([export, logs], "导出格式和日志保留期限") == [export, logs]
    assert _search([export, logs], "导出格式和日志保留期限", project_name="alpha") == []
    assert _search([export, logs], "导出格式和火星着陆预算") == []


@pytest.mark.parametrize("query", ["【导出格式和日志保留期限】", "docs/导出格式和日志保留期限.md", "协和医院"])
def test_conjoined_fallback_does_not_reinterpret_literals_or_short_word_fragments(query):
    entries = [_entry("export", "导出格式", "使用 TSV。"),
               _entry("logs", "日志保留期限", "保留十二天。"),
               _entry("clinic", "医院", "门诊时间。")]
    assert _search(entries, query) == _rank_current_entries(entries, query)


def test_empty_knowledge_has_no_search_results():
    assert _search([], "lease") == []


@pytest.fixture
def lease_examples():
    a = _entry("a", "Lease policy", "Keep lease records.", project="alpha")
    z = a.model_copy(update={"id": "z", "project_name": "zeta", "module_path": ["Other"]})
    b = _entry("b", "Lease policy", "Keep lease records.", project="alpha")
    other = _entry("other", "Lease timeout", "Release expired leases.", project="zeta")
    return [a, z, b, other]


# Move the winning duplicate before/after its peers; limits and scope do not
# depend on every permutation of the same entries.
@pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 2, 1, 0), (1, 0, 3, 2)])
def test_determinism_and_cross_project_dedup(lease_examples, order):
    a, _z, _b, other = lease_examples
    assert _search([lease_examples[index] for index in order], "lease") == [a, other]


@pytest.mark.parametrize("limit, expected_ids", [
    (1, ["a"]), (2, ["a", "other"]), (0, []), (-1, []),
])
def test_search_limits_after_dedup(lease_examples, limit, expected_ids):
    found = _search(lease_examples, "lease", limit=limit)
    assert [entry.id for entry in found] == expected_ids


def test_explicit_project_keeps_its_own_duplicate(lease_examples):
    _a, z, _b, other = lease_examples
    assert _search(lease_examples, "lease", project_name="zeta") == [z, other]


def test_listing_deduplicates_across_projects(lease_examples):
    a, _z, _b, other = lease_examples
    assert asyncio.run(list_current_knowledge(_backend(lease_examples))) == [a, other]
