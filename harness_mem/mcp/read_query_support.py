"""Query interpretation, quality signals, and read-side DX metadata."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Literal, cast

from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

from .handler_facade_proxy import tool_handlers_facade as _core


def _get_backend():
    return _core._get_backend()


def _observer_data_dir():
    return _core._observer_data_dir()


def _cost_surface_budgets(project_name):
    return _core._cost_surface_budgets(project_name)


def _record_state_event(*args, **kwargs):
    return _core._record_state_event(*args, **kwargs)


def _run_command_to_payload(coro):
    return _core._run_command_to_payload(coro)


async def _gather_project_status(*args, **kwargs):
    return await _core._gather_project_status(*args, **kwargs)


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})
VALID_CONTEXT_OUTCOMES: frozenset[str] = frozenset({"used", "ignored", "misleading"})
CONTEXT_OUTCOME_VALUES: dict[str, float] = {
    "used": 1.0,
    "ignored": 0.0,
    "misleading": -1.0,
}
VALID_RETRIEVAL_PROFILES: frozenset[str] = frozenset({"light", "quality"})
RetrievalProfile = Literal["light", "quality"]


def _quality_signal_target(*parts: str | None) -> str:
    payload = "\x1f".join(part or "" for part in parts).encode("utf-8")
    return f"query:{hashlib.sha256(payload).hexdigest()[:16]}"


async def _record_search_quality_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    entries: list[Any],
    response: Any,
    context_plan: Any,
    historical_excluded: int = 0,
) -> None:
    """Write bounded, content-free shadow metrics for one search call."""

    for entry in entries:
        entry_id = str(getattr(entry, "id", "") or "")
        if not entry_id:
            continue
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=entry_id,
            context={"surface": "search_memory"},
        )

    if historical_excluded > 0:
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_excluded",
            target_kind="context_source",
            target_id=_quality_signal_target(project_name, query, "historical"),
            value=float(historical_excluded),
            context={"surface": "search_memory", "reason": "historical"},
        )

    reason: str | None = None
    if not list(getattr(response, "results", []) or []):
        reason = "no_evidence"
    elif context_plan is not None and not bool(
        getattr(context_plan.context_sufficiency, "safe_to_answer", False)
    ):
        reason = "insufficient_context"
    if reason is None:
        return
    await record_retrieval_signal(
        backend,
        project_name=project_name,
        signal_type="retrieval_abstained",
        target_kind="context_source",
        target_id=_quality_signal_target(project_name, query),
        value=1.0,
        context={
            "surface": "search_memory",
            "reason": reason,
            "result_count": len(list(getattr(response, "results", []) or [])),
        },
    )


async def _count_mainline_historical_exclusions(
    backend: LocalMemoryBackend,
    *,
    query: str,
    project_name: str,
    mode: str,
    memory_type: list[str] | None,
    include_provisional: bool,
    time_window: tuple[datetime | None, datetime | None] | None,
) -> int:
    """Count bounded history matches hidden by the current-only search default."""

    entries = await backend.structured_store.search_memory_entries(
        query,
        project_name=project_name,
        limit=100,
        mode=mode,
        memory_type=memory_type,
        include_history=True,
        deep_recall=True,
        time_window=time_window,
        include_provisional=include_provisional,
    )
    facts = await backend.structured_store.search_relation_facts(
        query,
        project_name=project_name,
        limit=100,
        include_history=True,
        time_window=time_window,
        include_provisional=include_provisional,
    )
    now = datetime.now(timezone.utc)

    def historical(item: Any) -> bool:
        if list(getattr(item, "superseded_by", []) or []):
            return True
        valid_to = getattr(item, "valid_to", None)
        if valid_to is None:
            return False
        if valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        return valid_to <= now

    return sum(historical(item) for item in [*entries, *facts])


async def _record_temporal_quality_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    result: Any,
    mode: str,
    identity_parts: tuple[str | None, ...],
) -> None:
    """Record temporal abstention/exclusion evidence without storing query text."""

    target_id = _quality_signal_target(project_name, *identity_parts)
    reason = str(getattr(result, "abstention_reason", "") or "")
    if bool(getattr(result, "abstain", False)):
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_abstained",
            target_kind="context_source",
            target_id=target_id,
            value=1.0,
            context={"surface": "temporal_query", "reason": reason or "no_evidence"},
        )

    timeline = tuple(getattr(result, "timeline", ()) or ())
    if reason == "temporal_conflict":
        conflict_count = sum(
            bool(getattr(record, "is_current", False)) for record in timeline
        )
        await record_retrieval_signal(
            backend,
            project_name=project_name,
            signal_type="retrieval_excluded",
            target_kind="context_source",
            target_id=target_id,
            value=float(max(1, conflict_count)),
            context={"surface": "temporal_query", "reason": "temporal_conflict"},
        )

    if mode == "current":
        stale_count = sum(
            not bool(getattr(record, "is_current", False)) for record in timeline
        )
        if stale_count:
            await record_retrieval_signal(
                backend,
                project_name=project_name,
                signal_type="retrieval_excluded",
                target_kind="context_source",
                target_id=target_id,
                value=float(stale_count),
                context={"surface": "temporal_query", "reason": "historical"},
            )


def _action(label: str, surface: str, reason: str) -> dict[str, str]:
    return {"label": label, "surface": surface, "reason": reason}


def _autopilot_dx_metadata(
    *,
    should_search: bool,
    trigger: str | None,
    search_executed: bool,
    missing_project: bool = False,
) -> dict[str, Any]:
    if missing_project:
        return {
            "why_this_result": (
                "Autopilot detected a search-worthy event but no project was "
                "available. Open the intended workspace or pass project_name."
            ),
            "next_actions": [
                _action(
                    "resolve_project_context",
                    "get_project_status",
                    "Open the intended workspace so project context can be resolved before runtime ticks.",
                )
            ],
            "degraded_reason": "missing_project",
        }
    if search_executed:
        return {
            "why_this_result": (
                f"Autopilot search ran because trigger={trigger}; inject the "
                "returned answer_ready_context or context_plan into the next "
                "agent context."
            ),
            "next_actions": [
                _action(
                    "inject_next_context",
                    "answer_ready_context",
                    "Use bounded, source-attributed context in the next provider request.",
                ),
                _action(
                    "record_outcome",
                    "record_context_outcome",
                    "After the task, mark surfaced source ids used/ignored/misleading.",
                ),
            ],
            "degraded_reason": None,
        }
    return {
        "why_this_result": (
            "Autopilot search skipped this event because no concrete "
            "memory-backed uncertainty was detected."
            if not should_search
            else "Autopilot search was skipped by policy."
        ),
        "next_actions": [],
        "degraded_reason": None,
    }


_AS_OF_TERMS: tuple[str, ...] = (
    "as of",
    "at the time",
    "back then",
    "当时",
    "那时",
)
_HISTORY_TERMS: tuple[str, ...] = (
    "previous",
    "previously",
    "formerly",
    "legacy",
    "old",
    "history",
    "historical",
    "before",
    "以前",
    "之前",
    "历史",
    "过去",
    "旧",
)
_DATE_PATTERN = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?)?\b"
)


def _temporal_intent_mode(query: str | None) -> Literal["as_of", "history"] | None:
    normalized = (query or "").strip().lower()
    if not normalized:
        return None
    if any(term in normalized for term in _AS_OF_TERMS):
        return "as_of"
    if _DATE_PATTERN.search(normalized):
        return "as_of"
    if any(term in normalized for term in _HISTORY_TERMS):
        return "history"
    return None


def _extract_as_of_hint(query: str | None) -> str | None:
    match = _DATE_PATTERN.search(query or "")
    if not match:
        return None
    try:
        return (
            datetime.fromisoformat(match.group(1))
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        return None


def _temporal_query_action(mode: str) -> dict[str, str]:
    return _action(
        "inspect_temporal_truth",
        "temporal_query",
        (
            f"Query looks time-scoped; use temporal_query mode={mode} before "
            "treating old-state answers as current truth."
        ),
    )


def _temporal_intent_drilldown_hint(
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> dict[str, Any] | None:
    if mode is None:
        return None
    as_of = _extract_as_of_hint(query) if mode == "as_of" else None
    arguments: dict[str, Any] = {
        "project_name": project_name,
        "query": query,
        "mode": mode,
        "limit": 20,
    }
    if mode == "as_of":
        arguments["as_of"] = as_of
        arguments["requires_as_of"] = as_of is None
    return {
        "source_id": None,
        "source_kind": "temporal_intent",
        "read_surface": "mcp.temporal_query",
        "tool": "temporal_query",
        "arguments": arguments,
        "why": (
            "The query appears to ask about historical or as-of truth. "
            "Use temporal_query and preserve its abstention_reason if no evidence matches."
        ),
        "abstention": "no_evidence",
    }


def _with_temporal_intent_hint(
    hints: list[dict[str, Any]],
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> list[dict[str, Any]]:
    hint = _temporal_intent_drilldown_hint(
        project_name=project_name,
        query=query,
        mode=mode,
    )
    if hint is None:
        return list(hints)
    return [*hints, hint]


def _is_historical_truth(record: object) -> bool:
    valid_to = getattr(record, "valid_to", None)
    if not isinstance(valid_to, datetime):
        return False
    return valid_to <= datetime.now(timezone.utc)


def _is_superseded_truth(record: object) -> bool:
    return _is_historical_truth(record) and bool(
        list(getattr(record, "superseded_by", []) or [])
    )


def _normalize_retrieval_profile(value: object) -> RetrievalProfile | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_RETRIEVAL_PROFILES:
        return cast(RetrievalProfile, profile)
    return None


async def _resolve_retrieval_profile(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    requested: str | None,
) -> dict[str, Any]:
    if requested is not None:
        normalized = _normalize_retrieval_profile(requested)
        if normalized is None:
            valid = ", ".join(sorted(VALID_RETRIEVAL_PROFILES))
            return {
                "success": False,
                "error": f"retrieval_profile must be one of: {valid}",
            }
        return {
            "success": True,
            "active": normalized,
            "configured": None,
            "source": "argument",
        }

    configured: RetrievalProfile | None = None
    if project_name:
        from harness_mem.commands import support as _support

        profile = await LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(
            project_name
        )
        if profile is not None:
            configured = _normalize_retrieval_profile(profile.retrieval_profile)

    return {
        "success": True,
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
    }


def _retrieval_profile_status(
    *,
    active_profile: str | None,
    memory_entry_count: int,
) -> dict[str, Any]:
    configured = _normalize_retrieval_profile(active_profile)
    suggested = None if configured else ("quality" if memory_entry_count > 0 else None)
    return {
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
        "suggested": suggested,
        "available": [
            {
                "name": "light",
                "default": True,
                "reranker": "noop",
                "query_rewriting_enabled": False,
                "multi_query_enabled": False,
                "hyde_enabled": False,
                "summary": "Default lightweight retrieval path.",
            },
            {
                "name": "quality",
                "default": False,
                "reranker": "noop",
                "query_rewriting_enabled": True,
                "multi_query_enabled": True,
                "hyde_enabled": False,
                "summary": (
                    "Opt-in deterministic query rewrite/fanout trace; no "
                    "heavy reranker, HyDE, ANN, Tantivy, or LanceDB is enabled."
                ),
            },
        ],
        "auto_enabled": False,
        "default_profile": "light",
        "claim_boundary": (
            "retrieval_profile=quality is component-level retrieval behavior; "
            "it does not unlock broad_memory_answer_quality"
        ),
    }


def _search_dx_metadata(
    *,
    memory_entry_count: int,
    relation_fact_count: int,
    observation_count: int,
    effective_mode: str,
    fallback_reason: str | None,
    project_name: str | None,
    query: str,
    include_history: bool,
    deep_recall: bool,
    temporal_intent_mode: Literal["as_of", "history"] | None,
) -> dict[str, Any]:
    total = memory_entry_count + relation_fact_count + observation_count
    next_actions: list[dict[str, str]] = []
    if total == 0:
        next_actions.append(
            _action(
                "distill_recent_sessions",
                "/hm:distill",
                "No confirmed memory matched this query; run /hm:distill before relying on search.",
            )
        )
        next_actions.append(
            _action(
                "search_raw_evidence",
                "search_raw",
                "Use raw evidence search if you need exact transcript snippets before distill.",
            )
        )
    else:
        next_actions.append(
            _action(
                "inspect_sources",
                "drilldown_hints",
                "Use returned source ids and read surfaces when a result needs proof.",
            )
        )
        next_actions.append(
            _action(
                "record_outcome",
                "record_context_outcome",
                "After the task, record used/ignored/misleading so future opt-in ranking is explainable.",
            )
        )
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "harness-mem doctor",
                "Search degraded to a fallback path; inspect local runtime health before claiming quality.",
            )
        )
    if include_history or deep_recall:
        next_actions.append(
            _action(
                "inspect_temporal_chain",
                "temporal_query",
                "History-capable search was requested; use temporal_query for current/history/as_of proof.",
            )
        )
    elif temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))

    project_fragment = f" for {project_name}" if project_name else ""
    why = (
        f"Returned {memory_entry_count} memory entries, {relation_fact_count} "
        f"relation facts, and {observation_count} observations{project_fragment} "
        f"using {effective_mode} mode for query {query!r}."
    )
    if include_history:
        why += " Historical structured truth was included because include_history=true."
    elif deep_recall:
        why += " Historical structured truth may be included because deep_recall=true."
    elif temporal_intent_mode:
        why += " Query appears temporal; current results remain current-only unless history is requested."
    return {
        "why_this_result": why,
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


def _wake_dx_metadata(
    *,
    success: bool,
    fallback_reason: str | None,
    source_coverage: dict[str, int] | None,
    temporal_intent_mode: Literal["as_of", "history"] | None = None,
) -> dict[str, Any]:
    if not success:
        return {
            "why_this_result": "Wake did not complete, so no context packet was generated.",
            "next_actions": [
                _action(
                    "check_status",
                    "get_project_status",
                    "Status explains whether the project is missing ingest, review, or local setup.",
                )
            ],
            "degraded_reason": fallback_reason or "wake_failed",
            "drilldown_hints": [],
        }
    coverage = source_coverage or {}
    next_actions = [
        _action(
            "answer_with_sources",
            "supporting_evidence",
            "Use the returned evidence ids when the task needs proof.",
        ),
        _action(
            "search_specific_gap",
            "/hm:search",
            "If the wake packet is too broad, search for the exact subsystem or decision.",
        ),
    ]
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "harness-mem doctor",
                "Wake used a fallback search path; inspect local health before release claims.",
            )
        )
    if temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))
    return {
        "why_this_result": (
            "Generated wake context from project profile, rules, "
            f"handoffs, and task-aware retrieval; source coverage: {coverage}."
        ),
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


# Status decision metadata lives in response_views.py.
