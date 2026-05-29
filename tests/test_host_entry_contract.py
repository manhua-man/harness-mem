"""Reflection-contract equivalence tests (v2.4.1 Task 5, Req 1).

Property 1 — Idempotency_Equivalence (Req 1.2, 1.3, 1.5): the host entry's
argv -> ``reflection_once`` parameter mapping does not perturb the v2.4.0
idempotency-key inputs. We compare the key the host entry actually persists
(``--config-override triggers.after_agent=on`` so reflection_once runs) against
the key ``compute_idempotency_key`` produces directly with the same logical
inputs.

project_name note: the host entry passes ``Path(project_root).name`` as the
project_name, so the direct key is computed with the tmp project dir basename.

Data-dir isolation: ``LocalMemoryBackend`` binds ``DEFAULT_DATA_DIR`` at import
time, so we monkeypatch
``harness_mem.storage.local_memory_backend.DEFAULT_DATA_DIR`` directly and
isolate ``Path.home`` for the user-level config lookup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.reflection_jobs import compute_idempotency_key
from harness_mem.host_entry.__main__ import build_parser, run
from tests.helpers import run as run_async


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


def _isolate(monkeypatch: pytest.MonkeyPatch, home: Path, data_dir: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import harness_mem.storage.local_memory_backend as lmb

    monkeypatch.setattr(lmb, "DEFAULT_DATA_DIR", data_dir)


def _open_store(data_dir: Path):
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    return backend


def _persisted_jobs(data_dir: Path):
    backend = _open_store(data_dir)
    try:
        return backend.reflection_job_store.list(limit=1000)
    finally:
        run_async(backend.close())


def _job_found_by_key(data_dir: Path, key: str) -> bool:
    """True iff the host entry's single persisted job is retrievable by ``key``.

    The idempotency_key is the DB index column, not a reliably round-tripped
    model field, so we prove ``k_host == key`` by querying the store with the
    directly-computed key and asserting it returns the one persisted job
    (``needs_distill`` is non-terminal, so ``find_by_idempotency_key`` returns
    it).
    """
    backend = _open_store(data_dir)
    try:
        jobs = backend.reflection_job_store.list(limit=1000)
        assert len(jobs) == 1, f"expected one job, found {len(jobs)}"
        found = backend.reflection_job_store.find_by_idempotency_key(key)
        return found is not None and found.id == jobs[0].id
    finally:
        run_async(backend.close())


@pytest.mark.parametrize(
    ("source", "session_ids", "trigger_id"),
    [
        ("ide_hook", ["s1"], "t-1"),
        ("scheduler", ["s1", "s2"], "t-2"),
        ("agent", [], None),
        ("user", ["only"], "trig"),
        ("ide_hook", ["b", "a", "c"], "ordered"),
    ],
)
def test_idempotency_equivalence_host_vs_direct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    session_ids: list[str],
    trigger_id: str | None,
) -> None:
    """Validates: Requirements 1.2 — host-entry key == direct compute key."""
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "on"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)

    argv = ["--project-root", str(project_root), "--source", source]
    if trigger_id is not None:
        argv += ["--trigger-id", trigger_id]
    if session_ids:
        argv += ["--session-ids", *session_ids]
    args = _parse(argv)
    exit_code, _ = run_async(run(args))
    assert exit_code == 0

    k_direct = compute_idempotency_key(
        project_name=project_root.name,
        source=source,
        phase="ingest",
        session_ids=session_ids,
        trigger_id=trigger_id,
    )
    assert _job_found_by_key(data_dir, k_direct)


def test_session_id_cli_order_collapses_to_one_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 1.5 — session-id ordering does not split the job."""
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "on"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)

    base = ["--project-root", str(project_root), "--source", "ide_hook", "--trigger-id", "t"]
    run_async(run(_parse(base + ["--session-ids", "a", "b", "c"])))
    run_async(run(_parse(base + ["--session-ids", "c", "b", "a"])))

    # Different CLI order, same multiset → same idempotency key → one row.
    assert len(_persisted_jobs(data_dir)) == 1


def test_identical_reinvocation_creates_one_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 1.3 — identical params do not duplicate the job."""
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "on"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)

    argv = [
        "--project-root", str(project_root), "--source", "ide_hook",
        "--trigger-id", "same", "--session-ids", "s1",
    ]
    run_async(run(_parse(argv)))
    run_async(run(_parse(argv)))

    assert len(_persisted_jobs(data_dir)) == 1
