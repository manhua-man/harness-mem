from __future__ import annotations

import asyncio
import json
from pathlib import Path

import harness_mem.adapters.hermes.adapter as hermes_adapter_module
import harness_mem.commands.ingest as ingest_module
import harness_mem.commands.support as support_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.parser import parse_hermes_json_session
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _write_hermes_session(
    sessions_dir: Path,
    session_id: str,
    *,
    workspace_text: str,
) -> Path:
    session_path = sessions_dir / f"{session_id}.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Inspect this workspace: {workspace_text}",
                    },
                    {
                        "role": "assistant",
                        "content": "I will inspect the files.",
                        "reasoning": "internal reasoning should not be stored",
                        "reasoning_content": "internal reasoning should not be stored",
                        "finish_reason": "stop",
                        "codex_message_items": [
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"path": "README.md"},
                            }
                        ],
                    },
                ],
                "message_count": 2,
            }
        ),
        encoding="utf-8",
    )
    return session_path


def test_parse_hermes_json_session_reads_messages_and_tools(tmp_path: Path) -> None:
    session_path = _write_hermes_session(
        tmp_path,
        "session_20260711_abcd",
        workspace_text="F:/AIInfra/harness-mem",
    )

    turns = parse_hermes_json_session(session_path)

    assert len(turns) == 1
    assert turns[0]["user"] == "Inspect this workspace: F:/AIInfra/harness-mem"
    assert turns[0]["assistant"] == ["I will inspect the files."]
    assert turns[0]["tools"][0]["name"] == "Read"
    assert "internal reasoning" not in json.dumps(turns, ensure_ascii=False)


def test_hermes_adapter_lists_project_scoped_sessions_by_workspace_mention(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / ".hermes" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    matching = _write_hermes_session(
        sessions_dir,
        "session_20260711_match",
        workspace_text=str(workspace.resolve()),
    )
    _write_hermes_session(
        sessions_dir,
        "session_20260711_other",
        workspace_text="E:/project/other",
    )

    adapter = HermesAdapter(
        None,
        sessions_dir=sessions_dir,
        project_root=workspace,
        scope="project",
    )
    sessions = adapter.list_sessions(project_name="harness-mem", min_size_kb=0)

    assert len(sessions) == 1
    assert sessions[0]["path"] == matching
    assert sessions[0]["session_id"] == "session_20260711_match"


def test_hermes_adapter_scope_all_lists_unmatched_sessions(tmp_path: Path) -> None:
    sessions_dir = tmp_path / ".hermes" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    _write_hermes_session(
        sessions_dir,
        "session_20260711_other",
        workspace_text="E:/project/other",
    )

    adapter = HermesAdapter(
        None,
        sessions_dir=sessions_dir,
        project_root=workspace,
        scope="all",
    )
    sessions = adapter.list_sessions(project_name="harness-mem", min_size_kb=0)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session_20260711_other"


def test_hermes_adapter_session_to_observation(tmp_path: Path) -> None:
    sessions_dir = tmp_path / ".hermes" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    session_path = _write_hermes_session(
        sessions_dir,
        "session_20260711_match",
        workspace_text=str(workspace.resolve()),
    )

    adapter = HermesAdapter(
        None,
        sessions_dir=sessions_dir,
        project_root=workspace,
        scope="project",
    )
    observation = adapter.session_to_observation(
        session_path,
        "session_20260711_match",
        "harness-mem",
    )

    assert observation.client == "hermes"
    assert observation.session_id == "session_20260711_match"
    assert "# Hermes Session: session_20260711_match" in observation.raw_content
    assert "User: Inspect this workspace:" in observation.raw_content
    assert "Assistant: I will inspect the files." in observation.raw_content
    assert "Tools: Read" in observation.raw_content
    assert "internal reasoning" not in observation.raw_content
    assert observation.metadata["project_name"] == "harness-mem"
    assert observation.metadata["project_root"] == str(workspace.resolve())
    assert observation.metadata["scope"] == "project"


def test_tool_ingest_sessions_hermes_uses_project_root_and_reports_resolved_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / ".hermes" / "sessions"
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    _write_hermes_session(
        sessions_dir,
        "session_20260711_match",
        workspace_text=str(workspace.resolve()),
    )

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(hermes_adapter_module, "DEFAULT_SESSIONS_DIR", sessions_dir)

    payload = tool_handlers.tool_ingest_sessions(
        client="hermes",
        project_root=str(workspace),
    )

    assert payload["success"] is True
    assert payload["project_name"] == "harness-mem"
    assert payload["resolved_client"] == "hermes"
    assert payload["host_client"] == "hermes"
    assert payload["source_kind"] == "transcript"
    assert payload["adapter_available"] is True
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
    assert observations[0].client == "hermes"
