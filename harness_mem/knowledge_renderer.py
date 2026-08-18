"""Deterministic, read-only projections of current SQLite knowledge."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from harness_mem.core.schemas.knowledge import KnowledgeEntry, KnowledgeSource


def _escape_markdown(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _entry_sort_key(entry: KnowledgeEntry) -> tuple:
    return (
        tuple(part.casefold() for part in entry.module_path),
        entry.title.casefold(),
        entry.statement.casefold(),
        entry.id,
    )


def _source_suffix(
    entry: KnowledgeEntry,
    *,
    sources_by_knowledge_id: Mapping[str, Sequence[KnowledgeSource]],
) -> str:
    details: list[str] = []
    if entry.verified_at is not None:
        details.append(f"verified {entry.verified_at.date().isoformat()}")
    sources = sorted(
        sources_by_knowledge_id.get(entry.id, ()),
        key=lambda item: (item.source_kind.casefold(), item.locator.casefold(), item.id),
    )
    if sources:
        rendered_sources = ", ".join(
            f"{_escape_markdown(source.source_kind)}: "
            f"{_escape_markdown(source.locator)}"
            for source in sources
        )
        details.append(f"source {rendered_sources}")
    return f" ({'; '.join(details)})" if details else ""


def render_knowledge_markdown(
    project_name: str,
    entries: Iterable[KnowledgeEntry],
    *,
    include_details: bool = False,
    sources_by_knowledge_id: Mapping[str, Sequence[KnowledgeSource]] | None = None,
) -> str:
    """Render current knowledge without reading, parsing, or writing any file.

    The normal projection includes only natural modules, titles, and statements.
    ``include_details`` adds the verification date and minimal source locators;
    internal ids, revisions, jobs, decisions, and audit reasons are never shown.
    """

    normalized_project = project_name.strip()
    if not normalized_project:
        raise ValueError("project_name must not be empty")
    current_entries = sorted(list(entries), key=_entry_sort_key)
    foreign_projects = {
        entry.project_name
        for entry in current_entries
        if entry.project_name != normalized_project
    }
    if foreign_projects:
        raise ValueError("all knowledge entries must belong to the rendered project")

    grouped: dict[tuple[str, ...], list[KnowledgeEntry]] = defaultdict(list)
    for entry in current_entries:
        grouped[tuple(entry.module_path)].append(entry)

    lines = [f"# {_escape_markdown(normalized_project)} 会话蒸馏知识库"]
    source_map = sources_by_knowledge_id or {}
    previous_path: tuple[str, ...] = ()
    for module_path in sorted(
        grouped,
        key=lambda path: tuple(part.casefold() for part in path),
    ):
        common = 0
        while (
            common < len(previous_path)
            and common < len(module_path)
            and previous_path[common] == module_path[common]
        ):
            common += 1
        for index in range(common, len(module_path)):
            # Markdown has only six heading levels. Preserve deeper paths by
            # joining the remaining natural labels rather than inventing one.
            if index >= 5:
                if index == 5:
                    tail = " / ".join(module_path[5:])
                    lines.extend(("", f"###### {_escape_markdown(tail)}"))
                break
            lines.extend(
                ("", f"{'#' * (index + 2)} {_escape_markdown(module_path[index])}")
            )
        for entry in grouped[module_path]:
            suffix = (
                _source_suffix(entry, sources_by_knowledge_id=source_map)
                if include_details
                else ""
            )
            lines.append(
                f"- **{_escape_markdown(entry.title)}**："
                f"{_escape_markdown(entry.statement)}{suffix}"
            )
        previous_path = module_path
    return "\n".join(lines) + "\n"


__all__ = ["render_knowledge_markdown"]
