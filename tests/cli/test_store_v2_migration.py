from __future__ import annotations

import json
from pathlib import Path

from harness_mem import cli
from harness_mem.commands.maintenance import cmd_migrate_store_v2
from harness_mem.storage.store_v2_migration import (
    apply_store_v2_migration,
    build_migration_plan,
    export_store_v2_json_snapshot,
    logical_checksum,
    scan_legacy_payloads,
)
from tests.helpers import run


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _seed_v3_blobs(data_dir: Path) -> list[Path]:
    return [
        _write_json(
            data_dir / "verbatim" / "obs-demo.json",
            {
                "id": "obs-demo",
                "session_id": "session-a",
                "client": "codex",
                "content_type": "text",
                "raw_content": "demo observation",
                "timestamp": "2026-06-12T00:00:00+00:00",
                "tags": [],
                "metadata": {"project_name": "demo"},
                "compacted": False,
            },
        ),
        _write_json(
            data_dir / "structured" / "memory_entries" / "mem-demo.json",
            {
                "id": "mem-demo",
                "project_name": "demo",
                "category": "decision",
                "content": "demo memory",
                "confidence": 0.8,
                "status": "accepted",
                "source": "unit",
                "created_at": "2026-06-12T00:00:00+00:00",
                "updated_at": "2026-06-12T00:00:00+00:00",
                "tags": [],
                "compacted": False,
            },
        ),
        _write_json(
            data_dir / "structured" / "memory_entries" / "mem-other.json",
            {
                "id": "mem-other",
                "project_name": "other",
                "category": "decision",
                "content": "other memory",
                "confidence": 0.8,
                "status": "accepted",
                "source": "unit",
                "created_at": "2026-06-12T00:00:00+00:00",
                "updated_at": "2026-06-12T00:00:00+00:00",
                "tags": [],
                "compacted": False,
            },
        ),
    ]


def test_store_v2_dry_run_is_project_scoped_and_read_only(data_dir: Path) -> None:
    blobs = _seed_v3_blobs(data_dir)
    before = {path: path.read_text(encoding="utf-8") for path in blobs}

    plan = build_migration_plan(data_dir, project_name="demo")

    assert plan["dry_run"] is True
    assert plan["default_storage_changed"] is False
    assert plan["legacy_json_file_count"] == 2
    assert plan["collections"] == {"memory_entries": 1, "observations": 1}
    assert len(plan["logical_checksum"]) == 64
    assert not (data_dir / "store_v2" / "canonical.sqlite").exists()
    assert {path: path.read_text(encoding="utf-8") for path in blobs} == before


def test_store_v2_apply_and_export_roundtrip_checksums(data_dir: Path, tmp_path: Path) -> None:
    _seed_v3_blobs(data_dir)
    legacy_rows, invalid = scan_legacy_payloads(data_dir, project_name="demo")
    assert invalid == []
    legacy_checksum = logical_checksum(legacy_rows)

    applied = apply_store_v2_migration(data_dir, project_name="demo")
    assert applied["checksum_match"] is True
    assert applied["before_checksum"] == legacy_checksum
    assert applied["after_checksum"] == legacy_checksum
    assert Path(applied["canonical_db_path"]).exists()

    exported = export_store_v2_json_snapshot(
        data_dir,
        tmp_path / "rollback",
        project_name="demo",
    )
    assert exported["rollback_checksum_match"] is True
    exported_rows, exported_invalid = scan_legacy_payloads(tmp_path / "rollback", project_name="demo")
    assert exported_invalid == []
    assert logical_checksum(exported_rows) == legacy_checksum
    assert (tmp_path / "rollback" / "verbatim" / "obs-demo.json").exists()
    assert (tmp_path / "rollback" / "structured" / "memory_entries" / "mem-demo.json").exists()
    assert not (tmp_path / "rollback" / "structured" / "memory_entries" / "mem-other.json").exists()


def test_cli_migrate_store_v2_dry_run_and_apply(
    data_dir: Path,
    capsys,
    monkeypatch,
) -> None:
    cli.cmd_use("demo")
    _seed_v3_blobs(data_dir)

    monkeypatch.setattr(
        "sys.argv",
        ["harness-mem", "maintenance", "migrate-store-v2", "-p", "demo"],
    )
    assert cli.main() == 0
    dry_out = capsys.readouterr().out
    assert "Storage v2 migration dry run: demo" in dry_out
    assert "Default storage changed: false" in dry_out
    assert "No changes written" in dry_out
    assert not (data_dir / "store_v2" / "canonical.sqlite").exists()

    monkeypatch.setattr(
        "sys.argv",
        ["harness-mem", "maintenance", "migrate-store-v2", "-p", "demo", "--apply"],
    )
    assert cli.main() == 0
    apply_out = capsys.readouterr().out
    assert "Applied Storage v2 side-by-side migration: demo" in apply_out
    assert "Checksum match: true" in apply_out
    assert (data_dir / "store_v2" / "canonical.sqlite").exists()


def test_cmd_migrate_store_v2_export_rollback(
    data_dir: Path,
    tmp_path: Path,
    capsys,
) -> None:
    _seed_v3_blobs(data_dir)
    assert run(cmd_migrate_store_v2("demo", apply=True)) == 0
    capsys.readouterr()

    assert run(
        cmd_migrate_store_v2(
            "demo",
            apply=True,
            export_rollback=str(tmp_path / "rollback"),
        )
    ) == 0
    out = capsys.readouterr().out
    assert "Exported Storage v2 rollback snapshot: demo" in out
    assert "Rollback checksum match: true" in out
