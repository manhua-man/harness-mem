from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands.maintenance import cmd_migrate_store_v2
from harness_mem.storage.store_v2_migration import (
    apply_store_v2_migration,
    build_migration_plan,
    canonical_db_path,
    export_store_v2_json_snapshot,
    logical_checksum,
    scan_legacy_payloads,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "storage_v2_fixture.py"
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "storage_v2_fixture_for_tests",
    FIXTURE_PATH,
)
assert FIXTURE_SPEC is not None
assert FIXTURE_SPEC.loader is not None
STORAGE_V2_FIXTURE = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(STORAGE_V2_FIXTURE)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _seed_project(data_dir: Path, project_name: str) -> None:
    timestamp = datetime(2026, 6, 12, tzinfo=timezone.utc)
    _write_json(
        data_dir / "verbatim" / "obs-storage-v2-1.json",
        {
            "id": "obs-storage-v2-1",
            "session_id": "session-storage-v2",
            "client": "pytest",
            "raw_content": "storage v2 migration observation",
            "content_type": "transcript",
            "timestamp": timestamp.isoformat(),
            "metadata": {"project_name": project_name},
            "tags": ["storage-v2"],
            "compacted": False,
        },
    )
    _write_json(
        data_dir / "structured" / "memory_entries" / "mem-storage-v2-1.json",
        {
            "id": "mem-storage-v2-1",
            "project_name": project_name,
            "category": "decision",
            "content": "storage v2 keeps v3 JSON as default during v4.0.0",
            "confidence": 0.91,
            "source": "obs-storage-v2-1",
            "status": "accepted",
            "created_at": timestamp.isoformat(),
            "updated_at": timestamp.isoformat(),
            "tags": ["storage-v2"],
        },
    )
    _write_json(
        data_dir / "structured" / "confirmed_rules" / "rule-storage-v2-1.json",
        {
            "id": "rule-storage-v2-1",
            "project_name": project_name,
            "pattern": "Storage v2 migration must be reversible.",
            "trigger": "When running v4.0.0 migration checks.",
            "examples": [],
            "confirmed_at": timestamp.isoformat(),
            "source_candidate_id": "candidate-storage-v2-1",
            "source_session_id": "session-storage-v2",
            "tags": ["storage-v2"],
        },
    )


def test_store_v2_dry_run_apply_and_rollback_checksum_contract(
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_name = "storage-v2-contract"
    _seed_project(data_dir, project_name)

    plan = build_migration_plan(data_dir, project_name=project_name)

    assert plan["dry_run"] is True
    assert plan["default_storage_changed"] is False
    assert plan["legacy_json_file_count"] == 3
    assert plan["apply_supported"] is True
    assert plan["rollback_supported"] is True
    assert not canonical_db_path(data_dir).exists()

    applied = apply_store_v2_migration(data_dir, project_name=project_name)

    assert applied["checksum_match"] is True
    assert applied["default_storage_changed"] is False
    assert applied["migrated_row_count"] == 3
    assert canonical_db_path(data_dir).exists()

    dry_export_dir = tmp_path / "dry-export"
    dry_export = export_store_v2_json_snapshot(
        data_dir,
        dry_export_dir,
        project_name=project_name,
        apply=False,
    )

    assert dry_export["dry_run"] is True
    assert dry_export["would_export_json_file_count"] == 3
    assert dry_export["exported_json_file_count"] == 0
    assert not dry_export_dir.exists()

    export_dir = tmp_path / "rollback-export"
    exported = export_store_v2_json_snapshot(
        data_dir,
        export_dir,
        project_name=project_name,
        apply=True,
    )
    source_rows, _ = scan_legacy_payloads(data_dir, project_name=project_name)
    exported_rows, invalid = scan_legacy_payloads(export_dir, project_name=project_name)

    assert invalid == []
    assert exported["rollback_checksum_match"] is True
    assert exported["exported_json_file_count"] == 3
    assert logical_checksum(source_rows) == logical_checksum(exported_rows)


def test_migrate_store_v2_cli_export_rollback_respects_dry_run(
    data_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_name = "storage-v2-cli"
    _seed_project(data_dir, project_name)
    from tests.helpers import run

    assert run(cmd_migrate_store_v2(project_name, apply=True)) == 0
    capsys.readouterr()

    export_dir = tmp_path / "cli-rollback"
    assert (
        run(
            cmd_migrate_store_v2(
                project_name,
                apply=False,
                export_rollback=str(export_dir),
            )
        )
        == 0
    )
    captured = capsys.readouterr()

    assert "Storage v2 rollback export dry run" in captured.out
    assert "No changes written" in captured.out
    assert not export_dir.exists()

    assert (
        run(
            cmd_migrate_store_v2(
                project_name,
                apply=True,
                export_rollback=str(export_dir),
            )
        )
        == 0
    )
    assert (export_dir / "verbatim" / "obs-storage-v2-1.json").exists()


def test_storage_v2_fixture_profiles_are_stable() -> None:
    assert STORAGE_V2_FIXTURE.CORPUS_PROFILES == {
        "10k": 10_000,
        "100k": 100_000,
        "1m": 1_000_000,
    }
    assert STORAGE_V2_FIXTURE.resolve_entry_count(120, None) == 120
    assert STORAGE_V2_FIXTURE.resolve_entry_count(120, "10k") == 10_000


def test_storage_v2_fixture_writes_deterministic_dataset(tmp_path: Path) -> None:
    first = STORAGE_V2_FIXTURE.generate_v3_corpus(
        tmp_path / "first",
        entry_count=12,
        project_count=3,
        seed=4000,
        payload_size_bytes=128,
    )
    second = STORAGE_V2_FIXTURE.generate_v3_corpus(
        tmp_path / "second",
        entry_count=12,
        project_count=3,
        seed=4000,
        payload_size_bytes=128,
    )

    assert first["dataset_hash"] == second["dataset_hash"]
    assert first["entry_mix"] == {
        "observation": 2,
        "memory_entry": 2,
        "confirmed_rule": 2,
        "relation_fact": 2,
        "rule_candidate": 2,
        "skill": 2,
    }
    assert STORAGE_V2_FIXTURE.corpus_json_file_count(tmp_path / "first") == 12
