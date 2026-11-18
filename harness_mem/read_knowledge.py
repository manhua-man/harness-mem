"""Clean default retrieval over separated current knowledge."""

from __future__ import annotations

import re
from hashlib import sha256
from collections import Counter
from itertools import chain, zip_longest
from math import log1p
from pathlib import Path
from typing import Callable

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.core.schemas.source_report import readable_knowledge_statement
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
# Question scaffolding is not a topic. This is lexical matching, not a synonym
# dictionary or a semantic model; the Agent still reformulates empty queries.
_QUESTION_WORDS = re.compile(
    "请问|之前|以前|这个|那个|我们|你们|怎么|如何|什么|是否|一下|"
    "可以|需要|问题|解决|处理|记得|记住|了吗|的吗"
)
_GENERIC_ACTION_PAIRS = frozenset({"自动", "开启", "关闭", "启用", "停用", "使用", "默认"})
_QUESTION_BACKGROUND_PAIRS = _GENERIC_ACTION_PAIRS | frozenset({
    "只有", "想先", "手里", "到底", "接下", "下来", "一回", "回事", "就是",
    "判断", "不能", "可以", "要求", "需要", "希望", "进行",
})
_QUESTION_FRAMING = re.compile(
    r"我想|只想|上次|那次|这次|当时|现在|最后|之后|后来|为什么|接下来|"
    r"能不能|有没有|是不是|能直接|可以直接|光凭|还是|能否|到底|还有|"
    r"一些|几个|那条|这条|这边|[的了吗呢吧]"
)
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
_QUESTION_PART_BREAK = re.compile(
    r"(?<=[?？])\s*|[；;]\s*|[，,]\s*(?=(?:还有|另外|以及|同时|顺便|那|当时|后来|"
    r"怎么|怎样|如何|为什么|哪些|有什么|有没有|能不能|能否|是否|是不是|什么|最后))|"
    r"(?<=[\u3400-\u9fff])(?=(?:以及|另外|再|又)(?:怎么|如何|为什么|有哪些|哪些|是否|能否))|"
    r"\s+(?=(?:and|also|or)\s+(?:how|what|why|when|where|which|did|can|does)\b)",
    re.IGNORECASE,
)


def question_parts(query: str) -> list[str]:
    """Keep explicit requests in their original wording and order."""
    if not is_natural_question(query) or len(query) > 1800:
        return []
    segments = [part.strip() for part in _QUESTION_PART_BREAK.split(query) if part.strip()]
    if not 2 <= len(segments) <= 6:
        return []
    return segments


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


def is_long_query(query: str) -> bool:
    """Identify multi-part Chinese requests needing local-topic discovery."""
    count = len(_cjk_query_pairs(query))
    # Natural questions can be substantially shorter than a multi-sentence
    # task while still containing more than one requested concept. Preserve
    # exact technical-identifier searches on the original short-query path.
    return count >= 12 or (
        count >= 8 and bool(_QUESTION_WORDS.search(query)) and not _WORD.findall(query.casefold())
    )


def is_natural_question(query: str) -> bool:
    return (is_long_query(query) or bool(_ENGLISH_QUESTION_CLAUSE.search(query))
            or (len(_cjk_query_pairs(query)) >= 4 and bool(re.search(r"[？?]", query))))


def _focused_compound(query: str) -> tuple[str, str] | None:
    """Recognize a single named subject plus one short Chinese topic."""
    words = list(dict.fromkeys(
        word for word in _WORD.findall(query.casefold()) if word not in _ENGLISH_GRAMMAR_WORDS
    ))
    runs = _CJK_RUN.findall(query)
    if len(words) != 1 or len(runs) != 1 or not 4 <= len(runs[0]) <= 8:
        return None
    return words[0], runs[0]


def is_focused_compound_query(query: str) -> bool:
    """These searches may contain weaker partial-topic candidates."""
    return _focused_compound(query) is not None


def _term_counts(text: str) -> Counter[str]:
    counts = Counter(_WORD.findall(text.casefold()))
    for run in _CJK_RUN.findall(text):
        counts.update(run)
        counts.update(run[index : index + 2] for index in range(len(run) - 1))
    return counts


def _searchable_fields(entry: KnowledgeEntry) -> tuple[str, str]:
    """Rank report content, not its repeated attribution boilerplate.

    The readable projection still returns the complete stored statement, so
    this changes matching only and never removes the speaker/source boundary.
    """
    if entry.source_report is not None:
        return entry.source_report.topic_title or "", entry.source_report.text
    return entry.title, entry.statement


async def search_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None = None,
    query: str,
    limit: int | None = None,
    project_root: str | Path | None = None,
    source_context: bool = False,
    expand_long_query: bool = False,
    task_context: str | None = None,
    discovery: dict | None = None,
) -> list[KnowledgeEntry]:
    """Return only current, separated knowledge with deterministic text ranking."""

    entries = await _current_entries(
        backend,
        project_name=project_name,
        project_root=project_root,
    )
    count_terms = None
    exact: list[KnowledgeEntry] = []
    if not query.strip():
        ranked = sorted(entries, key=lambda entry: (entry.title, entry.project_name, entry.id))
    else:
        counts_by_text: dict[str, Counter[str]] = {}

        def cached_term_counts(text: str) -> Counter[str]:
            # Only pure text features are shared, for this call's lifetime.
            # Rankings read these counters without mutating them; query-specific
            # document frequency, weights and admission still run independently.
            if text not in counts_by_text:
                counts_by_text[text] = _term_counts(text)
            return counts_by_text[text]

        count_terms = cached_term_counts
        ranked = _rank_current_entries(entries, query, count_terms=count_terms,
                                       source_context=source_context)
        if not ranked:
            ranked = _rank_conjoined_topics(entries, query, count_terms=count_terms)
        if expand_long_query and not source_context:
            expanded = _rank_long_query_candidates(entries, query)
            expanded_ids = {id(entry) for entry in expanded}
            ranked = expanded + [entry for entry in ranked if id(entry) not in expanded_ids]
            focused = _rank_focused_compound_candidates(entries, query, count_terms=count_terms)
            if focused:
                # Give the named-subject channel a chance without hiding
                # matching facts from other projects in the original channel.
                merged: list[KnowledgeEntry] = []
                seen: set[int] = set()
                for candidates in zip_longest(focused, ranked):
                    for entry in candidates:
                        if entry is not None and id(entry) not in seen:
                            seen.add(id(entry))
                            merged.append(entry)
                ranked = merged
        # A caller may explicitly search the complete rendered title or body
        # for readback, including a report's attribution. Preserve that literal
        # lookup without using shared report boilerplate as a relevance signal.
        exact_query = query.strip().casefold()
        exact = [entry for entry in entries if exact_query in {
            entry.title.strip().casefold(), entry.statement.strip().casefold(),
            readable_knowledge_statement(entry.statement, entry.source_report).strip().casefold(),
        }]
        if exact:
            exact_objects = {id(entry) for entry in exact}
            ranked = exact + [entry for entry in ranked if id(entry) not in exact_objects]
    if task_context is not None or (expand_long_query and is_natural_question(query)):
        from harness_mem.embedding.current_semantic import semantic_discovery

        namespace = str(Path(backend.data_dir).resolve())
        semantic = semantic_discovery(
            [(entry.id, "\n".join(_searchable_fields(entry))) for entry in entries],
            query=query, task_context=task_context or "", namespace=namespace,
            **({"minimum_score": 0.65} if task_context is None else {}),
        )
        if discovery is not None:
            discovery.update(
                status=semantic.status, reason=semantic.reason,
                binding=sha256(("current-context-semantic-v2\n" + namespace + "\n" + semantic.binding).encode()).hexdigest(),
            )
        if semantic.status == "available":
            by_id = {entry.id: entry for entry in entries}
            semantic_entries = [by_id[identity] for identity in semantic.ordered_ids if identity in by_id]
            if task_context is None:
                # A match in both channels should outrank a stray literal span
                # from another project. Keep both independent discovery routes.
                scores: dict[str, float] = {}
                for lane in (ranked, semantic_entries):
                    for rank, entry in enumerate(lane, 1):
                        scores[entry.id] = scores.get(entry.id, 0.0) + 1 / (12 + rank)
                combined = [by_id[identity] for identity in sorted(scores, key=scores.__getitem__, reverse=True)]
            else:
                semantic_ids = {entry.id for entry in semantic_entries}
                combined = semantic_entries + [entry for entry in ranked if entry.id not in semantic_ids]
            # Preserve literal readback priority even when semantic discovery participates.
            exact_query = query.strip().casefold()
            exact = [entry for entry in combined if exact_query and exact_query in {
                entry.title.strip().casefold(), entry.statement.strip().casefold(),
                readable_knowledge_statement(entry.statement, entry.source_report).strip().casefold(),
            }]
            exact_ids = {entry.id for entry in exact}
            ranked = exact + [entry for entry in combined if entry.id not in exact_ids]
    parts = question_parts(query) if expand_long_query and not source_context else []
    if parts:
        prioritized = _prioritize_question_parts(
            entries, ranked, parts, count_terms=count_terms or _term_counts, discovery=discovery,
        )
        exact_objects = {id(entry) for entry in exact}
        ranked = exact + [entry for entry in prioritized if id(entry) not in exact_objects]
    results = _deduplicate_current(ranked, across_projects=project_name is None)
    return results if limit is None else results[: max(0, int(limit))]


def _prioritize_question_parts(
    entries: list[KnowledgeEntry], overall: list[KnowledgeEntry], parts: list[str],
    *, count_terms: Callable[[str], Counter[str]], discovery: dict | None,
) -> list[KnowledgeEntry]:
    """Give each explicit part first-page space, using the full question as context."""
    context = {id(entry): rank for rank, entry in enumerate(overall)}
    lanes: list[list[KnowledgeEntry]] = []
    for part in parts:
        matches = _rank_current_entries(entries, part, count_terms=count_terms)
        if not matches:
            matches = _rank_long_query_candidates(entries, part)
        # A follow-up can omit its subject. The complete query contributes a
        # preference while a separate explicit topic can still win on its own.
        scores = {
            id(entry): 1 / (3 + rank) + 0.65 / (3 + context.get(id(entry), len(entries)))
            for rank, entry in enumerate(matches)
        }
        lanes.append(sorted(matches, key=lambda entry: -scores[id(entry)])[:3])
    if discovery is not None:
        discovery["part_matches"] = [{(entry.project_name, entry.id) for entry in lane} for lane in lanes]
    leading = (entry for row in zip_longest(*lanes) for entry in row if entry is not None)
    by_id: dict[tuple[str, str], KnowledgeEntry] = {}
    for entry in chain(overall[:1], leading, overall):
        by_id.setdefault((entry.project_name, entry.id), entry)
    return list(by_id.values())


def _rank_long_query_candidates(
    entries: list[KnowledgeEntry], query: str,
) -> list[KnowledgeEntry]:
    """Find local textual overlaps in long tasks, without judging relevance.

    A long request can discuss several topics, so a single old fact cannot be
    required to match half of the whole request. This broadens candidate
    discovery only for read callers that request it; write/assimilation context
    and short literal searches keep their existing ranking. Spans and scores
    are lexical hints, not evidence that a memory applies to a task.
    """
    if not is_long_query(query):
        return []
    topic = _QUESTION_WORDS.sub(" ", _QUESTION_FRAMING.sub(" ", query)).casefold()
    grams = {run[start:start + size] for run in _CJK_RUN.findall(topic)
             for start in range(len(run) - 1) for size in range(2, min(6, len(run) - start) + 1)}
    grams.difference_update(_QUESTION_BACKGROUND_PAIRS)
    words = set(_WORD.findall(topic)) - _ENGLISH_QUESTION_WORDS
    matches: list[tuple[set[str], set[str]]] = []
    frequencies: Counter[str] = Counter()

    def match(field: str) -> set[str]:
        field = field.casefold()
        return {gram for gram in grams if gram in field} | (words & set(_WORD.findall(field)))

    for entry in entries:
        title, statement = _searchable_fields(entry)
        title_matches, body_matches = match(title), match(statement)
        frequencies.update(title_matches | body_matches)
        matches.append((title_matches, body_matches))

    weights = {term: log1p(len(entries) / (frequency + 1)) * (1 + min(3, max(0, len(term) - 2)) * 0.45)
               for term, frequency in frequencies.items()}

    def strongest(terms: set[str], limit: int) -> float:
        # Give a matched phrase one contribution, even if it contains several
        # matching n-grams. Cap contributions from long historical reports.
        retained = [weights[term] for term in terms
                    if not any(term != other and term in other for other in terms)]
        return sum(sorted(retained, reverse=True)[:limit])

    scored = []
    for entry, (title_matches, body_matches) in zip(entries, matches):
        shared = title_matches | body_matches
        if len(shared) < 2 and not any(len(term) >= 3 for term in shared):
            continue
        score = 1.4 * strongest(title_matches, 5) + strongest(body_matches, 7)
        scored.append((entry, score))
    scored.sort(key=lambda item: (-item[1], item[0].title, item[0].project_name, item[0].id))
    return [entry for entry, _ in scored]


def _rank_focused_compound_candidates(
    entries: list[KnowledgeEntry], query: str,
    *, count_terms: Callable[[str], Counter[str]],
) -> list[KnowledgeEntry]:
    """Find named-subject candidates matching parts of one compound topic.

    This is a weaker discovery channel, not a project filter or relevance
    judgment. Require the subject as an exact token in the topic title, or as
    the exact project label, and leave all original candidates available.
    """
    focused = _focused_compound(query)
    if focused is None:
        return []
    subject, topic = focused
    project_entries = [entry for entry in entries if entry.project_name.casefold() == subject]
    streams: list[list[KnowledgeEntry]] = []
    for index in range(len(topic) - 1):
        pair = topic[index:index + 2]
        if pair in _GENERIC_ACTION_PAIRS:
            continue
        text_ranked = _rank_current_entries(entries, f"{subject} {pair}", count_terms=count_terms)
        text_ranked = [entry for entry in text_ranked if subject in _WORD.findall(
            _searchable_fields(entry)[0].casefold()
        ) and pair in " ".join(_searchable_fields(entry))]
        if text_ranked:
            streams.append(text_ranked)
        if project_entries:
            scoped = _rank_current_entries(project_entries, pair, count_terms=count_terms)
            if scoped:
                streams.append(scoped)
    ranked: list[KnowledgeEntry] = []
    seen: set[int] = set()
    for row in zip_longest(*streams):
        for entry in row:
            if entry is not None and id(entry) not in seen:
                seen.add(id(entry))
                ranked.append(entry)
    return ranked


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
    searchable_fields = [_searchable_fields(entry) for entry in entries]
    named_phrases = {
        match.group().casefold()
        for match in re.finditer(r"\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+\b", query)
        if any(match.group().casefold() in f"{title} {statement}".casefold()
               for title, statement in searchable_fields)
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

    fields = [(field_terms(title), field_terms(statement))
              for title, statement in searchable_fields]
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
    for entry, (raw_title, raw_statement), (title, _statement), content in zip(
        entries, searchable_fields, fields, contents,
    ):
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
                and (run in raw_title or run in raw_statement)
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
    """Keep one deterministic representative of identical facts within a project.

    Assimilation should prevent duplicates, but a normal user-facing read must
    not repeat the same title/statement while a Review or Dream reconciliation
    is pending.  This does not merge near-matches or mutate truth; it only
    collapses byte-equivalent knowledge wording in the default projection.
    Project identity must remain visible: equal wording does not establish that
    a project-specific entry and a global or other-project entry have the same
    provenance or applicability.
    """

    deduplicated: list[KnowledgeEntry] = []
    seen: set[tuple[object, ...]] = set()
    for entry in entries:
        key: tuple[object, ...] = (
            (entry.project_name,) if across_projects
            else tuple(part.casefold().strip() for part in entry.module_path),
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
