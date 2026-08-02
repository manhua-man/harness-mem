from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


def _write_session(path: Path, turns: int) -> None:
    rows = []
    for index in range(turns):
        rows.extend(
            [
                {
                    "type": "user",
                    "message": {"content": f"request-{index}-" + "u" * 700},
                },
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": f"answer-{index}-" + "a" * 700}
                        ],
                        "stop_reason": "end_turn",
                    },
                },
            ]
        )
    write_jsonl(path, rows)


def test_claude_growing_session_updates_lossless_revision(tmp_path: Path) -> None:
    async def exercise() -> None:
        sessions_root = tmp_path / "sessions"
        project_dir = sessions_root / "demo"
        project_dir.mkdir(parents=True)
        session_path = project_dir / "session-1.jsonl"
        _write_session(session_path, 25)
        first_bytes = session_path.read_bytes()

        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = ClaudeCodeAdapter(backend, sessions_dir=sessions_root)
            first = await adapter.sync_session(
                session_path,
                "session-1",
                "demo",
                project_root=tmp_path / "project",
            )
            _write_session(session_path, 26)
            second_bytes = session_path.read_bytes()
            second = await adapter.sync_session(
                session_path,
                "session-1",
                "demo",
                project_root=tmp_path / "project",
            )

            assert first.action == "ingested"
            assert second.action == "updated"
            assert (
                backend.transcript_store.reconstruct_raw(
                    first.source.id,
                    source_revision=first.source.source_revision,
                )
                == first_bytes
            )
            assert (
                backend.transcript_store.reconstruct_raw(second.source.id)
                == second_bytes
            )
            observation = await backend.verbatim_store.get(second.observation_id)
            assert observation is not None
            assert "request-0-" in observation.raw_content
            assert "request-25-" in observation.raw_content
            assert "middle turns omitted" not in observation.raw_content
            assert "[TRUNCATED]" not in observation.raw_content
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_claude_adapter_does_not_read_another_project_directory(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    wanted = sessions_root / "wanted"
    other = sessions_root / "other"
    wanted.mkdir(parents=True)
    other.mkdir(parents=True)
    _write_session(wanted / "wanted.jsonl", 1)
    _write_session(other / "other.jsonl", 1)

    adapter = ClaudeCodeAdapter(None, sessions_dir=sessions_root)

    assert [
        item["session_id"] for item in adapter.list_sessions("wanted", min_size_kb=0)
    ] == ["wanted"]
