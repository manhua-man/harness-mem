from __future__ import annotations

import json
import os

import pytest

from harness_mem.maintenance_lock import (
    exclusive_maintenance_run,
    maintenance_is_locked,
    maintenance_lock_path,
)


def test_exclusive_maintenance_run_blocks_live_owner_and_releases(tmp_path) -> None:
    with exclusive_maintenance_run(
        tmp_path,
        run_id="run-a",
        operation="archive-distill",
    ):
        assert maintenance_is_locked(tmp_path)
        with pytest.raises(FileExistsError):
            with exclusive_maintenance_run(
                tmp_path,
                run_id="run-b",
                operation="archive-distill",
            ):
                pass
    assert not maintenance_is_locked(tmp_path)


def test_exclusive_maintenance_run_recovers_dead_owner(tmp_path) -> None:
    path = maintenance_lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "dead-run",
                "operation": "archive-distill",
                "pid": max(os.getpid() + 10_000_000, 99_999_999),
            }
        ),
        encoding="utf-8",
    )

    with exclusive_maintenance_run(
        tmp_path,
        run_id="recovered-run",
        operation="archive-distill",
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["run_id"] == "recovered-run"
        assert payload["started_at"]
