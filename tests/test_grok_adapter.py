from __future__ import annotations

import asyncio
from pathlib import Path

import harness_mem.adapters.grok.adapter as grok_adapter_module
import harness_mem.commands.ingest as ingest_module
import harness_mem.commands.support as support_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.adapters.grok.adapter import GrokAdapter, grok_project_bucket
from harness_mem.adapters.parser import parse_grok_jsonl_session
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


def _grok_records() -> list[dict]:
    return [
        {"type": "system", "content": "system prompt"},
        {
            "type": "user",
            "content": [{"type": "text", "text": "Please inspect this repo."}],
        },
        {
            "type": "assistant",
            "content": "I will read the files.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "Read",
                    "arguments": '{"path":"README.md"}',
                }
            ],
        },
        {"type": "assistant", "content": "The repo uses Python."},
    ]


def _write_grok_session(sessions_dir: Path, workspace: Path, session_id: str) -> Path:
    chat_history = (
        sessions_dir
        / grok_project_bucket(workspace.resolve())
        / session_id
        / "chat_history.jsonl"
    )
    write_jsonl(chat_history, _grok_records())
    return chat_history


def test_parse_grok_jsonl_session_reads_content_and_tools(tmp_path: Path) -> None:
    session_path = tmp_path / "chat_history.jsonl"
    write_jsonl(session_path, _grok_records())

    turns = parse_grok_jsonl_session(session_path)

    assert len(turns) == 1
    assert turns[0]["user"] == "Please inspect this repo."
    assert turns[0]["assistant"] == [
        "I will read the files.",
        "The repo uses Python.",
    ]
    assert turns[0]["tools"][0]["name"] == "Read"


def test_grok_adapter_lists_sessions_from_encoded_project_bucket(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / ".grok" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    _write_grok_session(sessions_dir, workspace, "session-1")

    adapter = GrokAdapter(None, sessions_dir=sessions_dir, project_root=workspace)
    sessions = adapter.list_sessions(project_name="harness-mem", min_size_kb=0)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-1"
    assert sessions[0]["path"].name == "chat_history.jsonl"


def test_grok_adapter_session_to_observation(tmp_path: Path) -> None:
    sessions_dir = tmp_path / ".grok" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    chat_history = _write_grok_session(sessions_dir, workspace, "session-1")

    adapter = GrokAdapter(None, sessions_dir=sessions_dir, project_root=workspace)
    observation = adapter.session_to_observation(
        chat_history,
        "session-1",
        "harness-mem",
    )

    assert observation.client == "grok"
    assert observation.session_id == "session-1"
    assert "# Grok Session: session-1" in observation.raw_content
    assert "User: Please inspect this repo." in observation.raw_content
    assert "Assistant: I will read the files." in observation.raw_content
    assert "Tools: Read" in observation.raw_content
    assert observation.metadata["project_name"] == "harness-mem"
    assert observation.metadata["project_root"] == str(workspace.resolve())


def test_tool_ingest_sessions_grok_uses_project_root_and_reports_resolved_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / ".grok" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    _write_grok_session(sessions_dir, workspace, "session-1")

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(grok_adapter_module, "DEFAULT_SESSIONS_DIR", sessions_dir)

    payload = tool_handlers._ingest_sessions(
        client="grok",
        project_root=str(workspace),
    )

    assert payload["success"] is True
    assert payload["project_name"] == "harness-mem"
    assert payload["resolved_client"] == "grok"
    assert payload["host_client"] == "grok"
    assert payload["source_kind"] == "transcript"
    assert "Ingested: 1 sessions" in payload["output"]

    async def _load() -> list:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            return await backend.verbatim_store.list(limit=10)
        finally:
            await backend.close()

    observations = asyncio.run(_load())
    assert len(observations) == 1
    assert observations[0].client == "grok"
