from __future__ import annotations

from pathlib import Path

from harness_mem.hook_receipts import (
    read_hook_execution_receipt,
    record_hook_execution,
)


def test_hook_receipt_is_bound_to_current_hook_configuration(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    manifest = workspace / ".codex" / "hooks.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"hooks":{"SessionStart":[]}}\n', encoding="utf-8")
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

    manifest.write_text('{"hooks":{"SessionStart":[],"Stop":[]}}\n', encoding="utf-8")

    assert (
        read_hook_execution_receipt(
            data_dir,
            project_root=workspace,
            client="codex",
            action="wake-start",
        )
        is None
    )
