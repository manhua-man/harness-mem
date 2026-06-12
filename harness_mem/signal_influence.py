"""Per-target retrieval-signal aggregation helper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@dataclass(frozen=True)
class TargetSignalSummary:
    """Per-target aggregate of wake/search retrieval signals."""

    wake_surfaced_count: int
    search_hit_count: int
    last_signal_at: datetime | None


async def pull_recent_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_ids: list[str],
    since: datetime,
) -> dict[str, TargetSignalSummary]:
    """Aggregate ``wake_surfaced`` + ``search_hit`` signals per target."""

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

    wake_counts: dict[str, int] = {tid: 0 for tid in target_id_set}
    search_counts: dict[str, int] = {tid: 0 for tid in target_id_set}
    last_at: dict[str, datetime | None] = {tid: None for tid in target_id_set}

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

    return {
        tid: TargetSignalSummary(
            wake_surfaced_count=wake_counts[tid],
            search_hit_count=search_counts[tid],
            last_signal_at=last_at[tid],
        )
        for tid in target_id_set
    }


__all__ = ["TargetSignalSummary", "pull_recent_signals"]
