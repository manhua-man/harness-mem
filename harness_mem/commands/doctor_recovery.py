"""Read-only Storage v2 probing and explainable Doctor recovery plans."""

from __future__ import annotations

import sqlite3
import tempfile
import re
from pathlib import Path
from typing import Any, Literal, TypedDict

from harness_mem.storage.canonical_store import (
    _missing_indexes,
    canonical_store_health,
    canonical_store_path,
)

RecoveryClass = Literal[
    "safe_rebuild",
    "snapshot_required",
    "manual_review",
    "destructive",
]
StorageAssessment = Literal[
    "healthy",
    "expected_growth",
    "actionable_drift",
    "corruption",
]


class RecoveryItem(TypedDict):
    id: str
    action_class: RecoveryClass
    risk: Literal["low", "medium", "high", "critical"]
    reason: str
    preview_command: str
    apply_command: str | None
    no_automatic_action: str | None
    destructive: bool


class RecoveryPlan(TypedDict):
    schema_version: int
    project_name: str | None
    assessment: StorageAssessment
    summary: str
    read_only: bool
    automatic_apply_allowed: bool
    items: list[RecoveryItem]


def read_only_storage_v2_health(
    data_dir: Path,
    *,
    project_name: str | None = None,
    wal_size_warning_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Inspect Storage v2 without letting schema setup modify the live database.

    ``canonical_store_health`` also makes old schemas usable by creating missing
    schema objects. That is appropriate on runtime boot, but Doctor is a probe.
    We therefore copy a transactionally consistent snapshot through a read-only
    SQLite connection and run the compatibility health logic on that snapshot.
    """

    data_dir = Path(data_dir)
    db_path = canonical_store_path(data_dir)
    if not db_path.exists():
        return canonical_store_health(
            data_dir,
            project_name=project_name,
            canonical_path=db_path,
            wal_size_warning_bytes=wal_size_warning_bytes,
        )

    wal_path = Path(f"{db_path}-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    try:
        source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            integrity_row = source.execute("PRAGMA quick_check").fetchone()
            integrity = str(integrity_row[0]) if integrity_row else "no result"
            if integrity != "ok":
                return _corrupt_storage_report(
                    db_path,
                    project_name=project_name,
                    detail=f"SQLite quick_check returned: {integrity}",
                    wal_size=wal_size,
                )
            missing_indexes = _missing_indexes(source)
            with tempfile.TemporaryDirectory(prefix="harness-mem-doctor-") as temp_dir:
                snapshot_path = Path(temp_dir) / "canonical.sqlite"
                snapshot = sqlite3.connect(snapshot_path)
                try:
                    source.backup(snapshot)
                    snapshot.commit()
                finally:
                    snapshot.close()
                report = canonical_store_health(
                    data_dir,
                    project_name=project_name,
                    canonical_path=snapshot_path,
                    wal_size_warning_bytes=wal_size_warning_bytes,
                )
        finally:
            source.close()
    except sqlite3.DatabaseError as exc:
        return _corrupt_storage_report(
            db_path,
            project_name=project_name,
            detail=f"SQLite could not be read safely: {exc}",
            wal_size=wal_size,
        )
    except OSError as exc:
        return {
            "status": "health_unavailable",
            "project_name": project_name,
            "canonical_db_path": str(db_path),
            "runtime_state": "unknown",
            "warnings": [f"Storage v2 read-only probe failed: {exc}"],
            "checksum_relation": "unknown",
            "index_drift": [],
            "wal_size_bytes": wal_size,
            "wal_warning": wal_size > wal_size_warning_bytes,
        }

    report["canonical_db_path"] = str(db_path)
    report["sqlite_integrity"] = "ok"
    report["wal_size_bytes"] = wal_size
    report["wal_warning"] = wal_size > wal_size_warning_bytes
    report["index_drift"] = missing_indexes
    if missing_indexes and report.get("status") == "healthy":
        report["status"] = "index_drift"
    return report


def build_doctor_recovery_plan(storage_report: dict[str, Any]) -> RecoveryPlan:
    """Classify a Storage v2 report without executing any recovery action."""

    project_name = storage_report.get("project_name")
    project_arg = _project_argument(project_name)
    doctor_command = f"harness-mem doctor{project_arg}"
    migrate_preview = f"harness-mem maintenance migrate-store-v2{project_arg} --dry-run"
    migrate_apply = f"harness-mem maintenance migrate-store-v2{project_arg} --apply"
    relation = str(storage_report.get("checksum_relation") or "unknown")
    status = str(storage_report.get("status") or "unknown")
    items: list[RecoveryItem] = []

    if status == "corrupt" or storage_report.get("sqlite_integrity") not in {None, "ok"}:
        items.append(
            _item(
                "storage_corruption",
                "destructive",
                "critical",
                str(
                    storage_report.get("corruption_detail")
                    or "Canonical SQLite failed its integrity check."
                ),
                doctor_command,
                no_action=(
                    "No automatic action. Preserve the damaged database and restore only "
                    "from a verified snapshot; replacing or deleting it is destructive."
                ),
            )
        )
        return _plan(
            project_name,
            "corruption",
            "Canonical storage is unreadable; recovery is blocked pending operator review.",
            items,
        )

    if relation == "invalid_legacy":
        items.append(
            _item(
                "invalid_legacy_payloads",
                "manual_review",
                "high",
                "Legacy JSON contains invalid payloads, so migration cannot prove equivalence.",
                migrate_preview,
                no_action=(
                    "No automatic action. Quarantine and review invalid files before any "
                    "migration; deleting them would be destructive."
                ),
            )
        )
        return _plan(
            project_name,
            "corruption",
            "Legacy compatibility data is invalid and cannot be compared safely.",
            items,
        )

    if relation == "content_conflict":
        items.append(
            _item(
                "authority_conflict",
                "manual_review",
                "high",
                "Legacy and canonical payloads differ before canonical authority is established.",
                migrate_preview,
                no_action=(
                    "No automatic action. Select the authoritative revision after inspecting "
                    "both stores; Doctor will not overwrite either copy."
                ),
            )
        )
        return _plan(
            project_name,
            "actionable_drift",
            (
                "Storage authority is ambiguous; recovery is blocked pending "
                "operator review."
            ),
            items,
        )

    if relation == "legacy_missing_in_canonical" or status in {
        "not_migrated",
        "partial_migration",
        "degraded",
    }:
        items.append(
            _item(
                "atomic_store_migration",
                "snapshot_required",
                "medium",
                "Canonical storage is absent, degraded, or missing identities present in legacy data.",
                migrate_preview,
                apply_command=migrate_apply,
                no_action=(
                    "Apply is operator-initiated and must create a pre-migration snapshot; "
                    "Doctor never invokes it."
                ),
            )
        )

    missing_indexes = list(storage_report.get("index_drift") or [])
    if missing_indexes:
        items.append(
            _item(
                "canonical_index_rebuild",
                "safe_rebuild",
                "low",
                f"Canonical storage is missing {len(missing_indexes)} derived index(es).",
                migrate_preview,
                apply_command=migrate_apply,
                no_action="Doctor reports the rebuild but never applies it automatically.",
            )
        )

    warnings = list(storage_report.get("warnings") or [])
    if warnings and not items:
        items.append(
            _item(
                "health_probe_unavailable",
                "manual_review",
                "high",
                "; ".join(str(warning) for warning in warnings),
                doctor_command,
                no_action="No automatic action because storage health could not be established.",
            )
        )

    if items:
        return _plan(
            project_name,
            "actionable_drift",
            "Storage needs explicit operator action; no repair has been executed.",
            items,
        )
    if relation == "canonical_superset_expected":
        return _plan(
            project_name,
            "expected_growth",
            (
                "Canonical storage contains newer authoritative rows; the legacy snapshot is "
                "expected to lag and no recovery action is needed."
            ),
            [],
        )
    return _plan(
        project_name,
        "healthy",
        "Canonical and legacy storage are consistent; no recovery action is needed.",
        [],
    )


def _corrupt_storage_report(
    db_path: Path,
    *,
    project_name: str | None,
    detail: str,
    wal_size: int,
) -> dict[str, Any]:
    return {
        "status": "corrupt",
        "project_name": project_name,
        "canonical_db_path": str(db_path),
        "runtime_state": "unknown",
        "checksum_match": False,
        "checksum_relation": "corruption",
        "checksum_relation_explanation": detail,
        "sqlite_integrity": "failed",
        "corruption_detail": detail,
        "index_drift": [],
        "wal_size_bytes": wal_size,
        "wal_warning": False,
    }


def _project_argument(project_name: Any) -> str:
    if not isinstance(project_name, str) or not project_name:
        return ""
    if re.fullmatch(r"[A-Za-z0-9._-]+", project_name):
        return f" --project {project_name}"
    # No quoting syntax is safe across PowerShell, cmd, and POSIX shells.
    # Keep the diagnostic copy/paste-safe and expose the real value separately
    # in RecoveryPlan.project_name for the operator to substitute deliberately.
    return " --project <PROJECT_NAME>"


def _item(
    item_id: str,
    action_class: RecoveryClass,
    risk: Literal["low", "medium", "high", "critical"],
    reason: str,
    preview_command: str,
    *,
    apply_command: str | None = None,
    no_action: str | None = None,
) -> RecoveryItem:
    return {
        "id": item_id,
        "action_class": action_class,
        "risk": risk,
        "reason": reason,
        "preview_command": preview_command,
        "apply_command": apply_command,
        "no_automatic_action": no_action,
        "destructive": action_class == "destructive",
    }


def _plan(
    project_name: str | None,
    assessment: StorageAssessment,
    summary: str,
    items: list[RecoveryItem],
) -> RecoveryPlan:
    return {
        "schema_version": 1,
        "project_name": project_name,
        "assessment": assessment,
        "summary": summary,
        "read_only": True,
        "automatic_apply_allowed": False,
        "items": items,
    }
