"""Tests for :func:`harness_mem.commands.doctor.signal_freshness` (Req 3).

The diagnostic is a read-only per-signal-type freshness report over the
``retrieval_signals`` table. For each of the five tracked signal types
(``search_hit``, ``wake_surfaced``, ``supersede_completed``,
``skill_result_success``, ``skill_result_failure``) it surfaces the most
recent ``recorded_at`` timestamp (ISO 8601), its age in seconds, and whether
the type has gone dormant. A type with zero events is treated as dormant
(``is_dormant=True``, ``latest_timestamp=None``, ``age_seconds=None``).
``all_silent`` is ``True`` only when every type has zero events.

Signals are seeded directly through ``save_retrieval_signal`` with an explicit
``recorded_at`` so the dormant boundary (``DORMANT_SIGNAL_AGE`` = 30 days) can
be exercised precisely. Async functions are driven via :func:`tests.helpers.run`
(``asyncio.run``). The store is scoped to ``tmp_path`` per the data-isolation
rule. Age boundaries use a comfortable margin (threshold ± 1 day) rather than
freezing the clock, so wall-clock jitter is irrelevant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.doctor import signal_freshness
from harness_mem.commands.doctor_thresholds import DORMANT_SIGNAL_AGE
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

PROJECT = "demo"

# Every tracked signal type the payload must always expose (Req 3.1).
_SIGNAL_TYPES = {
    "search_hit",
    "wake_surfaced",
    "supersede_completed",
    "skill_result_success",
    "skill_result_failure",
}

# Per-type dict keys the summary must always expose.
_SUMMARY_KEYS = {"latest_timestamp", "age_seconds", "is_dormant"}


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> LocalStructuredStore:
    """A fresh LocalStructuredStore scoped to tmp_path, closed on teardown."""
    local_store = LocalStructuredStore(tmp_path / "data")
    try:
        yield local_store
    finally:
        local_store.close()


# ---- seed helpers --------------------------------------------------------


def _seed_signal(
    store: LocalStructuredStore,
    *,
    signal_type: str,
    recorded_at: datetime,
    target_id: str = "target-1",
) -> RetrievalSignal:
    signal = RetrievalSignal(
        project_name=PROJECT,
        signal_type=signal_type,
        target_kind="memory_entry",
        target_id=target_id,
        recorded_at=recorded_at,
    )
    run(store.save_retrieval_signal(signal))
    return signal


def _dormant_time() -> datetime:
    """A recorded_at comfortably older than DORMANT_SIGNAL_AGE."""
    return datetime.now(timezone.utc) - DORMANT_SIGNAL_AGE - timedelta(days=1)


def _fresh_time() -> datetime:
    """A recorded_at well inside the dormant threshold."""
    return datetime.now(timezone.utc) - timedelta(hours=1)


def _snapshot_blobs(store: LocalStructuredStore) -> dict[str, str]:
    """Map of relative blob path -> file content, for read-only assertions."""
    snapshot: dict[str, str] = {}
    for path in sorted(store.blob_dir.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(store.blob_dir))] = path.read_text()
    return snapshot


# ---- test 1: per-signal-type latest detection ---------------------------


def test_latest_timestamp_is_the_newest_event_of_a_type(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 3.1 — latest_timestamp tracks the newest row."""
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=3)
    newer = now - timedelta(days=1)
    _seed_signal(store, signal_type="search_hit", recorded_at=older, target_id="a")
    _seed_signal(store, signal_type="search_hit", recorded_at=newer, target_id="b")

    report = run(signal_freshness(store, PROJECT))

    summary = report["search_hit"]
    parsed = datetime.fromisoformat(summary["latest_timestamp"])
    assert abs((parsed - newer).total_seconds()) < 1
    assert summary["is_dormant"] is False
    # Age reflects the newer event, not the older one.
    assert summary["age_seconds"] < int(timedelta(days=2).total_seconds())


# ---- test 2: dormant boundary -------------------------------------------


def test_dormant_boundary_at_threshold(store: LocalStructuredStore) -> None:
    """Validates: Requirements 3.2 — >30d dormant, <30d fresh."""
    now = datetime.now(timezone.utc)
    # 31 days old → dormant.
    _seed_signal(
        store,
        signal_type="search_hit",
        recorded_at=now - timedelta(days=31),
    )
    # 29 days old → not dormant.
    _seed_signal(
        store,
        signal_type="wake_surfaced",
        recorded_at=now - timedelta(days=29),
    )

    report = run(signal_freshness(store, PROJECT))

    assert report["search_hit"]["is_dormant"] is True
    assert report["wake_surfaced"]["is_dormant"] is False


# ---- test 3: never-events ------------------------------------------------


def test_never_seen_type_is_dormant_with_null_fields(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 3.1, 3.2 — zero rows → null + dormant."""
    # Seed only search_hit; the other four types have zero events.
    _seed_signal(store, signal_type="search_hit", recorded_at=_fresh_time())

    report = run(signal_freshness(store, PROJECT))

    for signal_type in _SIGNAL_TYPES - {"search_hit"}:
        summary = report[signal_type]
        assert summary["latest_timestamp"] is None, signal_type
        assert summary["age_seconds"] is None, signal_type
        assert summary["is_dormant"] is True, signal_type


# ---- test 4: all-silent --------------------------------------------------


def test_all_silent_when_store_empty(store: LocalStructuredStore) -> None:
    """Validates: Requirements 3.7 — empty store → every type dormant + all_silent."""
    report = run(signal_freshness(store, PROJECT))

    assert set(report.keys()) == _SIGNAL_TYPES | {"all_silent"}
    assert report["all_silent"] is True
    for signal_type in _SIGNAL_TYPES:
        summary = report[signal_type]
        assert set(summary.keys()) == _SUMMARY_KEYS, signal_type
        assert summary["latest_timestamp"] is None, signal_type
        assert summary["age_seconds"] is None, signal_type
        assert summary["is_dormant"] is True, signal_type


# ---- test 5: mixed fresh / dormant --------------------------------------


def test_mixed_fresh_and_empty_is_not_all_silent(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 3.7 — any event present → all_silent False."""
    _seed_signal(store, signal_type="skill_result_success", recorded_at=_fresh_time())

    report = run(signal_freshness(store, PROJECT))

    assert report["all_silent"] is False
    # The fresh type is not dormant; the others (no events) are dormant.
    assert report["skill_result_success"]["is_dormant"] is False
    for signal_type in _SIGNAL_TYPES - {"skill_result_success"}:
        assert report[signal_type]["is_dormant"] is True, signal_type


# ---- test 6: read-only invariant ----------------------------------------


def test_signal_freshness_is_read_only(store: LocalStructuredStore) -> None:
    """Validates: Requirements 3.6 — no blob mutation across the call."""
    _seed_signal(store, signal_type="search_hit", recorded_at=_fresh_time())
    _seed_signal(store, signal_type="wake_surfaced", recorded_at=_dormant_time())
    _seed_signal(
        store, signal_type="supersede_completed", recorded_at=_dormant_time()
    )

    before = _snapshot_blobs(store)
    run(signal_freshness(store, PROJECT))
    after = _snapshot_blobs(store)

    assert before == after
