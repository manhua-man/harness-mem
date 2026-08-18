"""Clean, user-facing projections for ordinary memory retrieval."""

from __future__ import annotations

from typing import Any, Iterable


def _text(value: object) -> str:
    """Normalize display prose without exposing an object's representation."""

    return " ".join(str(value or "").split())


def _topic_title(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts = [_text(part) for part in value]
    return " / ".join(part for part in parts if part)


def _title(item: object, *, fallback: str) -> str:
    for field in ("canonical_title", "title"):
        title = _text(getattr(item, field, None))
        if title:
            return title
    return _topic_title(getattr(item, "topic_path", None)) or fallback


def project_memory_entries(
    entries: Iterable[object],
    *,
    include_project: bool = False,
) -> list[dict[str, str]]:
    """Return canonical memory prose without storage or audit metadata."""

    projected: list[dict[str, str]] = []
    for entry in entries:
        statement = _text(
            getattr(entry, "statement", None) or getattr(entry, "content", None)
        )
        if not statement:
            continue
        item = {
            "title": _title(entry, fallback="Project memory"),
            "statement": statement,
        }
        if include_project:
            item["project_name"] = _text(getattr(entry, "project_name", None))
        projected.append(item)
    return projected


def project_relation_facts(
    facts: Iterable[object],
    *,
    include_project: bool = False,
) -> list[dict[str, str]]:
    """Render readable relations as canonical statements, not edge records."""

    projected: list[dict[str, str]] = []
    for fact in facts:
        source = _text(getattr(fact, "source_entity", None))
        relation = _text(getattr(fact, "relation_type", None)).replace("_", " ")
        target = _text(getattr(fact, "target_entity", None))
        statement = " ".join(part for part in (source, relation, target) if part)
        if statement:
            item = {
                "title": _title(fact, fallback="Project relationship"),
                "statement": statement,
            }
            if include_project:
                item["project_name"] = _text(getattr(fact, "project_name", None))
            projected.append(item)
    return projected


def project_wake_snapshot(snapshot: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Keep ordinary wake useful while removing its plan and audit machinery."""

    def entries(field: str, *, title: str) -> list[dict[str, str]]:
        seen: set[str] = set()
        projected: list[dict[str, str]] = []
        for entry in snapshot.get(field) or []:
            if not isinstance(entry, dict):
                continue
            statement = _text(entry.get("summary"))
            if not statement or statement in seen:
                continue
            seen.add(statement)
            projected.append({"title": title, "statement": statement})
        return projected

    return {
        "long_term_memory": entries("essential_truth", title="Project memory"),
        "active_context": entries("active_task", title="Current context"),
    }


__all__ = [
    "project_memory_entries",
    "project_relation_facts",
    "project_wake_snapshot",
]
