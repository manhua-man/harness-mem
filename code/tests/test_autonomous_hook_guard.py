from __future__ import annotations

import json
from pathlib import Path

from harness_mem.autonomous.hook_guard import (
    autonomous_provider_hook_reentry_blocked,
    count_hook_reentry_blocks,
    record_hook_reentry_block,
)


def test_record_and_count_hook_reentry_blocks(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_dir = tmp_path / "data"
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="post-turn-maintenance",
        trigger_id="session-1",
    )
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="dream-end",
        trigger_id="session-2",
    )
    assert (
        count_hook_reentry_blocks(
            data_dir,
            project_name="demo",
            project_root=project_root,
        )
        == 2
    )
    assert (
        count_hook_reentry_blocks(
            data_dir,
            project_name="demo",
            project_root=project_root,
            trigger_id="session-1",
        )
        == 1
    )


def test_autonomous_provider_context_blocks_wake_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_AUTONOMOUS_PROVIDER", "1")
    assert autonomous_provider_hook_reentry_blocked("wake-start") is True


def test_hook_reentry_ledger_is_json_lines(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_dir = tmp_path / "data"
    record_hook_reentry_block(
        data_dir,
        project_name="demo",
        project_root=project_root,
        action="post-turn-maintenance",
        trigger_id="session-1",
    )
    ledger = next((data_dir / "autonomous" / "hook_reentry").glob("*.jsonl"))
    payload = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert payload["action"] == "post-turn-maintenance"
    assert payload["trigger_id"] == "session-1"
