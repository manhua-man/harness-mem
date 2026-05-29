"""Interruption-safety tests for the host entry (v2.4.1 Task 6, Req 6.1-6.6).

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**

The host entry registers no signal handlers (Req 6.6): interruption is observed
*solely* through persisted ``reflection_jobs`` state, recovered on the next
invocation via v2.4.0 expired-lease re-acquisition (``acquire_lease``). These
tests pin that contract.

Why we simulate the crash STATE instead of racing a real SIGTERM: the v2.4.0
default ``defer_to_agent`` path completes in well under a millisecond, so a
real "kill the process mid-reflection" race is not achievable deterministically
on any platform (doubly so on Windows where POSIX ``SIGTERM`` is not delivered
the same way). The deterministic guarantee for Req 6.1/6.2/6.5 is asserted
directly against the SAME lease primitives the real recovery path uses.

Subprocess data-dir redirect: subprocess invocations set ``HOME`` *and*
``USERPROFILE`` to a tmp dir so the child's ``DEFAULT_DATA_DIR`` (bound at
import time from ``Path.home()``) lands under that tmp dir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import harness_mem.host_entry as host_entry_pkg
from harness_mem.commands.reflection_jobs import acquire_lease
from harness_mem.core.schemas import ReflectionJob
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from tests.helpers import run as run_async

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MAX_LEASE_SECONDS = 300
_MAX_RETRIES = 5


def _make_on_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "on"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return project_root, home, env


def _data_dir(home: Path) -> Path:
    return home / ".harness-mem" / "data"


def _run_host_entry(
    project_root: Path,
    env: dict[str, str],
    *,
    source: str = "ide_hook",
    trigger_id: str | None = None,
    session_ids: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [
        sys.executable,
        "-m",
        "harness_mem.host_entry",
        "--project-root",
        str(project_root),
        "--source",
        source,
    ]
    if trigger_id is not None:
        argv += ["--trigger-id", trigger_id]
    if session_ids:
        argv += ["--session-ids", *session_ids]
    return subprocess.run(
        argv,
        env=env,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _list_jobs(data_dir: Path) -> list[ReflectionJob]:
    if not data_dir.exists():
        return []
    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        return backend.reflection_job_store.list(limit=1000)
    finally:
        run_async(backend.close())


def _seed_job(data_dir: Path, job: ReflectionJob) -> None:
    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        backend.reflection_job_store.save(job)
    finally:
        run_async(backend.close())


def _expire_lease(store: ReflectionJobStore, job_id: str) -> None:
    job = store.get(job_id)
    assert job is not None
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    ok = store.compare_and_set(
        job_id=job_id,
        expected_status=job.status,
        expected_lease_owner=job.lease_owner,
        updates={"lease_until": past},
    )
    assert ok, "failed to expire lease for recovery simulation"


def test_completed_subprocess_creates_recoverable_job(tmp_path: Path) -> None:
    project_root, home, env = _make_on_project(tmp_path)
    proc = _run_host_entry(project_root, env, trigger_id="baseline-1")
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["status"] == "needs_distill"
    jobs = _list_jobs(_data_dir(home))
    assert len(jobs) == 1
    assert jobs[0].status == "needs_distill"


def test_reinvoke_same_params_is_idempotent(tmp_path: Path) -> None:
    project_root, home, env = _make_on_project(tmp_path)
    first = _run_host_entry(
        project_root, env, trigger_id="dup-trigger", session_ids=["s1", "s2"]
    )
    second = _run_host_entry(
        project_root, env, trigger_id="dup-trigger", session_ids=["s1", "s2"]
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    jobs = _list_jobs(_data_dir(home))
    assert len(jobs) == 1, "identical re-invocation must not create a second row"
    assert json.loads(first.stdout)["job_id"] == json.loads(second.stdout)["job_id"]


def test_interrupted_subprocess_leaves_recoverable_or_terminal(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "crash-data"
    now = datetime.now(timezone.utc)
    crashed = ReflectionJob(
        project_name="repo",
        project_root=str(tmp_path / "repo"),
        source="ide_hook",
        status="processing",
        phase="ingest",
        lease_owner="dead-worker:9999",
        lease_until=now - timedelta(seconds=1),
        attempt_count=1,
    )
    _seed_job(data_dir, crashed)

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        store = backend.reflection_job_store
        persisted = store.get(crashed.id)
        assert persisted is not None
        recoverable = (
            persisted.status == "processing" and persisted.lease_until is not None
        )
        terminal_failed = persisted.status == "failed" and bool(persisted.error)
        assert recoverable or terminal_failed
        assert recoverable

        reacquired = run_async(
            acquire_lease(store, crashed.id, owner="recovery:1234")
        )
        assert reacquired is True
        after = store.get(crashed.id)
        assert after is not None
        assert after.attempt_count == 2
        assert after.status == "processing"
        assert after.lease_until is not None
    finally:
        run_async(backend.close())

    project_root, home, env = _make_on_project(tmp_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "harness_mem.host_entry",
            "--project-root",
            str(project_root),
            "--source",
            "ide_hook",
            "--trigger-id",
            "smoke-1",
        ],
        env=env,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        proc.wait(timeout=10)
    assert proc.poll() is not None

    for job in _list_jobs(_data_dir(home)):
        if job.status == "processing":
            assert job.lease_until is not None


def test_no_infinite_lease_after_acquire(tmp_path: Path) -> None:
    data_dir = tmp_path / "lease-data"
    pending = ReflectionJob(
        project_name="repo",
        project_root=str(tmp_path / "repo"),
        source="ide_hook",
        status="pending",
        phase="ingest",
        attempt_count=0,
    )
    _seed_job(data_dir, pending)

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        store = backend.reflection_job_store
        acquired = run_async(acquire_lease(store, pending.id, owner="worker:1"))
        assert acquired is True
        refreshed = store.get(pending.id)
        assert refreshed is not None
        now = datetime.now(timezone.utc)
        assert refreshed.lease_until is not None
        assert refreshed.lease_until > now
        assert refreshed.lease_until <= now + timedelta(
            seconds=_MAX_LEASE_SECONDS + 5
        )
    finally:
        run_async(backend.close())


def test_recovery_increments_attempt_count_and_bounds_via_max_retries(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "retry-data"
    job = ReflectionJob(
        project_name="repo",
        project_root=str(tmp_path / "repo"),
        source="ide_hook",
        status="pending",
        phase="ingest",
        attempt_count=0,
    )
    _seed_job(data_dir, job)

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        store = backend.reflection_job_store
        acquired = run_async(acquire_lease(store, job.id, owner="recovery"))
        assert acquired is True
        assert store.get(job.id).attempt_count == 1  # type: ignore[union-attr]

        for expected in range(2, _MAX_RETRIES + 1):
            _expire_lease(store, job.id)
            acquired = run_async(acquire_lease(store, job.id, owner="recovery"))
            assert acquired is True, f"cycle to attempt {expected} should acquire"
            current = store.get(job.id)
            assert current is not None
            assert current.attempt_count == expected

        _expire_lease(store, job.id)
        acquired = run_async(acquire_lease(store, job.id, owner="recovery"))
        assert acquired is False
        final = store.get(job.id)
        assert final is not None
        assert final.status == "failed"
        assert final.error is not None and "max_retries" in final.error
    finally:
        run_async(backend.close())


def test_pre_reflection_termination_leaves_no_rows(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness_mem.host_entry",
            "--project-root",
            "relative/not-absolute",
            "--source",
            "ide_hook",
        ],
        env=env,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stderr
    assert proc.stdout == ""
    assert not _data_dir(home).exists()
    assert _list_jobs(_data_dir(home)) == []


def test_host_entry_registers_no_signal_handlers() -> None:
    pkg_dir = Path(host_entry_pkg.__file__).parent
    py_files = sorted(pkg_dir.glob("*.py"))
    assert py_files
    for source_file in py_files:
        src = source_file.read_text(encoding="utf-8")
        assert "import signal" not in src, (
            f"{source_file.name} imports signal (Req 6.6 forbids signal trapping)"
        )
        assert "signal.signal(" not in src, (
            f"{source_file.name} registers a signal handler (Req 6.6 violation)"
        )
