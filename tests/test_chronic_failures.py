"""Tests for :func:`harness_mem.commands.doctor.chronic_failures` (Req 4).

The diagnostic is a read-only multi-failure aggregation over the
``reflection_jobs`` table. It buckets every ``failed`` job whose
``updated_at`` falls within ``CHRONIC_FAILURE_LOOKBACK`` (7 days) by error
sub-category, then reports only the buckets that breach the chronic
threshold (``count > CHRONIC_FAILURE_THRESHOLD`` — i.e. more than 3 failures,
so >= 4 with the default M=3). For each surviving bucket it surfaces the top
three offenders by ``updated_at`` descending.

This is deliberately distinct from v2.4.0 Req 8.4 ``latest_error`` (in
``queue_health``), which reports the *single* most recent failed job
regardless of frequency. v2.4.2 chronic-failure answers "is anything broken
on a chronic basis?" rather than "did anything just break?" (Req 4.7).

Seeding: failed ``ReflectionJob`` rows are written through the store, then
``updated_at`` is back-dated by directly rewriting both the ``updated_at``
column and the ``data`` blob's ``updated_at`` field — ``ReflectionJobStore.save``
always bumps ``updated_at`` to "now" on write, and ``chronic_failures`` reads
``updated_at`` out of the ``data`` blob (via ``list`` -> ``from_dict``), so the
blob is the field that must be back-dated. Async functions are driven via
:func:`tests.helpers.run` (``asyncio.run``). The autouse ``data_dir`` fixture
in :mod:`tests.conftest` keeps writes scoped to ``tmp_path``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.doctor import chronic_failures, queue_health
from harness_mem.commands.doctor_thresholds import (
    CHRONIC_FAILURE_LOOKBACK,
    CHRONIC_FAILURE_THRESHOLD,
)
from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex
from tests.helpers import run

PROJECT = "demo"

# Top-level keys the report dict must always expose.
_REQUIRED_REPORT_KEYS = {
    "lookback_days",
    "threshold",
    "subcategories",
    "is_chronic",
}


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """A fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "doctor_chronic_failures.db"
    sqldb = SQLiteIndex(db_path)
    sqldb.init_db()
    try:
        yield sqldb
    finally:
        sqldb.close()


@pytest.fixture
def store(index: SQLiteIndex) -> ReflectionJobStore:
    return ReflectionJobStore(index)


# ---- seed helpers --------------------------------------------------------


def _make_failed_job(
    *,
    error: str,
    project_name: str = PROJECT,
    phase: str = "ingest",
    idempotency_key: str | None = None,
) -> ReflectionJob:
    """Build a failed ReflectionJob with the test-relevant overrides."""
    kwargs: dict = {
        "project_name": project_name,
        "project_root": "/tmp/" + project_name,
        "status": "failed",
        "phase": phase,
        "source": "agent",
        "error": error,
    }
    if idempotency_key is not None:
        # extra="allow" lets the store mirror this onto the index column.
        kwargs["idempotency_key"] = idempotency_key
    return ReflectionJob(**kwargs)


def _backdate_updated_at(
    index: SQLiteIndex, job_id: str, updated_at: datetime
) -> None:
    """Rewrite a row's ``updated_at`` (column + ``data`` blob) to the past.

    ``ReflectionJobStore.save`` always sets ``updated_at`` to "now", and
    ``chronic_failures`` reads the value out of the ``data`` blob, so both
    surfaces must be updated for the back-date to take effect.
    """
    conn = index._conn_write()
    with index._lock:
        row = conn.execute(
            "SELECT data FROM reflection_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        blob = json.loads(row["data"])
        blob["updated_at"] = updated_at.isoformat()
        conn.execute(
            "UPDATE reflection_jobs SET updated_at = ?, data = ? WHERE id = ?",
            (updated_at.isoformat(), json.dumps(blob), job_id),
        )
        conn.commit()


def _seed_failed(
    store: ReflectionJobStore,
    index: SQLiteIndex,
    *,
    error: str,
    count: int,
    updated_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> list[ReflectionJob]:
    """Seed ``count`` failed jobs sharing one error, optionally back-dated."""
    jobs: list[ReflectionJob] = []
    for _ in range(count):
        job = _make_failed_job(error=error, idempotency_key=idempotency_key)
        store.save(job)
        if updated_at is not None:
            _backdate_updated_at(index, job.id, updated_at)
        jobs.append(job)
    return jobs


def _snapshot_rows(index: SQLiteIndex) -> list[tuple]:
    """Stable snapshot of the reflection_jobs table for read-only assertions."""
    conn = index._conn_write()
    rows = conn.execute(
        "SELECT id, project_name, status, kind, phase, source, "
        "idempotency_key, data, created_at, updated_at, "
        "lease_owner, lease_until, attempt_count "
        "FROM reflection_jobs ORDER BY id"
    ).fetchall()
    return [tuple(row) for row in rows]


def _subcat(report: dict, label: str) -> dict | None:
    for sub in report["subcategories"]:
        if sub["label"] == label:
            return sub
    return None


# ---- test 1: empty queue ------------------------------------------------


def test_empty_queue_is_not_chronic(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.5 — fresh store reports no chronic failures."""
    report = run(chronic_failures(store, PROJECT))

    assert set(report.keys()) == _REQUIRED_REPORT_KEYS
    assert report["lookback_days"] == 7
    assert report["threshold"] == 3
    assert report["subcategories"] == []
    assert report["is_chronic"] is False


# ---- test 2: sub-category bucketing for each known pattern --------------


@pytest.mark.parametrize(
    ("error", "expected_label"),
    [
        ("job_store_unavailable", "job_store_unavailable"),
        ("max_retries_exceeded", "max_retries_exceeded"),
        ("ingest: foo", "ingest"),
        ("prepare: bar", "prepare"),
        ("distill: baz", "distill"),
    ],
)
def test_known_pattern_bucketing(
    store: ReflectionJobStore,
    index: SQLiteIndex,
    error: str,
    expected_label: str,
) -> None:
    """Validates: Requirements 4.2, 4.3 — each known pattern maps to its label.

    The stage-prefix patterns (``ingest:`` / ``prepare:`` / ``distill:``)
    label without the trailing colon; the flag patterns keep their full text.
    """
    _seed_failed(store, index, error=error, count=4)

    report = run(chronic_failures(store, PROJECT))

    assert report["is_chronic"] is True
    assert len(report["subcategories"]) == 1
    sub = report["subcategories"][0]
    assert sub["label"] == expected_label
    assert sub["count"] == 4


# ---- test 3: the "other" bucket -----------------------------------------


def test_other_bucket_for_unknown_error(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.3 — unrecognized errors group under 'other'."""
    _seed_failed(store, index, error="some random error", count=4)

    report = run(chronic_failures(store, PROJECT))

    assert report["is_chronic"] is True
    sub = _subcat(report, "other")
    assert sub is not None
    assert sub["count"] == 4


# ---- test 4: count at threshold is NOT chronic --------------------------


def test_count_exactly_at_threshold_is_not_chronic(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.5 — count == threshold (3) is below chronic.

    Chronic requires *more than* M failures (count > 3), so exactly 3 of the
    same pattern must produce no subcategory and is_chronic False.
    """
    assert CHRONIC_FAILURE_THRESHOLD == 3
    _seed_failed(store, index, error="job_store_unavailable", count=3)

    report = run(chronic_failures(store, PROJECT))

    assert report["subcategories"] == []
    assert report["is_chronic"] is False


# ---- test 5: count above threshold IS chronic ---------------------------


def test_count_above_threshold_is_chronic(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.1, 4.5 — count == threshold + 1 (4) is chronic."""
    _seed_failed(store, index, error="job_store_unavailable", count=4)

    report = run(chronic_failures(store, PROJECT))

    sub = _subcat(report, "job_store_unavailable")
    assert sub is not None
    assert sub["count"] == 4
    assert report["is_chronic"] is True


# ---- test 6: top-3 offender selection -----------------------------------


def test_top_3_offenders_are_the_newest_by_updated_at(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.4 — at most 3 offenders, newest updated_at first."""
    now = datetime.now(timezone.utc)
    # Seed 5 jobs of one pattern, each with a distinct (back-dated, but still
    # within the 7-day lookback) updated_at: 1h, 2h, 3h, 4h, 5h old.
    ages_hours = [1, 2, 3, 4, 5]
    jobs_by_age: dict[int, str] = {}
    for hours in ages_hours:
        [job] = _seed_failed(
            store,
            index,
            error="max_retries_exceeded",
            count=1,
            updated_at=now - timedelta(hours=hours),
        )
        jobs_by_age[hours] = job.id

    report = run(chronic_failures(store, PROJECT))

    sub = _subcat(report, "max_retries_exceeded")
    assert sub is not None
    assert sub["count"] == 5
    # Exactly 3 offenders, and they are the 3 newest (1h, 2h, 3h old).
    assert len(sub["top_offenders"]) == 3
    surfaced_ids = [o["job_id"] for o in sub["top_offenders"]]
    assert surfaced_ids == [jobs_by_age[1], jobs_by_age[2], jobs_by_age[3]]
    # updated_at strings are in descending order.
    timestamps = [o["updated_at"] for o in sub["top_offenders"]]
    assert timestamps == sorted(timestamps, reverse=True)


# ---- test 7: lookback window excludes old failures ----------------------


def test_failures_outside_lookback_are_excluded(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.1 — only failures within K days count."""
    now = datetime.now(timezone.utc)
    old = now - CHRONIC_FAILURE_LOOKBACK - timedelta(days=1)
    # 4 jobs older than the lookback window → must be excluded → not chronic.
    _seed_failed(
        store, index, error="job_store_unavailable", count=4, updated_at=old
    )

    report = run(chronic_failures(store, PROJECT))

    assert report["subcategories"] == []
    assert report["is_chronic"] is False


def test_failures_within_lookback_are_chronic(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.1 — 4 failures inside K days are chronic."""
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=1)  # comfortably inside the 7-day window.
    _seed_failed(
        store, index, error="job_store_unavailable", count=4, updated_at=recent
    )

    report = run(chronic_failures(store, PROJECT))

    sub = _subcat(report, "job_store_unavailable")
    assert sub is not None
    assert sub["count"] == 4
    assert report["is_chronic"] is True


# ---- test 8: distinction from v2.4.0 Req 8.4 ----------------------------


def test_single_failure_is_not_chronic_but_is_latest_error(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.7 — chronic is distinct from latest_error.

    A single failed job within the lookback window is reported by v2.4.0
    ``queue_health`` as ``latest_error`` (Req 8.4), but ``chronic_failures``
    returns ``is_chronic=False`` because the count is below threshold. The
    two surfaces are complementary, not duplicative.
    """
    store.save(_make_failed_job(error="job_store_unavailable"))

    chronic = run(chronic_failures(store, PROJECT))
    assert chronic["is_chronic"] is False
    assert chronic["subcategories"] == []

    # The same single failure DOES surface through v2.4.0 queue_health.
    queue = run(queue_health(store))
    assert queue["latest_error"] is not None
    assert queue["latest_error"]["error"] == "job_store_unavailable"


# ---- test 9: counts span idempotency keys -------------------------------


def test_chronic_counts_all_failed_rows_regardless_of_idempotency_key(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.1 — repeated failures accumulate to one counter.

    Per the v2.4.0 idempotency contract, the chronic detector counts every
    failed row in the window without de-duplicating by idempotency key. This
    test mixes 2 same-key repeats and 2 distinct-key clusters of the same
    error pattern; all 4 must accumulate toward the same chronic counter.
    """
    # Two failures of the SAME logical job (same idempotency key).
    _seed_failed(
        store,
        index,
        error="ingest: boom",
        count=2,
        idempotency_key="same-key",
    )
    # Two failures with DISTINCT idempotency keys.
    _seed_failed(
        store, index, error="ingest: boom", count=1, idempotency_key="key-a"
    )
    _seed_failed(
        store, index, error="ingest: boom", count=1, idempotency_key="key-b"
    )

    report = run(chronic_failures(store, PROJECT))

    sub = _subcat(report, "ingest")
    assert sub is not None
    # All 4 rows accumulate to the same counter (4 > 3 → chronic).
    assert sub["count"] == 4
    assert report["is_chronic"] is True


# ---- test 10: read-only invariant ---------------------------------------


def test_chronic_failures_is_read_only(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.6 — no row mutation across a chronic_failures call."""
    now = datetime.now(timezone.utc)
    _seed_failed(
        store,
        index,
        error="job_store_unavailable",
        count=4,
        updated_at=now - timedelta(days=1),
    )
    _seed_failed(store, index, error="some random error", count=2)

    before = _snapshot_rows(index)
    run(chronic_failures(store, PROJECT))
    after = _snapshot_rows(index)

    assert before == after


# ---- test 11: multiple chronic sub-categories ordered deterministically -


def test_multiple_subcategories_ordered_by_count_desc(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.2, 4.4 — distinct patterns each get a line.

    Ordering is count-desc so the worst offender bucket renders first.
    """
    _seed_failed(store, index, error="job_store_unavailable", count=5)
    _seed_failed(store, index, error="max_retries_exceeded", count=4)
    # Below threshold → must NOT appear.
    _seed_failed(store, index, error="distill: nope", count=2)

    report = run(chronic_failures(store, PROJECT))

    labels = [sub["label"] for sub in report["subcategories"]]
    assert labels == ["job_store_unavailable", "max_retries_exceeded"]
    assert _subcat(report, "distill") is None
    assert report["is_chronic"] is True
