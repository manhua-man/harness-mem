"""Clean default retrieval over separated current knowledge."""

from __future__ import annotations

import re
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


async def search_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    limit: int | None = None,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return only current, separated knowledge with deterministic text ranking."""

    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name,
        project_root=project_root,
    )
    terms = [_unwrap_query_term(term.lower()) for term in query.split()]
    terms = [term for term in terms if term and term not in {"【", "】"}]
    query_pairs = _cjk_query_pairs(query)

    def score(entry: KnowledgeEntry) -> tuple[int, int, str, str]:
        haystack = " ".join([entry.title, entry.statement, *entry.module_path]).lower()
        ascii_tokens = re.findall(r"[a-z0-9]+", haystack)
        occurrences = sum(
            (
                ascii_tokens.count(term)
                if term.isascii() and term.isalnum()
                else haystack.count(term)
            )
            for term in terms
        )
        # Keep full keyword matches first. For unsegmented Chinese questions,
        # require at least two distinct pairs and half the meaningful query;
        # one shared character/pair must not turn an unrelated question into a hit.
        matched_pairs = sum(pair in haystack for pair in query_pairs)
        partial = (
            matched_pairs
            if matched_pairs >= 2 and matched_pairs * 2 >= len(query_pairs)
            else 0
        )
        return (-occurrences, -partial, entry.title, entry.id)

    ranked = sorted(entries, key=score)
    if query.strip():
        ranked = [entry for entry in ranked if any(value < 0 for value in score(entry)[:2])]
    results = _deduplicate_current(ranked)
    return results if limit is None else results[: max(0, int(limit))]


async def list_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int | None = None,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return the module-organizable current knowledge library for one project."""

    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name,
        project_root=project_root,
    )
    ordered = sorted(entries, key=lambda entry: (entry.module_path, entry.title, entry.id))
    results = _deduplicate_current(ordered)
    return results if limit is None else results[: max(0, int(limit))]


def _deduplicate_current(entries: list[KnowledgeEntry]) -> list[KnowledgeEntry]:
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
            tuple(part.casefold().strip() for part in entry.module_path),
            entry.title.casefold().strip(),
            " ".join(entry.statement.casefold().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(entry)
    return deduplicated


__all__ = ["list_current_knowledge", "search_current_knowledge"]
