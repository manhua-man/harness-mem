"""Integration tests for :func:`reflection_once` (Req 5, 6, 9, 10).

These tests drive the v2.4.0 business command end-to-end against a real
``ReflectionJobStore`` backed by a temp-file SQLite. They exercise the
ordered behavior contract documented in the function's docstring:
project resolution, idempotency lookup, terminal+trigger guard, default
defer-to-agent shortcut, job-store unavailability handling, and the
candidate-only side-effects boundary.

The autouse ``data_dir`` fixture in :mod:`tests.conftest` keeps any
incidental writes scoped to ``tmp_path`` so we never touch
``~/.harness-mem/``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands.reflection_jobs import (
    compute_idempotency_key,
    reflection_once,
)
from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex
from tests.helpers import run


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """Fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "reflection_once_test.db"
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


# Tables we count to validate "zero side effects when off" / "failure
# preserves unrelated data". Limited to the candidate-layer surfaces
# reflection_once is allowed to touch (per Req 9.1) plus observations.
_CANDIDATE_TABLES = ("memory_entries", "rule_candidates", "observations")


def _row_counts(index: SQLiteIndex, tables: tuple[str, ...]) -> dict[str, int]:
    """Return row counts for the requested tables.

    Skips any table that doesn't exist in the schema — keeps the test
    forward-compatible if the surface set evolves.
    """
    conn = index._conn_write()
    counts: dict[str, int] = {}
    with index._lock:
        for table in tables:
            existing = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if existing is None:
                continue
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            counts[table] = int(row["c"])
    return counts


def _insert_unrelated_memory_entry(index: SQLiteIndex) -> str:
    """Insert a sentinel ``memory_entries`` row and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    entry_id = "sentinel-entry-1"
    conn = index._conn_write()
    with index._lock:
        conn.execute(
            "INSERT INTO memory_entries "
            "(id, project_name, category, content, source, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                "demo",
                "architecture",
                "unrelated sentinel content",
                "manual",
                now,
                now,
            ),
        )
        conn.commit()
    return entry_id


def _read_memory_entry_content(index: SQLiteIndex, entry_id: str) -> str | None:
    conn = index._conn_write()
    with index._lock:
        row = conn.execute(
            "SELECT content FROM memory_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    return row["content"] if row else None


# ---- tests ---------------------------------------------------------------


def test_default_config_returns_needs_distill(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 6.2, 9.1, 9.3.

    Default config (``{}``) implies ``distill.mode = defer_to_agent``
    per the v2.4.0 default — reflection_once should create the job,
    drive it through pending → processing → needs_distill, and report
    zero candidates / zero observations written.
    """
    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-A",
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    assert result.created is True
    assert result.status == "needs_distill"
    assert result.candidates_written == 0
    assert result.observations_written == 0
    assert result.job.status == "needs_distill"

    # Persistence confirms the job hit the store with the terminal-ish
    # status we returned (Req 5.2 idempotency relies on this row).
    persisted = store.get(result.job.id)
    assert persisted is not None
    assert persisted.status == "needs_distill"
    assert persisted.completed_at is not None


def test_explicit_defer_to_agent_within_500ms(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 6.2 (defer path completes < 500 ms)."""
    config = {"distill": {"mode": "defer_to_agent"}}

    start = time.perf_counter()
    result = run(
        reflection_once(
            project_name="demo",
            config=config,
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-B",
            project_root="/tmp/demo",
            job_store=store,
        )
    )
    elapsed = time.perf_counter() - start

    assert result.status == "needs_distill"
    assert result.created is True
    # 500ms budget per Req 6.2; in practice this lands well under that.
    assert elapsed < 0.5, f"defer path took {elapsed:.3f}s, exceeds 500ms budget"


def test_project_root_defaults_to_known_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirement 5.4 known-root resolution before cwd fallback."""
    workspace = tmp_path / "workspace"
    project_root = workspace / "demo"
    project_root.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-root-known",
            project_root=None,
            job_store=store,
        )
    )

    assert result.created is True
    assert result.job.project_root == str(project_root)


def test_project_root_defaults_to_cwd_when_no_known_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirement 5.4 cwd remains the final fallback."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    result = run(
        reflection_once(
            project_name="missing-project",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-root-cwd",
            project_root=None,
            job_store=store,
        )
    )

    assert result.created is True
    assert result.job.project_root == str(workspace)


def test_idempotent_repeat_returns_existing_in_flight(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 5.2 (non-terminal idempotency match).

    An in-flight ``processing`` job with the same idempotency key
    short-circuits reflection_once: returns ``created=False`` and the
    caller-facing status maps to ``retryable`` (poll/wait).
    """
    project_name = "demo"
    source = "agent"
    session_ids = ["s1", "s2"]
    trigger_id = "trigger-C"
    key = compute_idempotency_key(
        project_name=project_name,
        source=source,
        phase="ingest",
        session_ids=session_ids,
        trigger_id=trigger_id,
    )

    # Pre-seed an in-flight job with that key.
    seeded = ReflectionJob(
        project_name=project_name,
        project_root="/tmp/demo",
        source=source,
        status="processing",
        phase="ingest",
        lease_owner="prior-worker",
        idempotency_key=key,
        input_refs=[trigger_id],
    )
    store.save(seeded)

    result = run(
        reflection_once(
            project_name=project_name,
            config={},
            source=source,
            session_ids=session_ids,
            trigger_id=trigger_id,
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    assert result.created is False
    assert result.status == "retryable"  # processing maps to retryable
    assert result.job.id == seeded.id
    assert result.candidates_written == 0
    assert result.observations_written == 0


def test_terminal_same_trigger_returns_existing(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 5.3 (terminal + same trigger → existing job).

    A completed job with the same idempotency key AND same trigger_id
    means "this exact request already finished" — return the terminal
    job, don't create a duplicate.
    """
    project_name = "demo"
    source = "user"
    session_ids = ["s1"]
    trigger_id = "trigger-D"
    key = compute_idempotency_key(
        project_name=project_name,
        source=source,
        phase="ingest",
        session_ids=session_ids,
        trigger_id=trigger_id,
    )

    seeded = ReflectionJob(
        project_name=project_name,
        project_root="/tmp/demo",
        source=source,
        status="completed",
        phase="done",
        idempotency_key=key,
        # By convention input_refs[0] holds the trigger_id (Req 5.3).
        input_refs=[trigger_id],
        completed_at=datetime.now(timezone.utc),
    )
    store.save(seeded)

    result = run(
        reflection_once(
            project_name=project_name,
            config={},
            source=source,
            session_ids=session_ids,
            trigger_id=trigger_id,
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    assert result.created is False
    assert result.job.id == seeded.id
    assert result.status == "completed"


def test_terminal_different_trigger_creates_new(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 5.3 (terminal + new trigger_id → new job).

    Same project / source / session_ids but a fresh trigger_id means
    the caller is intentionally re-running. Even though a terminal
    record exists, we mint a new job. (Different trigger_id → different
    idempotency key, so this exercises the no-prior-row path through
    the terminal guard.)
    """
    project_name = "demo"
    source = "user"
    session_ids = ["s1"]
    old_trigger = "trigger-E-old"
    new_trigger = "trigger-E-new"

    old_key = compute_idempotency_key(
        project_name=project_name,
        source=source,
        phase="ingest",
        session_ids=session_ids,
        trigger_id=old_trigger,
    )

    seeded = ReflectionJob(
        project_name=project_name,
        project_root="/tmp/demo",
        source=source,
        status="completed",
        phase="done",
        idempotency_key=old_key,
        input_refs=[old_trigger],
        completed_at=datetime.now(timezone.utc),
    )
    store.save(seeded)

    result = run(
        reflection_once(
            project_name=project_name,
            config={},
            source=source,
            session_ids=session_ids,
            trigger_id=new_trigger,
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    assert result.created is True
    assert result.job.id != seeded.id
    # New job took the defer-to-agent path → needs_distill.
    assert result.status == "needs_distill"


def test_job_store_none_returns_failed_synthetic() -> None:
    """Validates: Requirements 10.5, 10.7 (job_store=None never raises).

    Missing store yields a synthetic failure result carrying
    ``error="job_store_unavailable"`` so the caller can degrade
    gracefully instead of crashing.
    """
    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-F",
            project_root="/tmp/demo",
            job_store=None,
        )
    )

    assert result.status == "failed"
    assert result.created is False
    assert result.candidates_written == 0
    assert result.observations_written == 0
    assert result.job.status == "failed"
    assert result.job.error == "job_store_unavailable"


def test_zero_side_effects_when_off(
    index: SQLiteIndex,
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 9.1, 10.1, 10.6.

    Default config in v2.4.0 must not write to memory_entries,
    rule_candidates, or observations — reflection_once is candidate-
    only and the default path produces zero candidates.
    """
    before = _row_counts(index, _CANDIDATE_TABLES)

    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-G",
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    after = _row_counts(index, _CANDIDATE_TABLES)

    assert result.status == "needs_distill"
    # Each candidate-layer table must be byte-identical in row count.
    for table in before:
        assert after.get(table) == before[table], (
            f"reflection_once dirtied {table}: {before[table]} -> "
            f"{after.get(table)}"
        )


def test_failure_preserves_unrelated_data(
    index: SQLiteIndex,
) -> None:
    """Validates: Requirements 10.7 (failure preserves unrelated data).

    Inserts a sentinel ``memory_entries`` row, forces a failure via
    ``job_store=None``, then asserts the sentinel is unchanged.
    Demonstrates that the synthetic-failure path never reaches into
    the database.
    """
    entry_id = _insert_unrelated_memory_entry(index)
    original_content = _read_memory_entry_content(index, entry_id)
    assert original_content == "unrelated sentinel content"

    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-H",
            project_root="/tmp/demo",
            job_store=None,
        )
    )

    assert result.status == "failed"
    # Sentinel row is untouched by the failed call.
    final_content = _read_memory_entry_content(index, entry_id)
    assert final_content == original_content
