"""Clean, user-facing projections for ordinary memory retrieval."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Callable, Iterable

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.mcp.response_budget import count_response_tokens, serialize_mcp_result


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
    include_modules: bool = False,
) -> list[dict[str, Any]]:
    """Return canonical memory prose without storage or audit metadata."""

    projected: list[dict[str, Any]] = []
    for entry in entries:
        statement = str(
            getattr(entry, "statement", None) or getattr(entry, "content", None)
            or ""
        ).strip()
        if not statement:
            continue
        item: dict[str, Any] = {
            "title": _title(entry, fallback="Project memory"),
            "statement": statement,
        }
        if include_project:
            item["project_name"] = _text(getattr(entry, "project_name", None))
        if include_modules:
            item["module"] = list(getattr(entry, "module_path", ()) or ())
        projected.append(item)
    return projected


def reading_tokens(payload: Any) -> int:
    """Count the final consumer text, conservatively when no tokenizer exists.

    Normal installs need no tokenizer dependency. UTF-8 bytes provide a
    conservative fallback instead of treating Chinese characters as quarter
    tokens. With tiktoken installed the declared encoding is cl100k_base.
    """
    text = payload if isinstance(payload, str) else serialize_mcp_result(payload)
    tokens, kind = count_response_tokens(text)
    return len(text.encode("utf-8")) if kind == "char-heuristic" else tokens


def resolve_read_budget(
    budget_tokens: int | None,
    *,
    surface: str,
    project_name: str | None = None,
) -> int:
    """Use existing user/project settings without making setup a read prerequisite."""
    if budget_tokens is not None:
        return int(budget_tokens)
    from harness_mem.commands.support import find_project_root
    from harness_mem.config.errors import ConfigError
    from harness_mem.config.merge import MergedConfig, load_merged_config

    try:
        root = find_project_root(project_name) if project_name else None
        config = load_merged_config(root)
    except (ConfigError, OSError):
        config = MergedConfig()
    return (
        config.cost_budget_wake_tokens
        if surface == "wake" else config.cost_budget_search_tokens
    )


def select_memory_page(
    entries: list[KnowledgeEntry],
    *,
    query: str,
    project_name: str | None,
    scope: str,
    budget_tokens: int,
    render: Callable[[list[KnowledgeEntry], dict[str, Any], bool], Any],
    cursor: str | None = None,
    detail: str = "auto",
    availability_only: bool = False,
) -> tuple[list[KnowledgeEntry], dict[str, Any], bool]:
    """Choose whole facts against the actual output, with stateless continuation.

    The renderer includes the caller's envelope and feedback fields. Selection
    never slices stored prose. Explicit full reading returns one complete fact;
    ordinary pages stay within the requested size. A changed result set starts
    a fresh page rather than applying an old offset to different knowledge.
    """
    if detail not in {"auto", "full"}:
        raise ValueError("detail must be auto or full")
    if isinstance(budget_tokens, bool) or int(budget_tokens) < 1:
        raise ValueError("budget_tokens must be positive")
    budget_tokens = int(budget_tokens)
    request_key = hashlib.sha256(
        json.dumps([scope, project_name, query], ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    revision = hashlib.sha256(
        json.dumps(
            [
                [entry.id, entry.project_name, entry.title, entry.statement, entry.module_path]
                for entry in entries
            ],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:24]
    offset = 0
    notice: dict[str, Any] = {}
    if cursor:
        try:
            position, previous_request, previous_revision = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if not isinstance(position, int) or isinstance(position, bool) or position < 0:
                raise ValueError
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            raise ValueError("Reading position is invalid; start this search again.") from None
        if previous_request != request_key:
            raise ValueError("Reading position belongs to a different query or scope.")
        if previous_revision == revision:
            if position > len(entries):
                raise ValueError("Reading position is outside the current results.")
            offset = position
        else:
            notice["message"] = "Memory changed; showing the current first page."

    def continuation(position: int, *, full: bool = False) -> dict[str, Any]:
        encoded = base64.urlsafe_b64encode(
            json.dumps([position, request_key, revision], separators=(",", ":")).encode()
        ).decode().rstrip("=")
        arguments: dict[str, Any] = {
            "query": query,
            "scope": scope,
            "cursor": encoded,
            "budget_tokens": budget_tokens,
        }
        if project_name is not None:
            arguments["project_name"] = project_name
        if full:
            arguments["detail"] = "full"
        else:
            # The next call is MCP even when this page is a smaller Markdown
            # Hook. Give that destination enough room for at least its index
            # and full-reading link; the current page's budget stays unchanged.
            for _ in range(4):
                minimum = reading_tokens({
                    "project_name": project_name, "query": query,
                    "status": "available", "memories": [], "total": len(entries),
                    "detail": "index",
                    "message": "Memory changed; showing the current first page.",
                    "continuation": {"tool": "search_memory", "arguments": {**arguments, "detail": "full"}},
                })
                if arguments["budget_tokens"] >= minimum:
                    break
                arguments["budget_tokens"] = minimum
        return {"tool": "search_memory", "arguments": arguments}

    def metadata(end: int) -> dict[str, Any]:
        result = dict(notice)
        if end < len(entries):
            result.update(total=len(entries), continuation=continuation(end))
        return result

    def fits(selected: list[KnowledgeEntry], info: dict[str, Any], index: bool = False) -> bool:
        return reading_tokens(render(selected, info, index)) <= budget_tokens

    if availability_only and entries:
        info = {
            **notice,
            "available_count": len(entries),
            "continuation": continuation(0),
        }
        if fits([], info):
            return [], info, False
    elif detail == "full":
        selected = entries[offset : offset + 1]
        return selected, {**metadata(offset + len(selected)), "detail": "full"}, False
    elif fits(entries[offset:], metadata(len(entries))):
        return entries[offset:], metadata(len(entries)), False
    else:
        selected = []
        for entry in entries[offset:]:
            candidate = [*selected, entry]
            info = metadata(offset + len(candidate))
            if not fits(candidate, info):
                break
            selected = candidate
        if selected:
            return selected, metadata(offset + len(selected)), False
        if offset < len(entries):
            info = {
                **notice,
                "total": len(entries),
                "detail": "index",
                "continuation": continuation(offset, full=True),
            }
            if fits(entries[offset : offset + 1], info, True):
                return entries[offset : offset + 1], info, True
            # Even a title can be very long. The whole-entry link still works
            # without clipping its title or pretending its body was returned.
            if fits([], info, True):
                return [], info, True
    raise ValueError("budget_tokens is too small to return a reading link.")


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


__all__ = [
    "project_memory_entries",
    "project_relation_facts",
]
