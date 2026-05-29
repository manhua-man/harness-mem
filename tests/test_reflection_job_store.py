"""Storage tests for :class:`ReflectionJobStore` (Req 2.x / 4.6 / 10.4).

These tests exercise the full CRUD-ish surface plus the lease-style
``compare_and_set`` path. They use the ``tmp_path`` fixture (per project
rules: no writes to ``~/.harness-mem/``) and the autouse ``data_dir``
fixture in :mod:`tests.conftest` keeps incidental writes scoped to the
temp directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """A fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "reflection_jobs_test.db"
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
    kind: str = "reflection",
    phase: str = "ingest",
    source: str = "user",
    created_at: datetime | None = None,
    idempotency_key: str | None = None,
    lease_owner: str | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
    output_candidate_ids: list[str] | None = None,
) -> ReflectionJob:
    """Build a ReflectionJob with sensible defaults for tests."""
    kwargs: dict = {
        "project_name": project_name,
        "project_root": "/tmp/" + project_name,
        "status": status,
        "kind": kind,
        "phase": phase,
        "source": source,
        "lease_owner": lease_owner,
        "lease_until": lease_until,
        "attempt_count": attempt_count,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
        kwargs["updated_at"] = created_at
    if output_candidate_ids is not None:
        kwargs["output_candidate_ids"] = output_candidate_ids
    if idempotency_key is not None:
        # extra="allow" lets us stash this on model_extra;
        # ReflectionJobStore.save reads it from there.
        kwargs["idempotency_key"] = idempotency_key
    return ReflectionJob(**kwargs)


# ---- save / get round-trip ----------------------------------------------


def test_save_then_get_round_trip_preserves_all_fields(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 2.3, 2.4 (round-trip)."""
    base = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    original = _make_job(
        project_name="round-trip",
        status="processing",
        phase="prepare",
        source="agent",
        created_at=base,
        lease_owner="worker-7",
        lease_until=base + timedelta(seconds=300),
        attempt_count=2,
        output_candidate_ids=["cand-a", "cand-b"],
    )
    original_id = original.id

    store.save(original)
    restored = store.get(original_id)

    assert restored is not None
    assert restored.id == original_id
    assert restored.project_name == "round-trip"
    assert restored.status == "processing"
    assert restored.phase == "prepare"
    assert restored.source == "agent"
    assert restored.lease_owner == "worker-7"
    assert restored.lease_until == base + timedelta(seconds=300)
    assert restored.attempt_count == 2
    assert restored.output_candidate_ids == ["cand-a", "cand-b"]
    assert restored.created_at == base
    # save() bumps updated_at to now() — we just check it's >= base.
    assert restored.updated_at >= base


def test_save_twice_with_same_id_keeps_one_row_with_latest_values(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 2.3 (upsert semantics)."""
    job = _make_job(project_name="upsert-target", status="pending")

    store.save(job)
    job.status = "processing"
    job.lease_owner = "worker-1"
    store.save(job)

    # Exactly one row by id.
    conn = index._conn_write()
    rows = conn.execute(
        "SELECT id, status, lease_owner FROM reflection_jobs WHERE id = ?",
        (job.id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "processing"
    assert rows[0]["lease_owner"] == "worker-1"

    # And get() reflects the latest values.
    fetched = store.get(job.id)
    assert fetched is not None
    assert fetched.status == "processing"
    assert fetched.lease_owner == "worker-1"


def test_get_unknown_id_returns_none(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.5."""
    assert store.get("nope-not-a-real-id") is None


# ---- list filters --------------------------------------------------------


def test_list_filters_by_project_name(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (project_name filter)."""
    a = _make_job(project_name="alpha")
    b = _make_job(project_name="beta")
    store.save(a)
    store.save(b)

    listed = store.list(project_name="alpha")
    assert {j.id for j in listed} == {a.id}


def test_list_filters_by_status(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (status filter)."""
    pending = _make_job(status="pending")
    processing = _make_job(status="processing")
    store.save(pending)
    store.save(processing)

    listed = store.list(status="processing")
    assert {j.id for j in listed} == {processing.id}


def test_list_filters_by_kind(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (kind filter).

    Only one ``kind`` is currently legal in the schema (``reflection``)
    so we just confirm the filter passes through to SQL — selecting an
    unrelated kind returns no rows.
    """
    job = _make_job(kind="reflection")
    store.save(job)

    assert store.list(kind="reflection") == [job] or [
        j.id for j in store.list(kind="reflection")
    ] == [job.id]
    assert store.list(kind="something-else") == []


def test_list_combined_filters(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (combined filter AND semantics)."""
    a = _make_job(project_name="alpha", status="pending")
    b = _make_job(project_name="alpha", status="processing")
    c = _make_job(project_name="beta", status="processing")
    for job in (a, b, c):
        store.save(job)

    listed = store.list(project_name="alpha", status="processing")
    assert {j.id for j in listed} == {b.id}


def test_list_orders_by_created_at_desc(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (ordering)."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    older = _make_job(project_name="ord", created_at=base)
    middle = _make_job(project_name="ord", created_at=base + timedelta(hours=1))
    newer = _make_job(project_name="ord", created_at=base + timedelta(hours=2))
    # Save in non-monotonic order to confirm ORDER BY is doing the work.
    store.save(middle)
    store.save(older)
    store.save(newer)

    listed = store.list(project_name="ord")
    assert [j.id for j in listed] == [newer.id, middle.id, older.id]


def test_list_no_matches_returns_empty(store: ReflectionJobStore) -> None:
    """Validates: Requirements 2.6 (empty result is a list, not an error)."""
    assert store.list(project_name="never-saved") == []


# ---- compare_and_set -----------------------------------------------------


def test_compare_and_set_succeeds_when_status_and_lease_owner_match(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.6 (happy path CAS)."""
    job = _make_job(status="pending", lease_owner=None)
    store.save(job)

    ok = store.compare_and_set(
        job_id=job.id,
        expected_status="pending",
        expected_lease_owner=None,
        updates={
            "status": "processing",
            "lease_owner": "worker-1",
            "attempt_count": 1,
        },
    )

    assert ok is True
    after = store.get(job.id)
    assert after is not None
    assert after.status == "processing"
    assert after.lease_owner == "worker-1"
    assert after.attempt_count == 1


def test_compare_and_set_fails_when_status_mismatches_and_leaves_row_unchanged(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 4.6 (status guard)."""
    job = _make_job(status="processing", lease_owner=None)
    store.save(job)

    ok = store.compare_and_set(
        job_id=job.id,
        expected_status="pending",
        expected_lease_owner=None,
        updates={"status": "processing", "lease_owner": "worker-x"},
    )

    assert ok is False
    after = store.get(job.id)
    assert after is not None
    assert after.status == "processing"
    assert after.lease_owner is None


@pytest.mark.parametrize(
    "stored_owner,expected_owner",
    [
        (None, "worker-x"),  # row says None, caller expected "worker-x"
        ("worker-x", None),  # row says "worker-x", caller expected None
        ("worker-x", "worker-y"),  # both set but different
    ],
)
def test_compare_and_set_fails_on_lease_owner_mismatch(
    store: ReflectionJobStore, stored_owner: str | None, expected_owner: str | None
) -> None:
    """Validates: Requirements 4.6 (lease_owner guard, three branches)."""
    job = _make_job(status="processing", lease_owner=stored_owner)
    store.save(job)

    ok = store.compare_and_set(
        job_id=job.id,
        expected_status="processing",
        expected_lease_owner=expected_owner,
        updates={"lease_owner": "winner"},
    )

    assert ok is False
    after = store.get(job.id)
    assert after is not None
    assert after.lease_owner == stored_owner  # unchanged


def test_compare_and_set_keeps_data_blob_in_sync_with_index_columns(
    store: ReflectionJobStore, index: SQLiteIndex
) -> None:
    """Validates: Requirements 4.6 (data blob + index column coherency).

    After a successful CAS the JSON blob in ``data`` MUST reflect the
    same values we wrote to the index columns. Otherwise list/get would
    return stale fields and the lease state machine would lie to
    callers.
    """
    job = _make_job(status="pending", lease_owner=None, attempt_count=0)
    store.save(job)

    ok = store.compare_and_set(
        job_id=job.id,
        expected_status="pending",
        expected_lease_owner=None,
        updates={
            "status": "processing",
            "lease_owner": "worker-9",
            "attempt_count": 4,
        },
    )
    assert ok is True

    conn = index._conn_write()
    row = conn.execute(
        "SELECT status, lease_owner, attempt_count, data "
        "FROM reflection_jobs WHERE id = ?",
        (job.id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "processing"
    assert row["lease_owner"] == "worker-9"
    assert row["attempt_count"] == 4

    blob = json.loads(row["data"])
    assert blob["status"] == "processing"
    assert blob["lease_owner"] == "worker-9"
    assert blob["attempt_count"] == 4

    # And the high-level get() round-trips the same values via from_dict.
    refetched = store.get(job.id)
    assert refetched is not None
    assert refetched.status == "processing"
    assert refetched.lease_owner == "worker-9"
    assert refetched.attempt_count == 4


# ---- find_by_idempotency_key --------------------------------------------


def test_find_by_idempotency_key_returns_latest_non_terminal_match(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 5.x (idempotency lookup picks latest live job)."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    older = _make_job(
        project_name="idem",
        status="pending",
        idempotency_key="key-A",
        created_at=base,
    )
    newer = _make_job(
        project_name="idem",
        status="processing",
        idempotency_key="key-A",
        created_at=base + timedelta(hours=1),
    )
    other = _make_job(
        project_name="idem",
        status="pending",
        idempotency_key="key-B",
        created_at=base + timedelta(hours=2),
    )
    for job in (older, newer, other):
        store.save(job)

    found = store.find_by_idempotency_key("key-A")
    assert found is not None
    assert found.id == newer.id


def test_find_by_idempotency_key_skips_terminal_rows(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 5.3 (terminal rows are not 'live')."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    completed = _make_job(
        project_name="idem-term",
        status="completed",
        idempotency_key="key-term",
        created_at=base,
    )
    failed = _make_job(
        project_name="idem-term",
        status="failed",
        idempotency_key="key-term",
        created_at=base + timedelta(minutes=1),
    )
    for job in (completed, failed):
        store.save(job)

    assert store.find_by_idempotency_key("key-term") is None


# ---- coexistence (Req 2.7 / 10.4) ---------------------------------------


def test_store_does_not_break_other_tables(tmp_path: Path) -> None:
    """Validates: Requirements 2.7, 10.4 (coexistence with existing schemas).

    Spinning up a SQLiteIndex + ReflectionJobStore on a fresh DB must
    leave the pre-existing tables created by ``init_db`` intact and
    queryable.
    """
    db_path = tmp_path / "coexist.db"
    sqldb = SQLiteIndex(db_path)
    try:
        sqldb.init_db()
        # Build a store. This is a no-op for table creation (we rely on
        # the index's own _TABLE_SCHEMAS) but the assertion is "wiring
        # the store up doesn't drop or alter anything".
        ReflectionJobStore(sqldb)

        conn = sqldb._conn_write()
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        # The new table is present.
        assert "reflection_jobs" in names
        # And at least one pre-existing core table was NOT dropped.
        assert "memory_entries" in names
        assert "observations" in names

        # Sanity: writing into the existing tables still works after
        # touching the reflection_jobs surface.
        now = datetime.now(timezone.utc).isoformat()
        sqldb.insert(
            "memory_entries",
            {
                "id": "coexist-entry",
                "project_name": "coexist",
                "category": "note",
                "content": "still works",
                "confidence": 0.9,
                "source": "test",
                "created_at": now,
                "updated_at": now,
                "tags": "[]",
            },
        )
        assert sqldb.get("memory_entries", "coexist-entry") is not None
    finally:
        sqldb.close()
