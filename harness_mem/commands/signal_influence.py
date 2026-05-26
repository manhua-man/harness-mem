"""Per-target retrieval-signal aggregation helper for v2.3.1 weak-link
signal application.

The wake renderer (task 4.2), search ranker (task 4.3), and doctor
transparency block (task 4.4) all need a "how many surface signals
hit each of these targets in this time window" view. This module
exposes :func:`pull_recent_signals` that builds it from the v2.3.0
``RetrievalSignal`` stream.

The signals layer (v2.3.0) only filters by a single ``signal_type``
per query, so this helper issues two queries (``wake_surfaced`` +
``search_hit``) and merges the results in memory. Other signal types
(``confirmed`` / ``rejected`` / ``skill_result_*`` /
``supersede_completed``) are review-side and out of scope here.

The ``ProjectProfile.weak_link_signals`` flag (default ``False`` in
v2.3.1, see design.md) gates whether the wake / search call sites
actually invoke this helper. The helper itself is unconditional — it
simply returns the aggregate when called.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@dataclass(frozen=True)
class TargetSignalSummary:
    """Per-target aggregate of ``wake_surfaced`` + ``search_hit`` signals.

    Returned by :func:`pull_recent_signals` for each target_id the
    caller asked about. Counts are 0 when the target had no signal of
    that type in the window; ``last_signal_at`` is ``None`` when the
    target had zero matching signals overall.

    Used downstream:

    - 4.2 wake re-grouping: a rule is "recent active" iff
      ``wake_surfaced_count + search_hit_count > 0``.
    - 4.3 search boost: an entry receives the boost iff
      ``search_hit_count >= 2``.
    - 4.4 doctor transparency: per-target counts feed the report.
    """

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
    """Aggregate ``wake_surfaced`` + ``search_hit`` signals per target.

    Returns a map from each requested ``target_id`` to its summary.
    Targets with no matching signals get a zero-counts summary with
    ``last_signal_at=None`` — the dict always has every requested id
    as a key, simplifying the call sites' ``.get(...)`` lookups.

    Caller controls the time window via ``since``; the helper does
    not pick a default. Wake passes ``now - 30d``; search passes
    ``now - 7d``; doctor may call twice with different windows.

    Implementation runs **two** ``query_retrieval_signals`` calls:
    ``query_retrieval_signals`` only filters by a single
    ``signal_type``, so we issue one query per type and merge the
    results in memory. Empty ``target_ids`` short-circuits to an
    empty dict — no IO.
    """
    if not target_ids:
        return {}

    target_id_set = set(target_ids)

    # The API is single-type per call; two queries cover the two surface
    # signal types we care about. The wake / search ranker doesn't care
    # about confirmed / rejected / skill_result_* / supersede_completed
    # — those are review-side, not retrieval-side.
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

    # Aggregate per target_id; track max(recorded_at) across both types.
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
