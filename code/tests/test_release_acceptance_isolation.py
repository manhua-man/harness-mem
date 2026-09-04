from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_release_hook_acceptance.py"
)
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "run_release_hook_acceptance", SCRIPT_PATH
)
if SCRIPT_SPEC is None or SCRIPT_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load release acceptance module: {SCRIPT_PATH}")
acceptance = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(acceptance)


def test_release_acceptance_prefers_the_worktree_runtime(tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-package"
    fake_package = fake_root / "harness_mem"
    fake_package.mkdir(parents=True)
    (fake_package / "__init__.py").write_text(
        'raise RuntimeError("release script imported the wrong package")\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_root)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "release script imported the wrong package" not in result.stderr


def test_real_ledger_check_is_read_only_and_run_specific(tmp_path: Path) -> None:
    data_dir = tmp_path / "real-data"
    data_dir.mkdir()
    ledger = data_dir / "transcript_ledger.sqlite"
    connection = sqlite3.connect(ledger)
    connection.executescript(
        """
        CREATE TABLE distill_jobs (id TEXT PRIMARY KEY);
        CREATE TABLE transcript_sources (
            project_name TEXT,
            client TEXT,
            session_id TEXT
        );
        INSERT INTO distill_jobs VALUES ('existing-job');
        INSERT INTO transcript_sources VALUES ('project', 'cursor', 'existing-session');
        """
    )
    connection.commit()
    connection.close()
    before = ledger.stat()

    assert acceptance._run_absent_from_real_ledger(
        data_dir=data_dir,
        project_name="project",
        client="cursor",
        session_id="new-session",
        job_id="new-job",
    )
    assert not acceptance._run_absent_from_real_ledger(
        data_dir=data_dir,
        project_name="project",
        client="cursor",
        session_id="existing-session",
        job_id="existing-job",
    )
    after = ledger.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_release_acceptance_never_initializes_the_real_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    output_path = tmp_path / "reports" / "acceptance.json"
    real_data_dir = tmp_path / "real-data"
    real_notes_dir = tmp_path / "real-notes"
    real_data_dir.mkdir()
    real_notes_dir.mkdir()
    (real_data_dir / "sentinel").write_text("unchanged", encoding="utf-8")

    original_backend = acceptance.LocalMemoryBackend

    def guarded_backend(data_dir: Path):
        if Path(data_dir).resolve() == real_data_dir.resolve():
            raise AssertionError("release acceptance initialized the real backend")
        return original_backend(data_dir)

    async def fake_stage_session(**_kwargs) -> str:
        return "job-1"

    async def fake_read_job_truth(**_kwargs) -> dict:
        return {
            "job_status": "completed",
            "bound_truth_count": 1,
            "sqlite_truth_count": 1,
            "entries": [{"title": "Rule", "statement": "Keep one rule."}],
        }

    autonomous = {
        "execution_source": "autonomous_worker",
        "runtime_current": True,
        "config_current": True,
        "lifecycle_verified": True,
        "provider_isolated": True,
        "note_verified": True,
        "hook_guard_check": {
            "all_blocked": True,
            "downstream_jobs_created": 0,
        },
    }
    receipt = {
        "state": "succeeded",
        "provider": {"name": "hermes_cli", "host_client": "hermes"},
    }
    hook_call: dict[str, object] = {}

    def fake_run_hook(**kwargs):
        hook_call.update(kwargs)
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr(acceptance, "REAL_DATA_DIR", real_data_dir)
    monkeypatch.setattr(acceptance, "_real_notes_dir", lambda: real_notes_dir)
    monkeypatch.setattr(acceptance, "LocalMemoryBackend", guarded_backend)
    monkeypatch.setattr(
        acceptance,
        "_run_absent_from_real_ledger",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(acceptance, "_stage_session", fake_stage_session)
    monkeypatch.setattr(acceptance, "_read_job_truth", fake_read_job_truth)
    monkeypatch.setattr(
        acceptance,
        "_run_hook",
        fake_run_hook,
    )
    monkeypatch.setattr(acceptance, "read_autonomous_receipt", lambda *_a, **_k: receipt)
    monkeypatch.setattr(
        acceptance,
        "collect_outcomes",
        lambda **_kwargs: {"autonomous": autonomous},
    )
    monkeypatch.setattr(
        acceptance,
        "_search_via_mcp",
        lambda **_kwargs: {
            "process_ok": True,
            "status": "answered",
            "memories": [{"title": "Rule", "statement": "Keep one rule."}],
        },
    )
    monkeypatch.setattr(
        acceptance,
        "load_merged_config",
        lambda _root: SimpleNamespace(distill_autonomous_cli="hermes"),
    )
    monkeypatch.setattr(
        acceptance,
        "resolve_semantic_executor_client",
        lambda _config, _host: "hermes",
    )
    monkeypatch.setattr(
        acceptance,
        "build_semantic_executor",
        lambda _config, _host: object(),
    )
    monkeypatch.setattr(
        acceptance,
        "run_model_samples",
        lambda **_kwargs: {
            "status": "passed",
            "passed": 1,
            "failed": 0,
            "total": 1,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--project-root",
            str(project_root),
            "--output",
            str(output_path),
        ],
    )

    assert acceptance.main() == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["model_check"]["status"] == "passed"
    assert report["full_hook_started"] is True
    assert hook_call["wait_timeout"] == 600
    assert report["isolation"]["real_ledger_run_absent"] is True
    assert report["provider_matches_selected_cli"] is True
    assert (real_data_dir / "sentinel").read_text(encoding="utf-8") == "unchanged"


def test_release_acceptance_stops_before_job_and_hook_when_model_check_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    output_path = tmp_path / "reports" / "acceptance.json"
    real_data_dir = tmp_path / "real-data"
    real_notes_dir = tmp_path / "real-notes"
    real_data_dir.mkdir()
    real_notes_dir.mkdir()

    async def forbidden_stage(**_kwargs) -> str:
        raise AssertionError("a failed model check must not create a job")

    def forbidden_hook(**_kwargs):
        raise AssertionError("a failed model check must not start the full Hook")

    monkeypatch.setattr(acceptance, "REAL_DATA_DIR", real_data_dir)
    monkeypatch.setattr(acceptance, "_real_notes_dir", lambda: real_notes_dir)
    monkeypatch.setattr(acceptance, "_stage_session", forbidden_stage)
    monkeypatch.setattr(acceptance, "_run_hook", forbidden_hook)
    monkeypatch.setattr(
        acceptance,
        "load_merged_config",
        lambda _root: SimpleNamespace(distill_autonomous_cli="hermes"),
    )
    monkeypatch.setattr(
        acceptance,
        "resolve_semantic_executor_client",
        lambda _config, _host: "hermes",
    )
    monkeypatch.setattr(
        acceptance,
        "build_semantic_executor",
        lambda _config, _host: object(),
    )
    monkeypatch.setattr(
        acceptance,
        "run_model_samples",
        lambda **_kwargs: {
            "status": "failed",
            "passed": 0,
            "failed": 1,
            "total": 1,
            "error": {"kind": "transient", "message": "timed out"},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--project-root",
            str(project_root),
            "--output",
            str(output_path),
        ],
    )

    assert acceptance.main() == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["reason"] == "model_check_failed"
    assert report["full_hook_started"] is False
