"""Retrieval feedback handlers kept separate from search result assembly."""

from __future__ import annotations

import asyncio
from uuid import NAMESPACE_URL, uuid5

from harness_mem.mcp.handler_facade_proxy import tool_handlers_facade as _core
from harness_mem.mcp.read_query_support import _action
from harness_mem.retrieval_signals import record_retrieval_signal


VALID_CONTEXT_OUTCOMES: frozenset[str] = frozenset({"used", "ignored", "misleading"})
CONTEXT_OUTCOME_VALUES: dict[str, float] = {
    "used": 1.0,
    "ignored": 0.0,
    "misleading": -1.0,
}


async def _resolve_context_outcome_targets(
    backend,
    *,
    project_name: str,
    surface: str,
    retrieval_id: str | None,
    source_ids: list[str],
) -> list[tuple[str, str]]:
    """Resolve opaque retrieval correlation back to the surfaced record kinds."""

    requested = set(source_ids)
    if retrieval_id:
        signals = await backend.structured_store.query_retrieval_signals(
            project_name,
            limit=1000,
        )
        resolved: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for signal in signals:
            context = signal.context if isinstance(signal.context, dict) else {}
            identity = (signal.target_kind, signal.target_id)
            if (
                signal.signal_type not in {"search_hit", "wake_surfaced"}
                or context.get("retrieval_id") != retrieval_id
                or context.get("surface") != surface
                or (requested and signal.target_id not in requested)
                or identity in seen
            ):
                continue
            seen.add(identity)
            resolved.append(identity)
        resolved_ids = {target_id for _kind, target_id in resolved}
        if requested and resolved_ids != requested:
            return []
        return resolved
    return [("context_source", source_id) for source_id in source_ids]


def tool_record_context_outcome(
    project_name: str,
    surface: str,
    outcome: str,
    source_ids: list[str] | None = None,
    reason: str | None = None,
    retrieval_id: str | None = None,
    _backend=None,
) -> dict:
    """Record whether surfaced context helped the task without mutating truth."""

    resolved_project = (project_name or "").strip()
    if not resolved_project:
        return {
            "success": False,
            "error": "project_name must not be empty",
            "truth_mutated": False,
        }
    normalized_surface = (surface or "").strip()
    if not normalized_surface:
        return {
            "success": False,
            "error": "surface must not be empty",
            "truth_mutated": False,
        }
    normalized_outcome = (outcome or "").strip().lower()
    if normalized_outcome not in VALID_CONTEXT_OUTCOMES:
        return {
            "success": False,
            "error": "outcome must be one of: used, ignored, misleading",
            "truth_mutated": False,
        }
    cleaned_source_ids = [
        str(source_id).strip()
        for source_id in (source_ids or [])
        if str(source_id).strip()
    ]
    normalized_retrieval_id = (retrieval_id or "").strip()[:128] or None
    if not cleaned_source_ids and normalized_retrieval_id is None:
        return {
            "success": False,
            "error": "retrieval_id or source_ids must identify surfaced context",
            "truth_mutated": False,
        }

    backend = _backend or _core._get_backend()
    resolved_targets = asyncio.run(
        _resolve_context_outcome_targets(
            backend,
            project_name=resolved_project,
            surface=normalized_surface,
            retrieval_id=normalized_retrieval_id,
            source_ids=cleaned_source_ids,
        )
    )
    if not resolved_targets:
        return {
            "success": False,
            "error": "retrieval_id did not resolve to surfaced context",
            "truth_mutated": False,
        }
    signal_ids: list[str] = []
    failed_source_ids: list[str] = []
    context = {
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "reason": (reason or "").strip()[:500] or None,
        "retrieval_id": normalized_retrieval_id,
    }
    value = CONTEXT_OUTCOME_VALUES[normalized_outcome]
    for target_kind, source_id in resolved_targets:
        signal = asyncio.run(
            record_retrieval_signal(
                backend,
                project_name=resolved_project,
                signal_type="context_outcome",
                target_kind=target_kind,
                target_id=source_id,
                value=value,
                context=context,
                signal_id=(
                    str(
                        uuid5(
                            NAMESPACE_URL,
                            "harness-mem:context-outcome:"
                            f"{resolved_project}:{normalized_retrieval_id}:"
                            f"{target_kind}:{source_id}:{normalized_outcome}",
                        )
                    )
                    if normalized_retrieval_id
                    else None
                ),
            )
        )
        if signal is None:
            failed_source_ids.append(source_id)
        else:
            signal_ids.append(signal.id)

    return {
        "success": not failed_source_ids,
        "project_name": resolved_project,
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "retrieval_id": normalized_retrieval_id,
        "recorded_count": len(signal_ids),
        "failed_count": len(failed_source_ids),
        "signal_ids": signal_ids,
        "failed_source_ids": failed_source_ids,
        "truth_mutated": False,
        "next_actions": [
            _action(
                "search_again",
                "/hm:search",
                "Opt-in projects can use outcome signals as a small explainable ranking hint.",
            )
        ],
        "why_this_result": (
            f"Recorded {len(signal_ids)} context outcome signals; confirmed truth was not changed."
        ),
        "degraded_reason": "signal_write_failed" if failed_source_ids else None,
    }


__all__ = ["VALID_CONTEXT_OUTCOMES", "tool_record_context_outcome"]
