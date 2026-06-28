from __future__ import annotations

import argparse
import asyncio
import json

import harness_mem.commands.dream as dream_module
import harness_mem.commands.wake as wake_module
import harness_mem.host_entry.__main__ as host_entry
import harness_mem.storage.local_memory_backend as backend_module
from harness_mem.config.merge import MergedConfig
from harness_mem.host_entry.exit_codes import ExitCode


class FakeBackend:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _args(tmp_path, action: str) -> argparse.Namespace:
    return argparse.Namespace(
        action=action,
        project_root=str(tmp_path),
        source="ide_hook",
        trigger_id="turn-1",
    )


def test_host_entry_wake_start_outputs_wake_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)

    async def fake_wake(_backend, project_name: str) -> str:
        return f"Wake context for {project_name}"

    async def fail_dream(*_args, **_kwargs):
        raise AssertionError("wake-start must not run dream")

    monkeypatch.setattr(wake_module, "build_wake_injection", fake_wake)
    monkeypatch.setattr(dream_module, "dream_auto_tick", fail_dream)

    code, payload = asyncio.run(host_entry.run(_args(tmp_path, "wake-start")))

    assert code == ExitCode.SUCCESS
    assert payload == f"Wake context for {tmp_path.name}"


def test_host_entry_dream_end_outputs_dream_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)

    async def fake_dream(_backend, *, project_name: str, **_kwargs):
        return {
            "success": True,
            "status": "completed",
            "project_name": project_name,
            "job_id": "job-1",
            "summary": {"processed": 2},
        }

    async def fail_wake(*_args, **_kwargs):
        raise AssertionError("dream-end must not render wake")

    monkeypatch.setattr(dream_module, "dream_auto_tick", fake_dream)
    monkeypatch.setattr(wake_module, "build_wake_injection", fail_wake)

    code, payload = asyncio.run(host_entry.run(_args(tmp_path, "dream-end")))
    assert code == ExitCode.SUCCESS

    data = json.loads(payload or "{}")
    assert data["action"] == "dream-end"
    assert data["status"] == "completed"
    assert data["items_processed"] == 2
    assert "reflection" not in payload.lower()
    assert "metabolism" not in payload.lower()
