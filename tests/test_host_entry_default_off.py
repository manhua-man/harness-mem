"""Default-off scope-safety + worker.mode guard tests (v2.4.1 Task 5, Req 4).

MCP-handler symmetry note: v2.4.1 adds no new MCP tool. The in-process
``reflection_once`` direct call IS the MCP-equivalent baseline; the default-off
decision lives in the shared host_entry layer, gated solely on the resolved
``triggers.*`` from ``load_merged_config``. These tests pin that the gate is
driven by config (not by entry point) and that the off state produces zero
side effects.

Req 4.8 policy: the implemented policy is FAIL-LOUD — malformed project TOML
raises ``ConfigParseError`` which ``run()`` maps to exit 3 (CONFIG_LOAD_ERROR),
NOT a silent default-off skip. This still satisfies Req 4.8's safety intent
(zero job/candidate writes) and is strictly more conservative.

``LocalMemoryBackend`` binds ``DEFAULT_DATA_DIR`` from ``Path.home()`` at import
time, so monkeypatching ``Path.home`` alone does not redirect the data dir. The
tests monkeypatch ``harness_mem.storage.local_memory_backend.DEFAULT_DATA_DIR``
directly (and still isolate ``Path.home`` for the user-level config lookup).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from harness_mem.config.merge import MergedConfig
from harness_mem.host_entry.__main__ import build_parser, run
from tests.helpers import run as run_async

_CANDIDATE_TABLES = ("memory_entries", "rule_candidates", "observations")


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


def _isolate(monkeypatch: pytest.MonkeyPatch, home: Path, data_dir: Path) -> None:
    """Isolate both the user-config lookup (Path.home) and the data dir."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    import harness_mem.storage.local_memory_backend as lmb

    monkeypatch.setattr(lmb, "DEFAULT_DATA_DIR", data_dir)


def _patch_reflection_sentinel(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace reflection_once with a sentinel that flags if called."""
    called = {"hit": False}

    async def _boom(*a, **k):  # pragma: no cover - must never run
        called["hit"] = True
        raise AssertionError("reflection_once must not run in default-off path")

    import harness_mem.commands.reflection_jobs as rj

    monkeypatch.setattr(rj, "reflection_once", _boom)
    return called


# ---- Req 4.7: worker.mode default-off guard ------------------------------


def test_worker_mode_defaults_off() -> None:
    assert MergedConfig().worker_mode == "off"


# ---- Req 4.1, 4.2, 4.3, 4.5: default-off zero side effects ---------------


@pytest.mark.parametrize(
    "project_toml",
    [
        None,  # no project config file at all
        '[triggers]\nafter_agent = "off"\n',  # explicit off
        '[logging]\nlevel = "debug"\n',  # only unrelated extras
        '[triggers]\nafter_agent = "off"\nscheduler = "off"\n',  # both off
    ],
)
def test_default_off_skips_with_zero_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_toml: str | None
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    if project_toml is not None:
        (project_root / ".harness-mem.toml").write_text(project_toml, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)
    called = _patch_reflection_sentinel(monkeypatch)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))

    assert exit_code == 0
    assert payload is not None
    assert json.loads(payload)["status"] == "skipped_default_off"
    assert called["hit"] is False
    # Default-off returns before any backend is created → no data dir.
    assert not data_dir.exists()


def test_default_off_exits_within_two_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)
    _patch_reflection_sentinel(monkeypatch)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    start = time.perf_counter()
    exit_code, _ = run_async(run(args))
    elapsed = time.perf_counter() - start

    assert exit_code == 0
    assert elapsed < 2.0


def test_pre_existing_data_dir_untouched_on_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A populated data dir present before a default-off call is unchanged."""
    project_root = tmp_path / "repo"
    project_root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)

    # Build a backend + seed one reflection job, then close it.
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend
    from harness_mem.core.schemas import ReflectionJob

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        backend.reflection_job_store.save(
            ReflectionJob(
                project_name="repo",
                project_root=str(project_root),
                source="agent",
                status="needs_distill",
                phase="done",
            )
        )
        before = len(backend.reflection_job_store.list(limit=1000))
    finally:
        run_async(backend.close())

    _patch_reflection_sentinel(monkeypatch)
    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))
    assert exit_code == 0
    assert json.loads(payload)["status"] == "skipped_default_off"  # type: ignore[arg-type]

    backend2 = LocalMemoryBackend(data_dir)
    run_async(backend2.init())
    try:
        after = len(backend2.reflection_job_store.list(limit=1000))
    finally:
        run_async(backend2.close())
    assert after == before


# ---- Req 4.4: triggers.on actually runs reflection_once (symmetry) -------


def test_trigger_on_invokes_reflection_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        '[triggers]\nafter_agent = "on"\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))

    # Default distill mode → defer_to_agent → needs_distill, exit 0.
    assert exit_code == 0
    assert payload is not None
    assert json.loads(payload)["status"] == "needs_distill"
    # A job row was created (reflection_once actually ran).
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend

    backend = LocalMemoryBackend(data_dir)
    run_async(backend.init())
    try:
        assert len(backend.reflection_job_store.list(limit=1000)) == 1
    finally:
        run_async(backend.close())


# ---- Req 4.8: malformed project config → fail-loud exit 3 ----------------


def test_malformed_project_config_fails_loud_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / ".harness-mem.toml").write_text(
        "this is = = not valid toml\n", encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    _isolate(monkeypatch, home, data_dir)
    called = _patch_reflection_sentinel(monkeypatch)

    args = _parse(["--project-root", str(project_root), "--source", "ide_hook"])
    exit_code, payload = run_async(run(args))

    # Fail-loud policy: exit 3, no JSON, no reflection_once call, no data dir.
    assert exit_code == 3
    assert payload is None
    assert called["hit"] is False
    assert not data_dir.exists()
