from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from harness_mem.commands.doctor import _doctor_recovery_plan_block
from harness_mem.commands.doctor_recovery import (
    build_doctor_recovery_plan,
    read_only_storage_v2_health,
)
from harness_mem.storage.canonical_store import (
    CANONICAL_ENTITY_TABLES,
    canonical_store_path,
    initialize_canonical_schema,
)


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "status": "healthy",
        "project_name": "demo",
        "runtime_state": "canonical",
        "checksum_relation": "exact_match",
        "sqlite_integrity": "ok",
        "index_drift": [],
    }
    report.update(overrides)
    return report


def test_expected_canonical_growth_is_informational_without_warning(capsys) -> None:
    plan = build_doctor_recovery_plan(
        _report(
            checksum_relation="canonical_superset_expected",
            checksum_match=False,
            canonical_only_count=3,
        )
    )

    assert plan["assessment"] == "expected_growth"
    assert plan["items"] == []
    assert plan["read_only"] is True
    assert plan["automatic_apply_allowed"] is False

    _doctor_recovery_plan_block(plan)
    output = capsys.readouterr().out
    assert "expected_growth" in output
    assert "⚠️" not in output


def test_recovery_plan_classifies_safe_snapshot_manual_and_destructive() -> None:
    safe = build_doctor_recovery_plan(_report(status="index_drift", index_drift=["idx_a"]))
    snapshot = build_doctor_recovery_plan(
        _report(
            status="partial_migration",
            checksum_relation="legacy_missing_in_canonical",
        )
    )
    manual = build_doctor_recovery_plan(
        _report(status="checksum_drift", checksum_relation="content_conflict")
    )
    destructive = build_doctor_recovery_plan(
        _report(
            status="corrupt",
            checksum_relation="corruption",
            sqlite_integrity="failed",
            corruption_detail="database disk image is malformed",
        )
    )

    assert safe["items"][0]["action_class"] == "safe_rebuild"
    assert safe["items"][0]["apply_command"].endswith("--apply")
    assert snapshot["items"][0]["action_class"] == "snapshot_required"
    assert snapshot["items"][0]["preview_command"].endswith("--dry-run")
    assert manual["items"][0]["action_class"] == "manual_review"
    assert manual["items"][0]["apply_command"] is None
    assert destructive["assessment"] == "corruption"
    assert destructive["items"][0]["action_class"] == "destructive"
    assert destructive["items"][0]["apply_command"] is None
    assert destructive["items"][0]["destructive"] is True


def test_recovery_plan_does_not_render_unsafe_project_name_as_shell_text() -> None:
    project_name = 'demo$(Write-Output "unsafe")'
    plan = build_doctor_recovery_plan(
        {
            "status": "index_drift",
            "project_name": project_name,
            "checksum_relation": "exact_match",
            "index_drift": ["idx_missing"],
            "warnings": [],
        }
    )

    assert plan["project_name"] == project_name
    command = plan["items"][0]["preview_command"]
    assert command.endswith("--project <PROJECT_NAME> --dry-run")
    assert "Write-Output" not in command


def test_invalid_legacy_fails_closed_without_apply_command() -> None:
    plan = build_doctor_recovery_plan(
        _report(
            status="degraded",
            checksum_relation="invalid_legacy",
            index_drift=["idx_observations_metadata"],
        )
    )

    assert plan["assessment"] == "corruption"
    assert plan["automatic_apply_allowed"] is False
    assert plan["items"][0]["action_class"] == "manual_review"
    assert all(item["apply_command"] is None for item in plan["items"])
    assert "deleting" in (plan["items"][0]["no_automatic_action"] or "")


def test_unsafe_combined_states_never_offer_apply_commands() -> None:
    reports = [
        _report(
            status="degraded",
            checksum_relation="content_conflict",
            index_drift=["idx_observations_metadata"],
        ),
        _report(
            status="corrupt",
            checksum_relation="content_conflict",
            sqlite_integrity="failed",
            corruption_detail="database disk image is malformed",
            index_drift=["idx_observations_metadata"],
        ),
    ]

    for report in reports:
        plan = build_doctor_recovery_plan(report)

        assert plan["automatic_apply_allowed"] is False
        assert plan["items"]
        assert all(item["apply_command"] is None for item in plan["items"])


def test_read_only_probe_detects_corrupt_sqlite_without_modifying_it(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db_path = canonical_store_path(data_dir)
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"not a sqlite database")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    report = read_only_storage_v2_health(data_dir, project_name="demo")
    plan = build_doctor_recovery_plan(report)

    assert report["status"] == "corrupt"
    assert plan["assessment"] == "corruption"
    assert plan["items"][0]["action_class"] == "destructive"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in db_path.parent.iterdir()) == [db_path.name]


def test_read_only_probe_reports_missing_indexes_without_recreating_them(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    db_path = canonical_store_path(data_dir)
    db_path.parent.mkdir(parents=True)
    dropped = f"idx_{CANONICAL_ENTITY_TABLES[0]}_metadata"
    connection = sqlite3.connect(db_path)
    try:
        initialize_canonical_schema(connection)
        connection.execute(f"DROP INDEX {dropped}")
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    report = read_only_storage_v2_health(data_dir, project_name="demo")

    assert report["status"] == "index_drift"
    assert dropped in report["index_drift"]
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    check = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        indexes = {
            str(row[0])
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    finally:
        check.close()
    assert dropped not in indexes
