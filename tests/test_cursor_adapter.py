from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import harness_mem.adapters.cursor.adapter as cursor_adapter_module
import harness_mem.commands.ingest as ingest_module
import harness_mem.commands.support as support_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.adapters.cursor.adapter import (
    CursorAdapter,
    cursor_project_name_candidates_from_path,
)
from harness_mem.adapters.parser import parse_cursor_jsonl_session
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _cursor_records_for_workspace(workspace: Path) -> list[dict]:
    workspace_text = str(workspace)
    return [
        {
            "role": "user",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "<user_query>\nInspect this workspace.\n</user_query>",
                    }
                ]
            },
        },
        {
            "role": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "Reading files from the requested workspace.",
                    },
                    {
                        "type": "tool_use",
                        "name": "Glob",
                        "input": {
                            "glob_pattern": "**/*.py",
                            "target_directory": workspace_text,
                        },
                    },
                ]
            },
        },
        {
            "type": "turn_ended",
            "status": "success",
        },
    ]


def test_cursor_project_name_candidates_from_path() -> None:
    candidates = cursor_project_name_candidates_from_path(Path("F:/AIInfra/harness-mem"))
    assert "f-AIInfra-harness-mem" in candidates


def test_parse_cursor_jsonl_session_reads_role_message_content(tmp_path: Path) -> None:
    session_path = tmp_path / "cursor.jsonl"
    _write_jsonl(
        session_path,
        [
            {
                "role": "user",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            },
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "hi there"},
                        {"type": "tool_use", "name": "Read", "input": {"path": "demo.py"}},
                    ]
                },
            },
            {"type": "turn_ended", "status": "success"},
        ],
    )

    turns = parse_cursor_jsonl_session(session_path)

    assert len(turns) == 1
    assert turns[0]["user"] == "hello"
    assert turns[0]["assistant"] == ["hi there"]
    assert turns[0]["tools"][0]["name"] == "Read"


def test_cursor_adapter_lists_sessions_from_slugged_project_dir(tmp_path: Path) -> None:
    projects_dir = tmp_path / ".cursor-projects"
    workspace = Path("F:/AIInfra/harness-mem")
    slug = "f-AIInfra-harness-mem"
    session_path = (
        projects_dir
        / slug
        / "agent-transcripts"
        / "session-1"
        / "session-1.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    adapter = CursorAdapter(None, projects_dir=projects_dir, project_root=workspace)
    sessions = adapter.list_sessions(project_name="harness-mem", min_size_kb=0)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-1"


def test_cursor_adapter_falls_back_to_transcript_content_match(tmp_path: Path) -> None:
    projects_dir = tmp_path / ".cursor-projects"
    workspace = Path("E:/project/servers")
    session_path = (
        projects_dir
        / "1776580358888"
        / "agent-transcripts"
        / "session-2"
        / "session-2.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    adapter = CursorAdapter(None, projects_dir=projects_dir, project_root=workspace)
    sessions = adapter.list_sessions(project_name="servers", min_size_kb=0)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-2"


def test_tool_ingest_sessions_cursor_uses_project_root_and_reports_resolved_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    projects_dir = tmp_path / ".cursor-projects"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    slug = next(
        candidate
        for candidate in cursor_project_name_candidates_from_path(workspace)
        if candidate.lower() != workspace.name.lower()
    )
    session_path = (
        projects_dir
        / slug
        / "agent-transcripts"
        / "cursor-session"
        / "cursor-session.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(cursor_adapter_module, "DEFAULT_PROJECTS_DIR", projects_dir)

    payload = tool_handlers.tool_ingest_sessions(
        project_name="servers",
        client="cursor",
        project_root=str(workspace),
    )

    assert payload["success"] is True
    assert payload["resolved_client"] == "cursor"
    assert payload["host_client"] == "cursor"
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
    assert observations[0].client == "cursor"


def test_tool_ingest_sessions_cursor_resolves_project_from_project_root_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    projects_dir = tmp_path / ".cursor-projects"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    slug = next(
        candidate
        for candidate in cursor_project_name_candidates_from_path(workspace)
        if candidate.lower() != workspace.name.lower()
    )
    session_path = (
        projects_dir
        / slug
        / "agent-transcripts"
        / "cursor-session"
        / "cursor-session.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(cursor_adapter_module, "DEFAULT_PROJECTS_DIR", projects_dir)

    payload = tool_handlers.tool_ingest_sessions(
        client="cursor",
        project_root=str(workspace),
    )

    assert payload["success"] is True
    assert payload["project_name"] == "servers"
    assert payload["project_root"] == str(workspace.resolve())
    assert payload["project_resolution_source"] == "project_root"
    assert payload["resolved_client"] == "cursor"
    assert "Ingested: 1 sessions" in payload["output"]


def test_tool_ingest_sessions_cursor_skips_existing_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    projects_dir = tmp_path / ".cursor-projects"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    slug = next(
        candidate
        for candidate in cursor_project_name_candidates_from_path(workspace)
        if candidate.lower() != workspace.name.lower()
    )
    session_path = (
        projects_dir
        / slug
        / "agent-transcripts"
        / "cursor-session"
        / "cursor-session.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(cursor_adapter_module, "DEFAULT_PROJECTS_DIR", projects_dir)

    first = tool_handlers.tool_ingest_sessions(
        client="cursor",
        project_root=str(workspace),
    )
    second = tool_handlers.tool_ingest_sessions(
        client="cursor",
        project_root=str(workspace),
    )

    assert first["success"] is True
    assert second["success"] is True
    assert "Ingested: 1 sessions" in first["output"]
    assert "Ingested: 0 sessions" in second["output"]
    assert "Skipped existing: 1 sessions" in second["output"]

    async def _load() -> list:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            return await backend.verbatim_store.list(limit=10)
        finally:
            await backend.close()

    observations = asyncio.run(_load())
    assert len(observations) == 1


def test_tool_prepare_session_distill_cursor_resolves_project_from_project_root_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    projects_dir = tmp_path / ".cursor-projects"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    slug = next(
        candidate
        for candidate in cursor_project_name_candidates_from_path(workspace)
        if candidate.lower() != workspace.name.lower()
    )
    session_path = (
        projects_dir
        / slug
        / "agent-transcripts"
        / "cursor-session"
        / "cursor-session.jsonl"
    )
    _write_jsonl(session_path, _cursor_records_for_workspace(workspace))

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(tool_handlers._support, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(cursor_adapter_module, "DEFAULT_PROJECTS_DIR", projects_dir)

    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger

    backend = LocalMemoryBackend(data_dir)
    asyncio.run(backend.init())
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test_tool_handlers"),
    )
    try:
        payload = tool_handlers.tool_prepare_session_distill(
            client="cursor",
            project_root=str(workspace),
        )
    finally:
        tool_handlers._backend_provider = previous_backend_provider
        tool_handlers._observer_data_dir_provider = previous_observer_provider
        tool_handlers._cost_surface_budgets_provider = previous_cost_provider
        tool_handlers.logger = previous_logger
        asyncio.run(backend.close())

    assert payload["success"] is True
    assert payload["project_name"] == "servers"
    assert payload["project_root"] == str(workspace.resolve())
    assert payload["project_resolution_source"] == "project_root"
    assert payload["resolved_client"] == "cursor"
    assert payload["observation_count"] == 1
    assert payload["observations"][0]["client"] == "cursor"
    assert payload["distill_job_id"]
    assert payload["distill_status"] == "processing"
