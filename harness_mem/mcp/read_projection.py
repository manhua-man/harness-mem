"""Clean, user-facing projections for ordinary memory retrieval."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Callable, Iterable

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.core.schemas.source_report import readable_knowledge_statement
from harness_mem.mcp.response_budget import count_response_tokens, serialize_mcp_result


FOCUSED_SEARCH_GUIDANCE = (
    "For each unanswered aspect, search the subject and a focused topic, keeping necessary conditions. "
    "When relevant, also search for applicable global or other-project history. "
    "Respect explicit exclusions and scope."
)


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
        statement = readable_knowledge_statement(statement, getattr(entry, "source_report", None))
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
    multipart: bool = False,
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
    if (surface == "search" and multipart and not config.search_budget_configured
            and config.cost_budget_search_tokens == MergedConfig.cost_budget_search_tokens):
        return 3600
    return (
        config.cost_budget_wake_tokens
        if surface == "wake" else config.cost_budget_search_tokens
    )


def _reading_request_key(*, query: str, project_name: str | None, scope: str,
                         task_context: str | None = None, retrieval_binding: str | None = None) -> str:
    request: list[Any] = [scope, project_name, query]
    if task_context is not None or retrieval_binding is not None:
        request.extend([
            hashlib.sha256(task_context.encode("utf-8")).hexdigest() if task_context is not None else None,
            retrieval_binding,
        ])
    return hashlib.sha256(
        json.dumps(request, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]


def _reading_revision(entries: list[KnowledgeEntry]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                [entry.id, entry.project_name, entry.title, entry.statement, entry.module_path]
                for entry in entries
            ],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:24]


def _selected_memory_revision(entry: KnowledgeEntry) -> str:
    # Include typed report provenance and timestamps, not just its rendered
    # body: a source change may leave the displayed statement unchanged.
    return hashlib.sha256(
        json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def make_selected_memory_cursor(
    entries: list[KnowledgeEntry],
    *,
    query: str,
    project_name: str | None,
    scope: str,
    position: int,
    task_context: str | None = None,
    retrieval_binding: str | None = None,
) -> str:
    """Bind one full-entry read to this request, ordered result set and identity.

    Like ordinary reading cursors, this is a position reference, not an
    authorization token. The caller must still obtain the allowed result set.
    """
    if type(position) is not int or not 0 <= position < len(entries):
        raise ValueError("Selected memory position is outside the current results.")
    return _selected_cursor(
        entries[position], position,
        _reading_request_key(query=query, project_name=project_name, scope=scope,
                             task_context=task_context, retrieval_binding=retrieval_binding),
        _reading_revision(entries),
    )


def _selected_cursor(entry: KnowledgeEntry, position: int, request_key: str, revision: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(
            [
                position,
                request_key,
                revision,
                entry.id,
                entry.project_name,
                _selected_memory_revision(entry),
            ],
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode().rstrip("=")


def memory_candidate_projector(
    entries: list[KnowledgeEntry],
    *,
    query: str,
    project_name: str | None,
    scope: str,
    task_context: str | None = None,
    retrieval_binding: str | None = None,
    whole_if_cheaper: bool = False,
) -> Callable[[list[KnowledgeEntry], bool], list[dict[str, Any]]]:
    """Prepare bounded previews with exact, version-checked full-read cursors."""
    positions = {id(entry): position for position, entry in enumerate(entries)}
    cursors: dict[int, str] = {}
    normal_cards: dict[int, dict[str, Any]] = {}
    request_key = _reading_request_key(query=query, project_name=project_name, scope=scope,
                                     task_context=task_context, retrieval_binding=retrieval_binding)
    revision = _reading_revision(entries)

    def project(page: list[KnowledgeEntry], titles_only: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for entry in page:
            position = positions[id(entry)]
            if not titles_only and position in normal_cards:
                result.append(dict(normal_cards[position]))
                continue
            if position not in cursors:
                cursors[position] = _selected_cursor(entry, position, request_key, revision)
            item: dict[str, Any] = {
                "title": entry.title,
                "project_name": entry.project_name,
                "read_cursor": cursors[position],
            }
            report = entry.source_report
            body = report.text if report is not None else entry.statement
            if report is not None:
                item["source_speaker"] = report.speaker
                item["source_period"] = report.period
            if not titles_only and len(body) > 1:
                # Always show an explicitly incomplete preview. A selected item
                # must be read in full before it is used or counted as read.
                length = min(120, len(body) // 2)
                item["preview"] = body[:length].rstrip() + "…"
            if not titles_only:
                if whole_if_cheaper:
                    # Use the ordinary complete projection: typed report
                    # attribution is preserved by its readable projection.
                    complete = project_memory_entries([entry], include_project=True)[0]
                    if reading_tokens(complete) < reading_tokens(item):
                        item = complete
                normal_cards[position] = dict(item)
            result.append(item)
        return result

    return project


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
    task_context: str | None = None,
    retrieval_binding: str | None = None,
    incremental: bool = False,
    page_limit: int | None = None,
) -> tuple[list[KnowledgeEntry], dict[str, Any], bool]:
    """Choose whole facts against the actual output, with stateless continuation.

    The renderer includes the caller's envelope and feedback fields. Selection
    never slices stored prose. Explicit full reading returns one complete fact;
    ordinary pages stay within the requested size. A changed result set starts
    a fresh page for ordinary pagination; an exact selected read instead fails
    so it can never silently open a different entry.
    """
    if detail not in {"auto", "full"}:
        raise ValueError("detail must be auto or full")
    if isinstance(budget_tokens, bool) or int(budget_tokens) < 1:
        raise ValueError("budget_tokens must be positive")
    budget_tokens = int(budget_tokens)
    request_key = _reading_request_key(query=query, project_name=project_name, scope=scope,
                                     task_context=task_context, retrieval_binding=retrieval_binding)
    revision = _reading_revision(entries)
    offset = 0
    selected_identity: tuple[str, str, str] | None = None
    notice: dict[str, Any] = {}
    if cursor:
        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if not isinstance(decoded, list) or len(decoded) not in {3, 6}:
                raise ValueError
            position, previous_request, previous_revision = decoded[:3]
            if not isinstance(position, int) or isinstance(position, bool) or position < 0:
                raise ValueError
            if len(decoded) == 6:
                selected_id, selected_project, selected_revision = decoded[3:]
                if not all(isinstance(value, str) and value for value in (
                    selected_id, selected_project, selected_revision,
                )):
                    raise ValueError
                selected_identity = selected_id, selected_project, selected_revision
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            raise ValueError("Reading position is invalid; start this search again.") from None
        if previous_request != request_key:
            raise ValueError("Reading position belongs to a different query or scope, task context, or retrieval backend.")
        if selected_identity is not None:
            if detail != "full":
                raise ValueError("Selected memory reading requires detail=full.")
            if previous_revision != revision:
                raise ValueError("Selected memory results changed; search again before opening it.")
            if position >= len(entries):
                raise ValueError("Selected memory position is outside the current results.")
            entry = entries[position]
            if (entry.id, entry.project_name) != selected_identity[:2]:
                raise ValueError("Selected memory identity changed; search again before opening it.")
            if _selected_memory_revision(entry) != selected_identity[2]:
                raise ValueError("Selected memory changed; search again before opening it.")
            offset = position
        elif previous_revision == revision:
            if position > len(entries):
                raise ValueError("Reading position is outside the current results.")
            offset = position
        else:
            notice["message"] = "Memory changed; showing the current first page."

    def continuation(position: int, *, full: bool = False) -> dict[str, Any]:
        if full:
            encoded = _selected_cursor(entries[position], position, request_key, revision)
        else:
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
        return {"tool": "search_memory", "arguments": arguments,
                **({"reuse_arguments": ["task_context"]} if task_context is not None else {})}

    def metadata(end: int) -> dict[str, Any]:
        result = dict(notice)
        if end < len(entries):
            result.update(total=len(entries), continuation=continuation(end))
        return result

    def fits(selected: list[KnowledgeEntry], info: dict[str, Any], index: bool = False) -> bool:
        return reading_tokens(render(selected, info, index)) <= budget_tokens

    window_end = len(entries) if page_limit is None else min(len(entries), offset + page_limit)
    if availability_only and entries and selected_identity is None:
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
    elif (not incremental or offset == window_end) and fits(entries[offset:window_end], metadata(window_end)):
        return entries[offset:window_end], metadata(window_end), False
    else:
        selected = []
        for entry in entries[offset:window_end]:
            candidate = [*selected, entry]
            info = metadata(offset + len(candidate))
            if not fits(candidate, info):
                if incremental and window_end == len(entries):
                    # Ordinary JSON pages grow with each whole entry. A
                    # continuation can cost more than the final few facts:
                    # look ahead without it until either all rows fit or
                    # even that prefix is too large. Do not project the
                    # entire library just to reject a large first page.
                    probe = candidate
                    final_info = metadata(len(entries))
                    while fits(probe, final_info):
                        if offset + len(probe) == len(entries):
                            return probe, final_info, False
                        probe = [*probe, entries[offset + len(probe)]]
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
    "make_selected_memory_cursor",
    "memory_candidate_projector",
    "project_memory_entries",
    "project_relation_facts",
]
