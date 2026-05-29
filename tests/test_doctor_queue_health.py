"""Tests for :func:`harness_mem.commands.doctor.queue_health` (Req 8).

The diagnostic is intentionally read-only: it pulls structured counts /
ages / lease info / latest error / needs_distill payload off the
:class:`ReflectionJobStore` without ever calling a mutating method.
These tests prove that contract and the exact dict shape the CLI and
MCP consumers branch on.

We seed jobs directly through the store (skipping the full
:func:`reflection_once` pipeline) so the assertions stay focused on the
diagnostic logic rather than the trigger orchestration. The autouse
``data_dir`` fixture in :mod:`tests.conftest` keeps writes scoped to
``tmp_path`` per the project rules.

Following the rest of the suite's convention, async functions are
driven via :func:`tests.helpers.run` (``asyncio.run``) instead of
``pytest-asyncio``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.doctor import queue_health
from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex
from tests.helpers import run


# Status keys that MUST always be present in status_counts (Req 8.1, 8.6).
_REQUIRED_STATUS_KEYS = {
    "pending",
    "processing",
    "completed",
    "failed",
    "retryable",
    "needs_distill",
}

# Top-level keys the report dict must always expose (Req 8.8).
_REQUIRED_REPORT_KEYS = {
    "status_counts",
    "oldest_waiting_age_seconds",
    "active_leases",
    "latest_error",
    "needs_distill",
}

# Canned next-action string from Req 8.5 — kept here so the test fails
# loudly if the production string drifts.
_EXPECTED_NEXT_ACTION = (
    "Run /hm:distill or invoke MCP distill tool to complete this job"
)


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """A fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "doctor_queue_health.db"
    sqldb = SQLiteIndex(db_path)
    sqldb.init_db()
    try:
        yield sqldb
    finally:
        sqldb.close()


@pytest.fixture
def store(index: SQLiteIndex) -> ReflectionJobStore:
    return ReflectionJobStore(index)


# ---- helpers -------------------------------------------------------------


def _make_job(
    *,
    status: str = "pending",
    project_name: str = "demo",
    phase: str = "ingest",
    source: str = "agent",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    lease_owner: str | None = None,
    lease_until: datetime | None = None,
    error: str | None = None,
    attempt_count: int = 0,
) -> ReflectionJob:
    """Build a ReflectionJob with the test-relevant overrides."""
    kwargs: dict = {
        "project_name": project_name,
        "project_root": "/tmp/" + project_name,
        "status": status,
        "phase": phase,
        "source": source,
        "lease_owner": lease_owner,
        "lease_until": lease_until,
        "error": error,
        "attempt_count": attempt_count,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    if updated_at is not None:
        kwargs["updated_at"] = updated_at
    return ReflectionJob(**kwargs)


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


# ---- test 1: empty queue ------------------------------------------------


def test_empty_queue_reports_all_zero(store: ReflectionJobStore) -> None:
    """Validates: Requirements 8.1, 8.6, 8.8 — fresh store reports defaults."""
    report = run(queue_health(store))

    assert set(report.keys()) == _REQUIRED_REPORT_KEYS
    assert set(report["status_counts"].keys()) == _REQUIRED_STATUS_KEYS
    assert all(v == 0 for v in report["status_counts"].values())
    assert report["oldest_waiting_age_seconds"] is None
    assert report["active_leases"] == []
    assert report["latest_error"] is None
    assert report["needs_distill"] == []


# ---- test 2: status counts ----------------------------------------------


def test_status_counts_reflect_mixed_jobs(store: ReflectionJobStore) -> None:
    """Validates: Requirements 8.1 — counts match exactly across all statuses."""
    # 2 pending + 3 processing + 1 completed + 1 failed + 1 retryable + 2 needs_distill
    spec = [
        ("pending", 2),
        ("processing", 3),
        ("completed", 1),
        ("failed", 1),
        ("retryable", 1),
        ("needs_distill", 2),
    ]
    for status, count in spec:
        for _ in range(count):
            store.save(_make_job(status=status))

    report = run(queue_health(store))

    assert report["status_counts"] == {
        "pending": 2,
        "processing": 3,
        "completed": 1,
        "failed": 1,
        "retryable": 1,
        "needs_distill": 2,
    }


# ---- test 3 & 4: oldest waiting age -------------------------------------


def test_oldest_waiting_age_includes_pending_and_retryable(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.2 — oldest spans pending ∪ retryable.

    Layout: 1h-old pending wins over the more recent retryable / processing /
    pending entries, because Req 8.2 only considers pending OR retryable.
    """
    now = datetime.now(timezone.utc)
    store.save(_make_job(status="pending", created_at=now - timedelta(hours=1)))
    store.save(_make_job(status="retryable", created_at=now - timedelta(minutes=30)))
    # processing jobs are NOT eligible for oldest_waiting_age.
    store.save(_make_job(status="processing", created_at=now - timedelta(minutes=10)))
    store.save(_make_job(status="pending", created_at=now - timedelta(minutes=5)))

    report = run(queue_health(store))

    age = report["oldest_waiting_age_seconds"]
    assert age is not None
    # ±5s tolerance for wall-clock jitter between fixture creation and the
    # datetime.now() inside queue_health.
    assert 3600 - 5 <= age <= 3600 + 5


def test_oldest_waiting_age_none_when_no_pending_or_retryable(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.2 — None when no eligible jobs exist."""
    now = datetime.now(timezone.utc)
    store.save(_make_job(status="completed", created_at=now - timedelta(hours=1)))
    store.save(_make_job(status="failed", created_at=now - timedelta(hours=2)))

    report = run(queue_health(store))

    assert report["oldest_waiting_age_seconds"] is None


# ---- test 5 & 6: active leases ------------------------------------------


def test_active_leases_includes_unexpired_and_expired_with_flag(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.3 — both branches surface with correct flag."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=5)
    past = now - timedelta(minutes=5)

    fresh = _make_job(status="processing", lease_owner="worker-a", lease_until=future)
    stale = _make_job(status="processing", lease_owner="worker-b", lease_until=past)
    store.save(fresh)
    store.save(stale)

    report = run(queue_health(store))

    leases = {entry["job_id"]: entry for entry in report["active_leases"]}
    assert set(leases.keys()) == {fresh.id, stale.id}
    assert leases[fresh.id]["expired"] is False
    assert leases[stale.id]["expired"] is True
    # lease_until is serialized as ISO string, not datetime — callers (CLI
    # + MCP) treat the report as JSON-friendly.
    assert isinstance(leases[fresh.id]["lease_until"], str)
    assert isinstance(leases[stale.id]["lease_until"], str)


def test_active_leases_excludes_processing_with_no_lease(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.3 — defensive: a processing row with no
    lease has nothing to report on, so it must NOT appear in active_leases.
    """
    job = _make_job(status="processing", lease_owner=None, lease_until=None)
    store.save(job)

    report = run(queue_health(store))

    # The job still counts toward the processing total...
    assert report["status_counts"]["processing"] == 1
    # ...but doesn't appear in active_leases because there's no lease info
    # to flag as expired or not.
    assert report["active_leases"] == []


# ---- test 7 & 8: latest error -------------------------------------------


def test_latest_error_is_most_recent_failed(store: ReflectionJobStore) -> None:
    """Validates: Requirements 8.4 — picks failure with greatest updated_at.

    ``ReflectionJobStore.save`` bumps ``updated_at`` to "now" on every
    write, so save-order monotonicity gives us deterministic ordering:
    the last job saved has the latest ``updated_at``.
    """
    a = _make_job(status="failed", error="alpha")
    store.save(a)
    b = _make_job(status="failed", error="beta")
    store.save(b)
    c = _make_job(status="failed", error="charlie")
    store.save(c)
    # `c` was saved last → its updated_at is the latest.

    report = run(queue_health(store))

    latest = report["latest_error"]
    assert latest is not None
    assert latest["job_id"] == c.id
    assert latest["error"] == "charlie"
    assert isinstance(latest["updated_at"], str)


def test_latest_error_is_none_when_no_failures(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.4 — None when no failed jobs exist."""
    store.save(_make_job(status="completed"))
    store.save(_make_job(status="pending"))

    report = run(queue_health(store))

    assert report["latest_error"] is None


# ---- test 9: needs_distill ----------------------------------------------


def test_needs_distill_reports_jobs_with_canned_next_action(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.5 — payload uses the exact next_action string."""
    a = _make_job(status="needs_distill")
    b = _make_job(status="needs_distill")
    store.save(a)
    store.save(b)

    report = run(queue_health(store))

    payload = report["needs_distill"]
    assert len(payload) == 2
    assert {entry["job_id"] for entry in payload} == {a.id, b.id}
    assert all(entry["next_action"] == _EXPECTED_NEXT_ACTION for entry in payload)


# ---- test 10: read-only --------------------------------------------------


def test_queue_health_is_read_only(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 8.7 — no row mutation across a queue_health call.

    We snapshot every column we care about (including ``data`` and
    ``updated_at``) before and after; byte-identical equality proves
    queue_health did not call ``save`` or ``compare_and_set`` (both of
    which would bump ``updated_at`` and rewrite ``data``).
    """
    now = datetime.now(timezone.utc)
    store.save(_make_job(status="pending", created_at=now - timedelta(minutes=10)))
    store.save(
        _make_job(
            status="processing",
            lease_owner="worker-x",
            lease_until=now + timedelta(minutes=5),
        )
    )
    store.save(_make_job(status="failed", error="boom"))
    store.save(_make_job(status="needs_distill"))

    before = _snapshot_rows(index)
    run(queue_health(store))
    after = _snapshot_rows(index)

    assert before == after


# ---- test 11: structured-dict shape -------------------------------------


def test_queue_health_returns_structured_dict_with_all_keys(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 8.8 — keys always present regardless of state.

    We exercise three states: empty, mixed-but-no-failures, and a single
    needs_distill. Every variant must produce the full top-level key set
    so MCP / CLI consumers can branch on values rather than on key
    existence.
    """
    # Variant 1: empty.
    report = run(queue_health(store))
    assert set(report.keys()) == _REQUIRED_REPORT_KEYS
    assert set(report["status_counts"].keys()) == _REQUIRED_STATUS_KEYS

    # Variant 2: mix without failures.
    store.save(_make_job(status="pending"))
    store.save(_make_job(status="completed"))
    report = run(queue_health(store))
    assert set(report.keys()) == _REQUIRED_REPORT_KEYS
    assert set(report["status_counts"].keys()) == _REQUIRED_STATUS_KEYS

    # Variant 3: add a needs_distill (so that list is non-empty).
    store.save(_make_job(status="needs_distill"))
    report = run(queue_health(store))
    assert set(report.keys()) == _REQUIRED_REPORT_KEYS
    assert set(report["status_counts"].keys()) == _REQUIRED_STATUS_KEYS
