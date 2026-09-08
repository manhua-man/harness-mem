"""Query interpretation, quality signals, and read-side DX metadata."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _quality_signal_target(*parts: str | None) -> str:
    payload = "\x1f".join(part or "" for part in parts).encode("utf-8")
    return f"query:{hashlib.sha256(payload).hexdigest()[:16]}"


def _new_retrieval_id() -> str:
    """Return an opaque correlation id that carries no query or source content."""

    return f"retrieval-{uuid4().hex}"


async def _record_search_quality_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str,
    entries: list[Any],
    relation_facts: list[Any] | None = None,
    observations: list[Any] | None = None,
    response: Any,
    context_plan: Any,
    historical_excluded: int = 0,
    retrieval_id: str | None = None,
    surface: str = "search_memory",
) -> dict[str, Any]:
    """Write bounded, content-free shadow metrics for one search call."""

    correlation = retrieval_id or _new_retrieval_id()
    attempted = 0
    recorded = 0
    recorded_source_ids: set[str] = set()

    async def write_signal(**kwargs: Any) -> None:
        nonlocal attempted, recorded
        attempted += 1
        if await record_retrieval_signal(backend, **kwargs) is not None:
            recorded += 1
            if kwargs.get("signal_type") == "search_hit":
                target_id = str(kwargs.get("target_id") or "")
                if target_id:
                    recorded_source_ids.add(target_id)

    surfaced = [
        *(
            (
                "knowledge_entry" if isinstance(entry, KnowledgeEntry) else "memory_entry",
                entry,
            )
            for entry in entries
        ),
        *(('context_source', fact) for fact in (relation_facts or [])),
        *(('observation', observation) for observation in (observations or [])),
    ]
    seen_targets: set[tuple[str, str]] = set()
    for target_kind, record in surfaced:
        target_id = str(getattr(record, "id", "") or "")
        identity = (target_kind, target_id)
        if not target_id or identity in seen_targets:
            continue
        seen_targets.add(identity)
        await write_signal(
            project_name=project_name,
            signal_type="search_hit",
            target_kind=target_kind,
            target_id=target_id,
            context={
                "surface": surface,
                "retrieval_id": correlation,
            },
        )

    if historical_excluded > 0:
        await write_signal(
            project_name=project_name,
            signal_type="retrieval_excluded",
            target_kind="context_source",
            target_id=_quality_signal_target(project_name, query, "historical"),
            value=float(historical_excluded),
            context={
                "surface": surface,
                "reason": "historical",
                "retrieval_id": correlation,
            },
        )

    reason: str | None = None
    if not list(getattr(response, "results", []) or []):
        reason = "no_evidence"
    elif context_plan is not None and not bool(
        getattr(context_plan.context_sufficiency, "safe_to_answer", False)
    ):
        reason = "insufficient_context"
    if reason is not None:
        await write_signal(
            project_name=project_name,
            signal_type="retrieval_abstained",
            target_kind="context_source",
            target_id=_quality_signal_target(project_name, query),
            value=1.0,
            context={
                "surface": surface,
                "reason": reason,
                "result_count": len(list(getattr(response, "results", []) or [])),
                "retrieval_id": correlation,
            },
        )
    failed = attempted - recorded
    return {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": correlation,
        "surface": surface,
        "attempted": attempted,
        "recorded": recorded,
        "failed": failed,
        "state": "degraded" if failed else "ok",
        "source_ids": sorted(recorded_source_ids),
        "content_recorded": False,
    }


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
