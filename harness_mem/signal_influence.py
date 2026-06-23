"""Per-target retrieval-signal aggregation helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@dataclass(frozen=True)
class TargetSignalSummary:
    """Per-target aggregate of wake/search retrieval signals."""

    wake_surfaced_count: int
    search_hit_count: int
    last_signal_at: datetime | None
    context_outcome_counts: dict[str, int] = field(default_factory=dict)
    context_outcome_score: float = 0.0
    last_context_outcome_at: datetime | None = None


async def pull_recent_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_ids: list[str],
    since: datetime,
) -> dict[str, TargetSignalSummary]:
    """Aggregate retrieval and context outcome signals per target."""

    if not target_ids:
        return {}

    target_id_set = set(target_ids)
    wake_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        since=since,
        limit=10000,
    )
    search_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=since,
        limit=10000,
    )
    outcome_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="context_outcome",
        since=since,
        limit=10000,
    )

    wake_counts: dict[str, int] = {tid: 0 for tid in target_id_set}
    search_counts: dict[str, int] = {tid: 0 for tid in target_id_set}
    last_at: dict[str, datetime | None] = {tid: None for tid in target_id_set}
    outcome_counts: dict[str, dict[str, int]] = {
        tid: {"used": 0, "ignored": 0, "misleading": 0} for tid in target_id_set
    }
    last_outcome_at: dict[str, datetime | None] = {tid: None for tid in target_id_set}

    for signal in wake_signals:
        if signal.target_id not in target_id_set:
            continue
        wake_counts[signal.target_id] += 1
        recorded = signal.recorded_at
        current = last_at[signal.target_id]
        if current is None or recorded > current:
            last_at[signal.target_id] = recorded

    for signal in search_signals:
        if signal.target_id not in target_id_set:
            continue
        search_counts[signal.target_id] += 1
        recorded = signal.recorded_at
        current = last_at[signal.target_id]
        if current is None or recorded > current:
            last_at[signal.target_id] = recorded

    for signal in outcome_signals:
        if signal.target_id not in target_id_set:
            continue
        context = signal.context or {}
        outcome = str(context.get("outcome") or "").strip().lower()
        if outcome not in {"used", "ignored", "misleading"}:
            continue
        outcome_counts[signal.target_id][outcome] += 1
        recorded = signal.recorded_at
        current = last_outcome_at[signal.target_id]
        if current is None or recorded > current:
            last_outcome_at[signal.target_id] = recorded
        current_any = last_at[signal.target_id]
        if current_any is None or recorded > current_any:
            last_at[signal.target_id] = recorded

    return {
        tid: TargetSignalSummary(
            wake_surfaced_count=wake_counts[tid],
            search_hit_count=search_counts[tid],
            last_signal_at=last_at[tid],
            context_outcome_counts=dict(outcome_counts[tid]),
            context_outcome_score=_context_outcome_score(outcome_counts[tid]),
            last_context_outcome_at=last_outcome_at[tid],
        )
        for tid in target_id_set
    }


def _context_outcome_score(counts: dict[str, int]) -> float:
    return (
        (counts.get("used", 0) * 0.08)
        - (counts.get("ignored", 0) * 0.04)
        - (counts.get("misleading", 0) * 0.12)
    )


__all__ = ["TargetSignalSummary", "pull_recent_signals"]
