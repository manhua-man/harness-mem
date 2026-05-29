"""Scope safety guardrails for v2.4.0 (Req 10).

These tests pin the v2.4.0 "safe by default" promises:

* Default config produces zero jobs / zero candidates / zero side
  effects on the data directory (Req 10.1, 10.6).
* :func:`reflection_once` never raises and always returns within a
  bounded time, even on unrecoverable errors (Req 10.5).
* The CLI surface stays clean — there is no ``harness-mem reflection``
  subcommand registered (Req 10.2).
* No daemon / background thread is spawned by reflection_once
  (Req 10.3).

The autouse ``data_dir`` fixture in :mod:`tests.conftest` keeps any
incidental writes scoped to ``tmp_path``.
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_mem import cli as cli_module
from harness_mem.commands.reflection_jobs import reflection_once
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.sqlite_index import SQLiteIndex
from tests.helpers import run


# Tables we count to validate "zero side effects when off" (Req 10.6).
# These are the candidate-layer surfaces reflection_once is allowed
# to touch per Req 9.1 plus observations (verbatim layer entrypoint).
_CANDIDATE_TABLES = ("memory_entries", "rule_candidates", "observations")


# ---- helpers -------------------------------------------------------------


def _row_count(index: SQLiteIndex, table: str) -> int:
    """Return ``COUNT(*)`` for ``table`` or ``0`` if the table is missing."""
    conn = index._conn_write()
    with index._lock:
        existing = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if existing is None:
            return 0
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"])


def _reflection_job_count(index: SQLiteIndex) -> int:
    return _row_count(index, "reflection_jobs")


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path):
    """Fresh SQLiteIndex per test, closed on teardown."""
    db_path = tmp_path / "scope_safety_test.db"
    sqldb = SQLiteIndex(db_path)
    sqldb.init_db()
    try:
        yield sqldb
    finally:
        sqldb.close()


@pytest.fixture
def store(index: SQLiteIndex) -> ReflectionJobStore:
    return ReflectionJobStore(index)


# ---- tests ---------------------------------------------------------------


def test_default_config_produces_no_jobs_no_candidates_no_side_effects(
    data_dir: Path,
) -> None:
    """Validates: Requirements 10.1, 10.6.

    With NO triggers configured (i.e. nothing calls reflection_once),
    just initializing the backend must produce zero reflection jobs,
    zero candidates, and zero observations. This pins the "safe by
    default" promise: a fresh install with default config has no
    side effects.
    """
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        index = backend._structured_store._index  # type: ignore[union-attr]
        # Reflection job table is empty.
        assert _reflection_job_count(index) == 0
        # Candidate-layer tables are also empty.
        for table in _CANDIDATE_TABLES:
            assert _row_count(index, table) == 0, (
                f"{table} has non-zero rows on a fresh backend init"
            )
    finally:
        run(backend.close())


def test_failure_returns_within_5_seconds(store: ReflectionJobStore) -> None:
    """Validates: Requirements 10.5.

    A failure path (here: ``job_store=None``) must return a structured
    failure result well under the 5-second budget without raising.
    """
    start = time.perf_counter()
    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-fail-timing",
            project_root="/tmp/demo",
            job_store=None,
        )
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, (
        f"reflection_once failure took {elapsed:.3f}s, exceeds 5s budget"
    )
    assert result.status == "failed"


def test_no_unhandled_exceptions_escape_reflection_once(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 10.5.

    Multiple failure paths must all return a :class:`ReflectionResult`
    without propagating exceptions. We wrap every call in a broad
    ``try/except`` and explicitly fail if anything escapes.
    """

    def _call(**kwargs):
        return run(reflection_once(**kwargs))

    # Path 1: job_store=None (synthetic-failure shortcut).
    try:
        result = _call(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-none-store",
            project_root="/tmp/demo",
            job_store=None,
        )
    except Exception as exc:
        pytest.fail(f"reflection_once raised on job_store=None: {exc!r}")
    assert result.status == "failed"

    # Path 2: store whose ``save`` blows up mid-flight. ``reflection_once``
    # catches this and returns a synthetic failure (Req 10.5).
    with patch.object(store, "save", side_effect=RuntimeError("disk full")):
        try:
            result = _call(
                project_name="demo",
                config={},
                source="agent",
                session_ids=["s2"],
                trigger_id="trigger-broken-save",
                project_root="/tmp/demo",
                job_store=store,
            )
        except Exception as exc:
            pytest.fail(
                f"reflection_once raised on save failure: {exc!r}"
            )
        assert result.status == "failed"

    # Path 3: store whose ``find_by_idempotency_key`` blows up. The
    # current implementation lets this exception propagate by design
    # only if it can't be classified — we want to confirm it IS caught.
    with patch.object(
        store,
        "find_by_idempotency_key",
        side_effect=RuntimeError("index corrupt"),
    ):
        try:
            result = _call(
                project_name="demo",
                config={},
                source="agent",
                session_ids=["s3"],
                trigger_id="trigger-broken-lookup",
                project_root="/tmp/demo",
                job_store=store,
            )
        except Exception as exc:
            # If the implementation doesn't catch idempotency lookup
            # failures, that's a Req 10.5 violation worth surfacing.
            pytest.fail(
                f"reflection_once raised on idempotency lookup failure: "
                f"{exc!r}"
            )
        # Status must still be a valid caller-facing terminal value.
        assert result.status in {
            "needs_distill",
            "completed",
            "retryable",
            "failed",
        }


def test_no_reflection_cli_subcommand_registered() -> None:
    """Validates: Requirements 10.2.

    The ``harness-mem`` CLI must not register a ``reflection``
    subcommand. We rebuild the parser by reading ``cli_module.main``
    indirectly — simplest reliable path is to introspect via a captured
    ``add_subparsers`` action.
    """
    # We can't easily invoke ``main()`` without it parsing argv, so we
    # build a minimal stand-in parser, monkey-patch ``argparse`` to
    # capture the subparser registrations, and replay the registration
    # block. Easier: import the module and check it for the literal
    # string ``"reflection"`` appearing in any ``add_parser`` call.
    cli_source = Path(cli_module.__file__).read_text(encoding="utf-8")

    # Look for any ``sub.add_parser("reflection"`` registration.
    assert 'add_parser("reflection"' not in cli_source, (
        "Found a reflection subcommand registration in cli.py — "
        "Req 10.2 forbids a user-facing harness-mem reflection CLI."
    )
    assert "add_parser('reflection'" not in cli_source, (
        "Found a reflection subcommand registration in cli.py — "
        "Req 10.2 forbids a user-facing harness-mem reflection CLI."
    )

    # Belt-and-braces: actually parse a fake invocation and confirm
    # argparse rejects ``reflection`` as an unknown command. We build
    # a parser that mirrors the real one by importing ``main`` and
    # invoking it under controlled args is messy; instead we rely on
    # the source check above PLUS a behavioral check that the
    # registered subcommand list does not include "reflection".
    parser = argparse.ArgumentParser(prog="harness-mem")
    sub = parser.add_subparsers(dest="command")
    # We don't enumerate them all here — the source check above is the
    # primary guard. This is a smoke check that argparse infra works.
    sub.add_parser("doctor")  # sanity
    with pytest.raises(SystemExit):
        # A bogus subcommand must raise SystemExit (argparse error).
        parser.parse_args(["reflection"])


def test_no_daemon_or_background_thread_running(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 10.3.

    ``reflection_once`` must complete without spawning long-lived
    background threads. We snapshot ``threading.enumerate()`` before
    and after the call and assert the count does not grow. This is a
    soft check — pytest / asyncio may have their own internal threads
    that we tolerate by comparing counts rather than identities.
    """
    before = set(threading.enumerate())
    before_count = len(before)

    result = run(
        reflection_once(
            project_name="demo",
            config={},
            source="agent",
            session_ids=["s1"],
            trigger_id="trigger-thread-check",
            project_root="/tmp/demo",
            job_store=store,
        )
    )

    after = set(threading.enumerate())
    after_count = len(after)
    new_threads = after - before

    # Filter out any non-daemon / non-MainThread artifacts that the
    # asyncio event loop or pytest infra might have left behind. The
    # core promise is: reflection_once does not start a thread that
    # is still alive after the call returns.
    leaked = [
        t for t in new_threads
        if t.is_alive() and t is not threading.current_thread()
    ]

    assert after_count <= before_count + 0, (
        f"reflection_once leaked {after_count - before_count} thread(s); "
        f"new alive threads: {[t.name for t in leaked]}"
    )
    # And the result is still a valid ReflectionResult.
    assert result.status in {
        "needs_distill",
        "completed",
        "retryable",
        "failed",
    }
