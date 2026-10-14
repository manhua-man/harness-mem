"""Clean default retrieval over separated current knowledge."""

from __future__ import annotations

import re
from collections import Counter
from math import log1p
from pathlib import Path

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
# Question scaffolding is not a topic. This is lexical matching, not a synonym
# dictionary or a semantic model; the Agent still reformulates empty queries.
_QUESTION_WORDS = re.compile(
    "请问|之前|以前|这个|那个|我们|你们|怎么|如何|什么|是否|一下|"
    "可以|需要|问题|解决|处理|记得|记住|了吗|的吗"
)
_GENERIC_ACTION_PAIRS = frozenset({"自动", "开启", "关闭", "启用", "停用", "使用", "默认"})
_QUERY_WRAPPERS = {"`": "`", '"': '"', "'": "'", "“": "”", "‘": "’", "【": "】"}
# Keep technical identifiers atomic; surrounding prose punctuation is a separator.
_WORD = re.compile(r"(?:--?|[./@])?[a-z0-9_]+(?:[./:\\=@-]+[a-z0-9_]+)*(?:\+\+|#)?")
_ENGLISH_QUESTION_WORDS = frozenset(
    "a an the how what why when where which who is are was were do does did "
    "can could should would will may i we you it this that these those "
    "to of for in on with about please tell me use enable disable".split()
)


def _unwrap_query_term(term: str) -> str:
    # Remove paired presentation wrappers, never technical punctuation such as
    # the leading dot in .env or the colon in a configuration key.
    while len(term) >= 2 and term[0] in _QUERY_WRAPPERS:
        if term[-1] != _QUERY_WRAPPERS[term[0]]:
            break
        term = term[1:-1]
    return term


def _cjk_query_pairs(query: str) -> set[str]:
    pairs: set[str] = set()
    for run in _CJK_RUN.findall(_QUESTION_WORDS.sub(" ", query)):
        pairs.update(
            run[index : index + 2] for index in range(len(run) - 1)
            if run[index : index + 2] not in _GENERIC_ACTION_PAIRS
        )
    return pairs


def _term_counts(text: str) -> Counter[str]:
    counts = Counter(_WORD.findall(text.casefold()))
    for run in _CJK_RUN.findall(text):
        counts.update(run)
        counts.update(run[index : index + 2] for index in range(len(run) - 1))
    return counts


async def search_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None = None,
    query: str,
    limit: int | None = None,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return only current, separated knowledge with deterministic text ranking."""

    entries = await _current_entries(
        backend,
        project_name=project_name,
        project_root=project_root,
    )
    if not query.strip():
        ranked = sorted(entries, key=lambda entry: (entry.title, entry.project_name, entry.id))
    else:
        ranked = _rank_current_entries(entries, query)
    results = _deduplicate_current(ranked, across_projects=project_name is None)
    return results if limit is None else results[: max(0, int(limit))]


def _rank_current_entries(entries: list[KnowledgeEntry], query: str) -> list[KnowledgeEntry]:
    query_pairs = _cjk_query_pairs(query)
    query_words = _WORD.findall(query.casefold())
    words = set(query_words)
    terms = words.copy()
    # Keyword lists such as "SQL WHERE" are already topic words. Remove
    # scaffolding only from a natural-language question, not every identifier.
    if query_words and query_words[0] in _ENGLISH_QUESTION_WORDS:
        terms.difference_update(_ENGLISH_QUESTION_WORDS)
    # A standalone identifier is a literal lookup, even when SQL or another
    # technical language uses the same spelling as English question scaffolding.
    if len(words) == 1:
        terms.update(words)
    for match in re.finditer(_WORD.pattern, query, flags=re.IGNORECASE):
        word = match.group()
        if len(word) > 1 and word.isupper():
            terms.add(word.casefold())
    for opening, closing in _QUERY_WRAPPERS.items():
        for match in re.finditer(re.escape(opening) + "(.*?)" + re.escape(closing), query):
            terms.update(_WORD.findall(match.group(1).casefold()))
    terms.update(query_pairs)
    single = _unwrap_query_term(query.strip()).strip()
    if len(single) == 1 and _CJK_RUN.fullmatch(single):
        terms.add(single)
    ordered_terms = sorted(terms)
    cjk_runs = [run for run in _CJK_RUN.findall(_QUESTION_WORDS.sub(" ", query)) if len(run) >= 2]
    fields = [
        (_term_counts(entry.title), _term_counts(entry.statement)) for entry in entries
    ]
    contents = [title + statement for title, statement in fields]
    # Document frequency uses content, never category labels. Repeated wording
    # cannot make a broad product term more discriminating. Identical facts
    # count once so pending duplicates cannot shift the relevance cutoff.
    documents = {
        (entry.title.casefold(), " ".join(entry.statement.casefold().split())): content
        for entry, content in zip(entries, contents)
    }
    # Unrelated projects must not turn a shared background word into a rare
    # topic. Measure discrimination within this query's matching documents.
    documents = {
        identity: content for identity, content in documents.items()
        if terms.intersection(content)
    }
    weights = {}
    for term in ordered_terms:
        frequency = sum(term in content for content in documents.values())
        weights[term] = log1p((len(documents) - frequency + 0.5) / (frequency + 0.5))

    scored = []
    for entry, (title, _statement), content in zip(entries, fields, contents):
        matches = terms.intersection(content)
        pairs = matches.intersection(query_pairs)
        # Preserve the Chinese partial-match guard. A complete meaningful run
        # (including a two-character keyword) can also establish a topic.
        if not (
            (len(pairs) >= 2 and len(pairs) * 2 >= len(query_pairs))
            or any(run in entry.title or run in entry.statement for run in cjk_runs)
        ):
            matches.difference_update(query_pairs)
        matched = [term for term in ordered_terms if term in matches]
        coverage = sum(weights[term] for term in matched)
        if not coverage:
            continue
        # Title evidence leads; frequency and category only break content ties.
        relevance = sum(weights[term] * (3 if term in title else 1) for term in matched)
        repetitions = sum(min(content[term], 3) for term in matched)
        module = _term_counts(" ".join(entry.module_path))
        category = sum(weights[term] for term in matched if term in module)
        scored.append((entry, coverage, relevance, repetitions, category, len(matched)))

    # Keep direct multi-term topic evidence independently of a stronger match.
    # A full-term reference must not displace a short answer such as "Lease
    # timeout: Fourteen days". The relative check only filters weaker isolated
    # words such as the product name in a more specific Quickstart question.
    cutoff = max((item[1] for item in scored), default=0) / 2
    admitted = [item for item in scored if item[1] >= cutoff or item[5] >= 2]
    admitted.sort(key=lambda item: (
        -item[2], -item[1], -item[3], -item[4],
        item[0].title, item[0].project_name, item[0].id,
    ))
    return [item[0] for item in admitted]


async def list_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None = None,
    limit: int | None = None,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return current knowledge, optionally filtered to an explicit project."""

    entries = await _current_entries(
        backend,
        project_name=project_name,
        project_root=project_root,
    )
    ordered = sorted(
        entries,
        key=lambda entry: (entry.module_path, entry.title, entry.project_name, entry.id),
    )
    results = _deduplicate_current(ordered, across_projects=project_name is None)
    return results if limit is None else results[: max(0, int(limit))]


async def _current_entries(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    project_root: str | Path | None,
) -> list[KnowledgeEntry]:
    """Use the current-knowledge owner without workspace or profile resolution."""

    store = backend.structured_store.knowledge_store
    if project_name is not None:
        return await store.list_entries(project_name, project_root=project_root)
    entries: list[KnowledgeEntry] = []
    for known_project in await store.known_projects():
        # Read failures must reach the caller, never become a partial/empty hit.
        entries.extend(await store.list_entries(known_project))
    return entries


def _deduplicate_current(
    entries: list[KnowledgeEntry], *, across_projects: bool = False,
) -> list[KnowledgeEntry]:
    """Keep one deterministic representative of each identical current fact.

    Assimilation should prevent duplicates, but a normal user-facing read must
    not repeat the same title/statement while a Review or Dream reconciliation
    is pending.  This does not merge near-matches or mutate truth; it only
    collapses byte-equivalent knowledge wording in the default projection.
    """

    deduplicated: list[KnowledgeEntry] = []
    seen: set[tuple[tuple[str, ...], str, str]] = set()
    for entry in entries:
        key = (
            () if across_projects else tuple(part.casefold().strip() for part in entry.module_path),
            entry.title.casefold().strip(),
            " ".join(entry.statement.casefold().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(entry)
    return deduplicated


__all__ = ["list_current_knowledge", "search_current_knowledge"]
