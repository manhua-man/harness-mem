from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run, write_codex_session

pytestmark = pytest.mark.cli


def test_codex_adapter_reports_missing_sessions_dir(data_dir: Path, tmp_path: Path):
    missing_sessions_dir = tmp_path / "missing-codex-sessions"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        result = run(
            CodexAdapter(backend, sessions_dir=missing_sessions_dir).ingest(
                project_name="demo",
                limit=5,
                min_size_kb=0,
            )
        )
    finally:
        run(backend.close())

    assert result["sessions_found"] == 0
    assert result["ingested"] == 0
    assert result["errors"] == 0
    assert result["warnings"] == [
        {
            "level": "warning",
            "code": "sessions_dir_missing",
            "message": f"Codex sessions directory does not exist: {missing_sessions_dir}",
            "path": str(missing_sessions_dir),
        }
    ]
    assert result["error_details"] == []


def test_codex_adapter_reports_corrupt_session_file(data_dir: Path, codex_sessions_root: Path):
    bad_session = codex_sessions_root / "corrupt-session.jsonl"
    bad_session.write_text(
        '\n'.join(['{"role": "user", "content": "hello"', '{"role": "assistant", "content": "missing brace"']) + "\n",
        encoding="utf-8",
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        result = run(
            CodexAdapter(backend, sessions_dir=codex_sessions_root).ingest(
                project_name="demo",
                limit=5,
                min_size_kb=0,
            )
        )
        observations = run(backend.verbatim_store.list(limit=10))
    finally:
        run(backend.close())

    assert result["sessions_found"] == 1
    assert result["ingested"] == 0
    assert result["errors"] == 1
    assert result["warnings"] == []
    assert result["error_details"] == [
        {
            "level": "error",
            "code": "session_parse_failed",
            "message": (
                "Failed to parse Codex session corrupt-session "
                f"({bad_session}): no valid JSON records found; skipped 2 malformed line(s)"
            ),
            "path": str(bad_session),
            "session_id": "corrupt-session",
        }
    ]
    assert observations == []


def test_codex_adapter_reports_session_save_failures(
    data_dir: Path,
    codex_sessions_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_codex_session(codex_sessions_root, "save-failure-session", "Investigate auth retry handling.")

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())

    async def raise_save(_observation):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(backend.verbatim_store, "save", raise_save)

    try:
        result = run(
            CodexAdapter(backend, sessions_dir=codex_sessions_root).ingest(
                project_name="demo",
                limit=5,
                min_size_kb=0,
            )
        )
    finally:
        run(backend.close())

    assert result["sessions_found"] == 1
    assert result["ingested"] == 0
    assert result["errors"] == 1
    assert result["warnings"] == []
    assert result["error_details"] == [
        {
            "level": "error",
            "code": "session_save_failed",
            "message": "Failed to save Codex session save-failure-session (database unavailable)",
            "path": str(codex_sessions_root / "save-failure-session.jsonl"),
            "session_id": "save-failure-session",
        }
    ]


def test_cmd_ingest_codex_prints_missing_sessions_dir_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    missing_sessions_dir = tmp_path / "missing-codex-sessions"
    patch_cli_adapters(monkeypatch, codex_sessions_root=missing_sessions_dir)

    assert run(cli.cmd_ingest("codex", "demo", 5)) == 1

    output = capsys.readouterr().out
    assert f"Warning: Codex sessions directory does not exist: {missing_sessions_dir}" in output
    assert "No codex sessions found." in output


def test_cmd_ingest_codex_prints_session_error_details(
    codex_sessions_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    bad_session = codex_sessions_root / "corrupt-session.jsonl"
    bad_session.write_text(
        '\n'.join(['{"role": "user", "content": "hello"', '{"role": "assistant", "content": "missing brace"']) + "\n",
        encoding="utf-8",
    )

    patch_cli_adapters(monkeypatch, codex_sessions_root=codex_sessions_root)

    assert run(cli.cmd_ingest("codex", "demo", 5)) == 1

    output = capsys.readouterr().out
    assert "Sessions found: 1" in output
    assert "Ingested: 0 sessions" in output
    assert (
        "Error: Failed to parse Codex session corrupt-session "
        f"({bad_session}): no valid JSON records found; skipped 2 malformed line(s)"
    ) in output
    assert "Errors: 1" in output


def test_codex_ingest_requires_project_name():
    assert run(cli.cmd_ingest("codex", None, 5)) == 1


def test_codex_ingest_sets_project_metadata(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    codex_sessions_root: Path,
):
    write_codex_session(codex_sessions_root, "codex-demo", "Worked on auth token expiry handling.")
    patch_cli_adapters(monkeypatch, codex_sessions_root=codex_sessions_root)

    assert run(cli.cmd_ingest("codex", "demo-project", 5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert len(observations) == 1
        assert observations[0].metadata["project_name"] == "demo-project"
    finally:
        run(backend.close())


def test_codex_ingest_uses_active_project(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    codex_sessions_root: Path,
):
    write_codex_session(codex_sessions_root, "codex-active", "Worked on auth token expiry handling.")
    patch_cli_adapters(monkeypatch, codex_sessions_root=codex_sessions_root)

    assert cli.cmd_use("demo-project") == 0
    assert run(cli.cmd_ingest("codex", None, 5)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert len(observations) == 1
        assert observations[0].metadata["project_name"] == "demo-project"
    finally:
        run(backend.close())
