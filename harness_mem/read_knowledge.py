"""Clean default retrieval over separated current knowledge."""

from __future__ import annotations

import re
from collections import Counter
from itertools import zip_longest
from math import log1p
from pathlib import Path
from typing import Callable

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
_ENGLISH_GRAMMAR_WORDS = frozenset(
    "a an the to of for in on with about my our your their its and or but not "
    "don t s m d re ve ll".split()
)
_ENGLISH_QUESTION_WORDS = _ENGLISH_GRAMMAR_WORDS | frozenset(
    "how what why when where which who is are was were do does did "
    "can could should would will may i we you it this that these those "
    "please tell me use enable disable".split()
)
_ENGLISH_QUESTION_CLAUSE = re.compile(
    r"\b(?:how|what|why|when|where|which|who)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|should|would|will|may|i|we|you|it)\b",
    re.IGNORECASE,
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
    source_context: bool = False,
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
        counts_by_text: dict[str, Counter[str]] = {}

        def count_terms(text: str) -> Counter[str]:
            # Only pure text features are shared, for this call's lifetime.
            # Rankings read these counters without mutating them; query-specific
            # document frequency, weights and admission still run independently.
            if text not in counts_by_text:
                counts_by_text[text] = _term_counts(text)
            return counts_by_text[text]

        ranked = _rank_current_entries(entries, query, count_terms=count_terms,
                                       source_context=source_context)
        if not ranked:
            ranked = _rank_conjoined_topics(entries, query, count_terms=count_terms)
    results = _deduplicate_current(ranked, across_projects=project_name is None)
    return results if limit is None else results[: max(0, int(limit))]


def _rank_conjoined_topics(
    entries: list[KnowledgeEntry], query: str,
    *, count_terms: Callable[[str], Counter[str]] | None = None,
) -> list[KnowledgeEntry]:
    """Recover two explicit Chinese topics only when both independently match.

    Keep all nonempty original rankings and literal/technical queries unchanged.
    This is a bounded lexical fallback, not semantic query decomposition: there
    is one conjunction, two complete CJK phrases, and no recursive splitting.
    The already selected entries preserve the caller's project/source scope.
    """
    if any(wrapper in query for pair in _QUERY_WRAPPERS.items() for wrapper in pair):
        return []
    if len(re.findall(r"以及|和|与", query)) != 1:
        return []
    parts = [part.strip() for part in re.split(r"以及|和|与", query, maxsplit=1)]
    if len(parts) != 2 or any(len(part) < 2 or not _CJK_RUN.fullmatch(part) for part in parts):
        return []
    groups = [_rank_current_entries(entries, part, count_terms=count_terms) for part in parts]
    if not all(groups):
        return []
    # Interleave topics so a page need not consume one whole topic before
    # reaching the other. Normal deduplication and whole-fact budgets still run.
    return [entry for row in zip_longest(*groups) for entry in row if entry is not None]


def _rank_current_entries(
    entries: list[KnowledgeEntry], query: str,
    *, count_terms: Callable[[str], Counter[str]] | None = None,
    source_context: bool = False,
) -> list[KnowledgeEntry]:
    count_terms = _term_counts if count_terms is None else count_terms
    query_pairs = _cjk_query_pairs(query)
    query_words = _WORD.findall(query.casefold())
    words = set(query_words)
    terms = words.copy()
    # Keyword lists such as "SQL WHERE" are already topic words. Remove
    # scaffolding only from a natural-language question, not every identifier.
    if query_words and (query_words[0] in _ENGLISH_QUESTION_WORDS
                        or _ENGLISH_QUESTION_CLAUSE.search(query)):
        terms.difference_update(_ENGLISH_QUESTION_WORDS)
    elif query_words and query_words[0] != "sql":
        # Prose and commands also contain grammar-only matches. Bare SQL lists
        # keep operator words; explicit quotes/capitalization are restored below.
        terms.difference_update(_ENGLISH_GRAMMAR_WORDS)
    # A standalone identifier is a literal lookup, even when SQL or another
    # technical language uses the same spelling as English question scaffolding.
    if len(words) == 1:
        terms.update(words)
    explicit_identifiers: set[str] = set()
    for match in re.finditer(_WORD.pattern, query, flags=re.IGNORECASE):
        word = match.group()
        if len(word) > 1 and any(character.isupper() for character in word[1:]):
            terms.add(word.casefold())
            explicit_identifiers.add(word.casefold())
    quoted_identifiers: set[str] = set()
    for opening, closing in _QUERY_WRAPPERS.items():
        # Apostrophes inside contractions/possessives are not quotation marks.
        left, right = (r"(?<!\w)", r"(?!\w)") if opening == "'" else ("", "")
        for match in re.finditer(left + re.escape(opening) + "(.*?)" + re.escape(closing) + right, query):
            quoted_identifiers.update(_WORD.findall(match.group(1).casefold()))
    terms.update(quoted_identifiers)
    explicit_identifiers.update(quoted_identifiers)
    terms.update(query_pairs)
    single = _unwrap_query_term(query.strip()).strip()
    if len(single) == 1 and _CJK_RUN.fullmatch(single):
        terms.add(single)
    cjk_runs = [run for run in _CJK_RUN.findall(_QUESTION_WORDS.sub(" ", query)) if len(run) >= 2]
    # Bind an actually attested multiword name before ranking. Otherwise a
    # question about Claude Code can match an unrelated use of either word.
    # Do not combine independent CamelCase identifiers or invent phrases that
    # no current fact contains (for example a product plus a requested topic).
    named_phrases = {
        match.group().casefold()
        for match in re.finditer(r"\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+\b", query)
        if any(match.group().casefold() in f"{entry.title} {entry.statement}".casefold()
               for entry in entries)
    }
    phrase_patterns = {
        phrase: re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")
        for phrase in named_phrases
    }
    for phrase in named_phrases:
        terms.difference_update(phrase.split())
        explicit_identifiers.difference_update(phrase.split())
        terms.add(phrase)
    terms.update(quoted_identifiers)
    explicit_identifiers.update(quoted_identifiers)
    ordered_terms = sorted(terms)

    def field_terms(text: str) -> Counter[str]:
        counted = count_terms(text)
        if not phrase_patterns:
            return counted
        return counted + Counter({
            phrase: len(pattern.findall(text.casefold()))
            for phrase, pattern in phrase_patterns.items()
        })

    fields = [
        (field_terms(entry.title), field_terms(entry.statement))
        for entry in entries
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
    distinctive_terms: set[str] = set()
    for term in ordered_terms:
        frequency = sum(term in content for content in documents.values())
        weights[term] = log1p((len(documents) - frequency + 0.5) / (frequency + 0.5))
        # Chinese queries keep their existing phrase/partial-match admission.
        if frequency == 1 and not query_pairs:
            distinctive_terms.add(term)

    scored = []
    for entry, (title, _statement), content in zip(entries, fields, contents):
        matches = terms.intersection(content)
        pairs = matches.intersection(query_pairs)
        # Preserve the Chinese partial-match guard. A complete meaningful run
        # (including a two-character keyword) can also establish a topic.
        if not (
            (len(pairs) >= 2 and len(pairs) * 2 >= len(query_pairs))
            # A complete multi-topic source need not fit inside one old fact.
            # This opt-in only recalls context, never verifies or selects truth.
            or (source_context and len(pairs) >= 2)
            or any(
                (len(run) > 2 or len(query_pairs) <= 2
                 or run == entry.title.strip())
                and (run in entry.title or run in entry.statement)
                for run in cjk_runs
            )
        ):
            matches.difference_update(query_pairs)
        matched = [term for term in ordered_terms if term in matches]
        coverage = sum(weights[term] for term in matched)
        if not coverage:
            continue
        # Title evidence leads; frequency and category only break content ties.
        relevance = sum(weights[term] * (3 if term in title else 1) for term in matched)
        repetitions = sum(min(content[term], 3) for term in matched)
        module = count_terms(" ".join(entry.module_path))
        category = sum(weights[term] for term in matched if term in module)
        scored.append((entry, coverage, relevance, repetitions, category, len(matched),
                       bool(matches.intersection(explicit_identifiers | distinctive_terms)),
                       frozenset(matches)))

    # Keep direct multi-term topic evidence independently of a stronger match.
    # A full-term reference must not displace a short answer such as "Lease
    # timeout: Fourteen days". The relative check only filters weaker isolated
    # words such as the product name in a more specific Quickstart question.
    cutoff = max((item[1] for item in scored), default=0) / 2
    # Explicit identifiers and terms unique to one fact remain independent topics.
    # A many-word match elsewhere must not suppress its only current fact.
    admitted = [item for item in scored if item[1] >= cutoff or item[5] >= 2 or item[6]]
    # A lone shared product/background term does not answer a more specific
    # question when another fact also matches its requested topic. Preserve
    # independent explicit/unique identifiers and direct complete-title lookup.
    compound_terms = {term for item in scored if item[5] > 1 for term in item[7]}
    admitted = [item for item in admitted if not (
        item[5] == 1 and not item[6]
        and item[0].title.strip().casefold() != single.casefold()
        and bool(item[7].intersection(compound_terms))
    )]
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
    seen: set[tuple[object, ...]] = set()
    for entry in entries:
        key: tuple[object, ...] = (
            () if across_projects else tuple(part.casefold().strip() for part in entry.module_path),
            entry.title.casefold().strip(),
            " ".join(entry.statement.casefold().split()),
        )
        if entry.source_report is not None:
            report = entry.source_report
            key = (*key, report.source_id, report.source_revision, report.speaker,
                   tuple(report.exchange_indexes), report.period, report.session_id)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(entry)
    return deduplicated


__all__ = ["list_current_knowledge", "search_current_knowledge"]
