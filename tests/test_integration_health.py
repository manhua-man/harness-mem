from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.integration_health import build_integration_health
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
