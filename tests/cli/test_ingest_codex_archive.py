from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.commands.support import project_adapter_cursor_path
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run, write_codex_archive_session

pytestmark = pytest.mark.cli


def test_codex_archive_adapter_reports_missing_archive_dir(data_dir: Path, tmp_path: Path):
    missing_archive_dir = tmp_path / "missing-archives"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        result = run(
            CodexArchiveAdapter(backend, archive_dir=missing_archive_dir).ingest(
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
            "code": "archive_dir_missing",
            "message": f"Codex archive directory does not exist: {missing_archive_dir}",
            "path": str(missing_archive_dir),
        }
    ]


def test_codex_archive_ingest_uses_incremental_cursor(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    archive_root = tmp_path / "archives"
    first = write_codex_archive_session(
        archive_root,
        "2026-05-17-a",
        user_text="First archive session",
        assistant_text="Archived answer A",
    )
    second = write_codex_archive_session(
        archive_root,
        "2026-05-17-b",
        user_text="Second archive session",
        assistant_text="Archived answer B",
    )
    first_time = 1_700_000_000
    second_time = first_time + 60
    os.utime(first, (first_time, first_time))
    os.utime(second, (second_time, second_time))

    patch_cli_adapters(monkeypatch, codex_archive_root=archive_root)

    assert run(cli.cmd_ingest("codex-archive", "demo", 10)) == 0
    first_output = capsys.readouterr().out
    assert "Sessions found: 2" in first_output
    assert "Candidates after cursor: 2" in first_output
    assert "Ingested: 2 sessions" in first_output

    third = write_codex_archive_session(
        archive_root,
        "2026-05-17-c",
        user_text="Third archive session",
        assistant_text="Archived answer C",
    )
    third_time = second_time + 60
    os.utime(third, (third_time, third_time))

    assert run(cli.cmd_ingest("codex-archive", "demo", 10)) == 0
    second_output = capsys.readouterr().out
    assert "Sessions found: 3" in second_output
    assert "Candidates after cursor: 1" in second_output
    assert "Ingested: 1 sessions" in second_output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert sorted(observation.session_id for observation in observations) == [
            "2026-05-17-a",
            "2026-05-17-b",
            "2026-05-17-c",
        ]
    finally:
        run(backend.close())

    cursor_path = project_adapter_cursor_path("demo", "codex-archive")
    assert cursor_path.exists()


def test_codex_archive_full_rescan_bypasses_cursor_without_duplicate_ingest(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    archive_root = tmp_path / "archives"
    first = write_codex_archive_session(
        archive_root,
        "2026-05-17-a",
        user_text="First archive session",
        assistant_text="Archived answer A",
    )
    second = write_codex_archive_session(
        archive_root,
        "2026-05-17-b",
        user_text="Second archive session",
        assistant_text="Archived answer B",
    )
    base_time = 1_700_100_000
    os.utime(first, (base_time, base_time))
    os.utime(second, (base_time + 60, base_time + 60))

    patch_cli_adapters(monkeypatch, codex_archive_root=archive_root)

    assert run(cli.cmd_ingest("codex-archive", "demo", 1)) == 0
    assert run(cli.cmd_ingest("codex-archive", "demo", 10, True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert sorted(observation.session_id for observation in observations) == [
            "2026-05-17-a",
            "2026-05-17-b",
        ]
    finally:
        run(backend.close())

    captured = capsys.readouterr().out
    assert "Skipped existing: 1 sessions" in captured or "Skipped existing: 2 sessions" in captured
