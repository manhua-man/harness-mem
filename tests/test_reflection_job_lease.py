"""Lease manager tests for :func:`acquire_lease` (Req 4).

These tests exercise the acquisition contract end-to-end against a real
``ReflectionJobStore`` backed by a temp-file SQLite (per project rules:
no writes to ``~/.harness-mem/``). The store's CAS + threading lock
gives us the same atomicity guarantee in tests that production code
gets, so we don't need to mock the persistence layer.

Asyncio note for ``test_concurrent_acquire_only_one_wins``: SQLite
serialises writers via the store's threading lock, and inside a single
event loop two ``await`` points on synchronous ``store.get`` /
``store.compare_and_set`` calls don't truly race at the SQL layer.
The test still validates the CAS *contract* (exactly one winner; loser
returns False without exceptions), which is what we care about. Real
multi-process races are exercised by the store's own CAS tests and by
production deployment, not by this test.

We don't depend on ``pytest-asyncio``: tests are plain sync functions
that drive the async ``acquire_lease`` via :func:`tests.helpers.run`
(``asyncio.run``). This matches the rest of the test suite's
convention.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.reflection_jobs import acquire_lease
from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex
from tests.helpers import run


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """Fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "reflection_jobs_lease_test.db"
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
    project_name: str = "demo",
    status: str = "pending",
    source: str = "user",
    lease_owner: str | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
) -> ReflectionJob:
    return ReflectionJob(
        project_name=project_name,
        project_root="/tmp/" + project_name,
        status=status,
        source=source,
        lease_owner=lease_owner,
        lease_until=lease_until,
        attempt_count=attempt_count,
    )


# ---- happy path ----------------------------------------------------------


def test_acquire_from_pending_succeeds(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.1, 4.4, 4.5 (pending -> processing)."""
    job = _make_job(status="pending")
    store.save(job)

    before = datetime.now(timezone.utc)
    ok = run(acquire_lease(store, job.id, owner="worker-1"))
    after = datetime.now(timezone.utc)

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "processing"
    assert refreshed.lease_owner == "worker-1"
    assert refreshed.attempt_count == 1
    # lease_until should land in [before+300s, after+300s].
    assert refreshed.lease_until is not None
    assert before + timedelta(seconds=300) <= refreshed.lease_until
    assert refreshed.lease_until <= after + timedelta(seconds=300)


def test_acquire_from_retryable_succeeds(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.1, 4.5 (retryable -> processing, attempt++)."""
    job = _make_job(status="retryable", attempt_count=2)
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="worker-2"))

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "processing"
    assert refreshed.lease_owner == "worker-2"
    assert refreshed.attempt_count == 3


# ---- rejection paths -----------------------------------------------------


def test_acquire_when_processing_with_active_lease_returns_false(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.1, 4.7 (live lease is off-limits)."""
    future = datetime.now(timezone.utc) + timedelta(seconds=600)
    job = _make_job(
        status="processing",
        lease_owner="incumbent",
        lease_until=future,
        attempt_count=1,
    )
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="intruder"))

    assert ok is False
    refreshed = store.get(job.id)
    assert refreshed is not None
    # Nothing mutated.
    assert refreshed.lease_owner == "incumbent"
    assert refreshed.attempt_count == 1


def test_acquire_unknown_job_returns_false(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.7 (unknown job is a normal False, not an error)."""
    ok = run(acquire_lease(store, "no-such-id", owner="worker-1"))
    assert ok is False


# ---- expiry recovery -----------------------------------------------------


def test_acquire_recovers_expired_lease(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.2, 4.3 (expired -> re-acquired by new owner)."""
    past = datetime.now(timezone.utc) - timedelta(seconds=60)
    job = _make_job(
        status="processing",
        lease_owner="dead-worker",
        lease_until=past,
        attempt_count=1,
    )
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="new-worker"))

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "processing"
    assert refreshed.lease_owner == "new-worker"
    assert refreshed.attempt_count == 2
    # The old owner is gone — the row is now exclusively the new worker's.
    assert refreshed.lease_owner != "dead-worker"


# ---- max retries ---------------------------------------------------------


def test_acquire_at_max_retries_marks_failed(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.8 (attempt_count == max -> failed)."""
    job = _make_job(status="retryable", attempt_count=5)
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="worker-1", max_retries=5))

    assert ok is False
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error is not None
    assert "max_retries" in refreshed.error
    # Lease ownership is cleared so the failed row is unambiguous.
    assert refreshed.lease_owner is None


def test_acquire_below_max_retries_succeeds(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.8 (attempt_count < max still acquires)."""
    job = _make_job(status="retryable", attempt_count=4)
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="worker-1", max_retries=5))

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "processing"
    assert refreshed.attempt_count == 5
    assert refreshed.lease_owner == "worker-1"


def test_custom_max_retries_respected(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.8 (max_retries is a parameter, not a constant)."""
    job = _make_job(status="retryable", attempt_count=2)
    store.save(job)

    ok = run(acquire_lease(store, job.id, owner="worker-1", max_retries=2))

    assert ok is False
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error is not None
    assert "max_retries" in refreshed.error


# ---- concurrent acquisition (Property P3 / Req 4.6, 4.7) ----------------


def test_concurrent_acquire_only_one_wins(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.6, 4.7 (CAS mutual exclusion).

    See module docstring re: SQLite serialisation. The point of this
    test is to confirm the acquire_lease contract: exactly one of two
    concurrent calls succeeds, the other returns False without raising,
    and attempt_count ends at 1 (NOT 2 — the loser must not have
    incremented anything).
    """
    job = _make_job(status="pending")
    store.save(job)

    async def race() -> list[bool]:
        return await asyncio.gather(
            acquire_lease(store, job.id, owner="worker-A"),
            acquire_lease(store, job.id, owner="worker-B"),
        )

    results = run(race())

    # Exactly one winner.
    assert sorted(results) == [False, True]

    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "processing"
    assert refreshed.lease_owner in {"worker-A", "worker-B"}
    # The loser must NOT have bumped attempt_count.
    assert refreshed.attempt_count == 1


def test_acquire_does_not_raise_when_store_compare_and_set_returns_false(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.7 (failed CAS surfaces as False, not exception).

    We reproduce the failure mode by pre-acquiring the lease; a second
    acquire on the now-processing-with-live-lease job must return False
    without raising. This is the routine "lost the race" path in
    production.
    """
    job = _make_job(status="pending")
    store.save(job)

    # First acquire wins.
    first = run(acquire_lease(store, job.id, owner="worker-1"))
    assert first is True

    # A second acquire on the same (now-processing, live-lease) job
    # is ineligible and returns False without raising.
    second = run(acquire_lease(store, job.id, owner="worker-2"))
    assert second is False


# ---- lease window --------------------------------------------------------


def test_lease_until_is_in_future_after_acquire(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.4 (lease_until ≈ now + duration)."""
    job = _make_job(status="pending")
    store.save(job)

    before = datetime.now(timezone.utc)
    ok = run(acquire_lease(store, job.id, owner="worker-1", duration_seconds=300))
    after = datetime.now(timezone.utc)

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.lease_until is not None
    assert refreshed.lease_until > datetime.now(timezone.utc)
    # lease_until should land within [before+300, after+300] — wall-clock
    # jitter window, well under the 5-second tolerance budget.
    assert before + timedelta(seconds=300) <= refreshed.lease_until
    assert refreshed.lease_until <= after + timedelta(seconds=300)


def test_custom_duration_seconds_respected(store: ReflectionJobStore) -> None:
    """Validates: Requirements 4.4 (duration_seconds is a parameter)."""
    job = _make_job(status="pending")
    store.save(job)

    before = datetime.now(timezone.utc)
    ok = run(acquire_lease(store, job.id, owner="worker-1", duration_seconds=60))
    after = datetime.now(timezone.utc)

    assert ok is True
    refreshed = store.get(job.id)
    assert refreshed is not None
    assert refreshed.lease_until is not None
    assert before + timedelta(seconds=60) <= refreshed.lease_until
    assert refreshed.lease_until <= after + timedelta(seconds=60)
