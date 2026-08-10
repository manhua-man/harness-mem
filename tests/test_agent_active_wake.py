from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands import wake
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import read_wake_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_wake_returns_machine_readable_distill_maintenance_offer(
    monkeypatch,
) -> None:
    offer = {
        "contract_version": "agent-distill-offer-v2",
        "agent_execution_required": True,
        "process_limit": 2,
        "job_ids": ["job-1", "job-2"],
        "distill_job_id": "job-1",
        "execution_order": "sequential",
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
    assert payload["distill_maintenance"]["job_ids"] == ["job-1", "job-2"]
    assert payload["distill_maintenance"]["distill_job_id"] == "job-1"
    assert payload["distill_maintenance"]["prepare_arguments"]["run_ingest"] is False


def test_wake_uses_default_two_job_batch_and_configured_distill_budget(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".harness-mem.toml").write_text(
        "[cost_budget]\ndistill_tokens = 6400\n",
        encoding="utf-8",
    )
    backend = LocalMemoryBackend(tmp_path / "data")

    async def run() -> None:
        await backend.init()
        try:
            for index in range(3):
                await persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=f"wake-batch-{index}",
                        client="codex",
                        raw_content=f"User: request {index}\n\nAssistant: done {index}",
                        content_type="transcript",
                        metadata={},
                    ),
                    project_name="demo",
                    project_root=str(project),
                    client="codex",
                    session_id=f"wake-batch-{index}",
                    source_kind="jsonl",
                    source_uri=f"file:///wake-batch-{index}.jsonl",
                    source_text=f"source {index}",
                )
            offer = wake._build_distill_maintenance_offer(
                backend,
                "demo",
                record_offer=True,
            )

            assert offer["contract_version"] == "agent-distill-offer-v2"
            assert offer["process_limit"] == 2
            assert len(offer["job_ids"]) == 2
            assert offer["prepare_arguments"]["budget_tokens"] == 6400
            assert "budget_tokens=6400" in offer["instruction"]
        finally:
            await backend.close()

    asyncio.run(run())
