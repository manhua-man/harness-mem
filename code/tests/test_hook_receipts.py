from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.hook_receipts import (
    inspect_hook_execution_receipt,
    read_hook_execution_receipt,
    record_hook_execution,
)


def test_hook_receipt_is_bound_to_current_hook_configuration(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    manifest = workspace / ".codex" / "hooks.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"

    receipt_path = record_hook_execution(
        data_dir,
        project_root=workspace,
        project_name="project",
        client="codex",
        action="wake-start",
        source="ide_hook",
        trigger_id="session-1",
    )

    assert receipt_path is not None
    receipt = read_hook_execution_receipt(
        data_dir,
        project_root=workspace,
        client="codex",
        action="wake-start",
    )
    assert receipt is not None
    assert receipt["trigger_id"] == "session-1"

    manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],"Stop":[]}}\n',
        encoding="utf-8",
    )

    assert (
        read_hook_execution_receipt(
            data_dir,
            project_root=workspace,
            client="codex",
            action="wake-start",
        )
        is None
    )


def test_hook_receipt_health_reports_last_success_age_and_freshness(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    manifest = workspace / ".codex" / "hooks.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    receipt_path = record_hook_execution(
        data_dir,
        project_root=workspace,
        project_name="project",
        client="codex",
        action="wake-start",
        source="ide_hook",
        trigger_id="session-1",
    )
    assert receipt_path is not None
    completed_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["completed_at"] = completed_at.isoformat()
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    fresh = inspect_hook_execution_receipt(
        data_dir,
        project_root=workspace,
        client="codex",
        action="wake-start",
        now=completed_at + timedelta(hours=12),
    )
    stale = inspect_hook_execution_receipt(
        data_dir,
        project_root=workspace,
        client="codex",
        action="wake-start",
        now=completed_at + timedelta(days=2),
    )

    assert fresh == {
        "freshness": "fresh",
        "receipt_status": "current",
        "last_success_at": completed_at.isoformat(),
        "age_seconds": 43200,
        "config_match": True,
    }
    assert stale["freshness"] == "stale"
    assert stale["age_seconds"] == 172800


def test_hook_receipt_health_distinguishes_missing_and_config_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    manifest = workspace / ".codex" / "hooks.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"

    missing = inspect_hook_execution_receipt(
        data_dir,
        project_root=workspace,
        client="codex",
        action="wake-start",
    )
    assert missing["freshness"] == "never"
    assert missing["receipt_status"] == "missing"
    assert missing["last_success_at"] is None

    record_hook_execution(
        data_dir,
        project_root=workspace,
        project_name="project",
        client="codex",
        action="wake-start",
        source="ide_hook",
        trigger_id="session-1",
    )
    manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook --changed"}]}}\n',
        encoding="utf-8",
    )
    mismatch = inspect_hook_execution_receipt(
        data_dir,
        project_root=workspace,
        client="codex",
        action="wake-start",
    )
    assert mismatch["freshness"] == "never"
    assert mismatch["receipt_status"] == "config_mismatch"
    assert mismatch["config_match"] is False
    assert mismatch["last_success_at"] is not None
