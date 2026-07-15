from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.integration_health import build_integration_health
from harness_mem.hook_receipts import record_hook_execution
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_integration_health_summarizes_current_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    hook_dir = workspace / ".cursor" / "hooks"
    hook_dir.mkdir(parents=True)
    (hook_dir / "session-start.sh").write_text("wake", encoding="utf-8")
    (hook_dir / "after-agent.sh").write_text("maintain", encoding="utf-8")
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "cursor")

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await persist_session_snapshot(
                backend,
                Observation(
                    session_id="cursor-session",
                    client="cursor",
                    raw_content="User: inspect integration health",
                    content_type="transcript",
                    metadata={"project_name": "project"},
                ),
                project_name="project",
                project_root=str(workspace),
                client="cursor",
                session_id="cursor-session",
                source_kind="jsonl",
                source_uri="file:///cursor-session.jsonl",
                source_text="User: inspect integration health\n",
            )
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())

    assert health["project"]["status"] == "ok"
    assert health["host"]["client"] == "cursor"
    assert health["hooks"]["status"] == "ok"
    assert health["transcript"]["status"] == "synced"
    assert health["transcript"]["session_count"] == 1
    assert health["transcript"]["latest_source_coverage"] == "complete"
    assert health["pending_distill"] == {
        "status": "queued",
        "queued": 1,
        "processing": 0,
        "completed_chunks": 0,
        "expected_chunks": 1,
        "legacy_audit_only": 0,
    }
    assert health["summary"].startswith("project=ok | host=cursor | hooks=ok (2/2)")


def test_integration_health_does_not_guess_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)

    async def run() -> dict:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            return await build_integration_health(
                backend,
                project_name="project",
                project_root=tmp_path,
            )
        finally:
            await backend.close()

    health = asyncio.run(run())
    assert health["host"] == {"status": "unknown", "client": "unknown"}
    assert health["hooks"]["status"] == "unknown"
    assert health["transcript"]["status"] == "unknown"


def test_codex_health_requires_current_hook_execution_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    hook_path = workspace / ".codex" / "hooks.json"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text('{"hooks":{"SessionStart":[],"Stop":[]}}\n', encoding="utf-8")
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")

    async def run() -> tuple[dict, dict]:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            before = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            record_hook_execution(
                backend.data_dir,
                project_root=workspace,
                project_name="project",
                client="codex",
                action="wake-start",
                source="ide_hook",
                trigger_id="session-1",
            )
            after = await build_integration_health(
                backend,
                project_name="project",
                project_root=workspace,
            )
            return before, after
        finally:
            await backend.close()

    before, after = asyncio.run(run())

    assert before["hooks"]["status"] == "review_required"
    assert before["hooks"]["wake_verified"] is False
    assert "Settings > Hooks" in before["hooks"]["action_required"]
    assert after["hooks"]["status"] == "ok"
    assert after["hooks"]["wake_verified"] is True
    assert after["hooks"]["action_required"] is None
