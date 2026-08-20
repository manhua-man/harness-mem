from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.runtime_reset import apply_runtime_reset, runtime_reset_plan
from harness_mem.maintenance_lock import exclusive_maintenance_run


def _seed_archive(archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True)
    (archive_dir / "rollout-reset-fixture.jsonl").write_text(
        '{"id":"reset-fixture"}\n', encoding="utf-8"
    )


def test_runtime_reset_preview_and_apply_preserve_archive_sources(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archived_sessions"
    _seed_archive(archive_dir)
    (data_dir / "nested").mkdir(parents=True)
    (data_dir / "nested" / "memory.json").write_text("old memory", encoding="utf-8")
    (data_dir / "old.sqlite").write_text("old index", encoding="utf-8")

    preview = runtime_reset_plan(data_dir=data_dir, archive_dir=archive_dir)

    assert preview["apply"] is False
    assert preview["archive_source_count"] == 1
    assert preview["target_names"] == ["nested", "old.sqlite"]
    assert (data_dir / "nested" / "memory.json").is_file()

    applied = apply_runtime_reset(data_dir=data_dir, archive_dir=archive_dir)

    assert applied["success"] is True
    assert applied["remaining_runtime_items"] == []
    assert applied["archive_source_count_after"] == 1
    assert (archive_dir / "rollout-reset-fixture.jsonl").is_file()
    assert list(data_dir.iterdir()) == []


def test_runtime_reset_fails_closed_while_maintenance_is_active(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archived_sessions"
    _seed_archive(archive_dir)
    data_dir.mkdir()
    (data_dir / "old.sqlite").write_text("old index", encoding="utf-8")

    with exclusive_maintenance_run(
        data_dir,
        run_id="another-maintenance-run",
        operation="test",
    ):
        with pytest.raises(FileExistsError):
            apply_runtime_reset(data_dir=data_dir, archive_dir=archive_dir)

    assert (data_dir / "old.sqlite").is_file()


def test_runtime_reset_rejects_missing_or_overlapping_archive_source(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(ValueError, match="unavailable"):
        runtime_reset_plan(data_dir=data_dir, archive_dir=tmp_path / "missing")

    _seed_archive(data_dir / "archived_sessions")
    with pytest.raises(ValueError, match="overlap"):
        runtime_reset_plan(
            data_dir=data_dir,
            archive_dir=data_dir / "archived_sessions",
        )
