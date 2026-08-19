"""Clean default retrieval over separated current knowledge."""

from __future__ import annotations

from pathlib import Path

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def search_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    limit: int,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return only current, separated knowledge with deterministic text ranking."""

    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name,
        project_root=project_root,
    )
    terms = [term.lower() for term in query.split() if term.strip()]

    def score(entry: KnowledgeEntry) -> tuple[int, str, str]:
        haystack = " ".join([entry.title, entry.statement, *entry.module_path]).lower()
        return (-sum(haystack.count(term) for term in terms), entry.title, entry.id)

    ranked = sorted(entries, key=score)
    if terms:
        ranked = [entry for entry in ranked if score(entry)[0] < 0]
    return _deduplicate_current(ranked)[:limit]


async def list_current_knowledge(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
    project_root: str | Path | None = None,
) -> list[KnowledgeEntry]:
    """Return the module-organizable current knowledge library for one project."""

    entries = await backend.structured_store.knowledge_store.list_entries(
        project_name,
        project_root=project_root,
    )
    ordered = sorted(entries, key=lambda entry: (entry.module_path, entry.title, entry.id))
    return _deduplicate_current(ordered)[:limit]


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
