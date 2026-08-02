from __future__ import annotations

import asyncio

from harness_mem.mcp import read_wake_handlers


def test_wake_returns_machine_readable_distill_maintenance_offer(
    monkeypatch,
) -> None:
    offer = {
        "contract_version": "agent-distill-offer-v1",
        "agent_execution_required": True,
        "process_limit": 1,
        "job_ids": ["job-1"],
        "prepare_arguments": {
            "run_ingest": False,
            "evidence_mode": "semantic",
            "detail_level": "compact",
            "budget_tokens": 3000,
        },
    }

    def fake_cmd_wake_up(
        _project_name,
        _no_auto_ingest=False,
        *,
        maintenance_capture,
        **_kwargs,
    ):
        maintenance_capture.update(offer)
        return asyncio.sleep(0, result=1)

    monkeypatch.setattr(
        read_wake_handlers,
        "cmd_wake_up",
        fake_cmd_wake_up,
    )

    payload = read_wake_handlers.tool_wake(project_name="demo")

    assert payload["success"] is False
    assert payload["distill_maintenance"] == offer
    assert payload["distill_maintenance"]["job_ids"] == ["job-1"]
    assert payload["distill_maintenance"]["prepare_arguments"]["run_ingest"] is False
