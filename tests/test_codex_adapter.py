from __future__ import annotations

import asyncio
import json
from pathlib import Path

import harness_mem.adapters.codex.adapter as codex_adapter_module
import harness_mem.commands.ingest as ingest_module
import harness_mem.commands.support as support_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.parser import parse_codex_archive_jsonl_session
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _codex_records_for_workspace(workspace: Path, *, session_id: str = "codex-session") -> list[dict]:
    return [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(workspace),
                "timestamp": "2026-07-09T00:00:00Z",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "# AGENTS.md instructions\n\n<environment_context>noise</environment_context>",
                    }
                ],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "turn_id": "turn-1",
                "type": "user_message",
                "message": "Please inspect the Codex workspace transcript.",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "The Codex workspace transcript was parsed.",
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "function_call",
                "name": "shell_command",
                "arguments": "{\"command\":\"git status --short\"}",
            },
        },
    ]


def test_parse_codex_rollout_reads_current_response_items(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_path = tmp_path / "rollout-2026-07-09T00-00-00-codex-session.jsonl"
    _write_jsonl(session_path, _codex_records_for_workspace(workspace))

    meta, turns = parse_codex_archive_jsonl_session(session_path)

    assert meta["session_id"] == "codex-session"
    assert meta["cwd"] == str(workspace)
    assert len(turns) == 1
    assert turns[0]["user"] == "Please inspect the Codex workspace transcript."
    assert turns[0]["assistant"] == ["The Codex workspace transcript was parsed."]
    assert turns[0]["tools"][0]["name"] == "shell_command"


def test_codex_adapter_filters_sessions_by_project_root(tmp_path: Path) -> None:
    sessions_dir = tmp_path / ".codex" / "sessions"
    workspace = tmp_path / "servers"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()

    _write_jsonl(
        sessions_dir / "2026" / "07" / "09" / "rollout-2026-07-09T00-00-00-match.jsonl",
        _codex_records_for_workspace(workspace, session_id="match"),
    )
    _write_jsonl(
        sessions_dir / "2026" / "07" / "09" / "rollout-2026-07-09T00-00-01-other.jsonl",
        _codex_records_for_workspace(other_workspace, session_id="other"),
    )

    adapter = CodexAdapter(None, sessions_dir=sessions_dir, project_root=workspace)
    project_sessions = adapter.list_sessions(min_size_kb=0)
    all_sessions = adapter.list_sessions(min_size_kb=0, scope="all")

    assert [session["session_id"] for session in project_sessions] == ["match"]
    assert {session["session_id"] for session in all_sessions} == {"match", "other"}


def test_tool_ingest_sessions_codex_uses_project_root_and_reports_resolved_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / ".codex" / "sessions"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    _write_jsonl(
        sessions_dir / "2026" / "07" / "09" / "rollout-2026-07-09T00-00-00-codex-session.jsonl",
        _codex_records_for_workspace(workspace),
    )

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(codex_adapter_module, "DEFAULT_SESSIONS_DIR", sessions_dir)

    payload = tool_handlers._ingest_sessions(
        client="codex",
        project_root=str(workspace),
    )

    assert payload["success"] is True
    assert payload["project_name"] == "servers"
    assert payload["project_root"] == str(workspace.resolve())
    assert payload["project_resolution_source"] == "project_root"
    assert payload["resolved_client"] == "codex"
    assert payload["host_client"] == "codex"
    assert payload["source_kind"] == "transcript"
    assert "Project-scope sessions: 1" in payload["output"]
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
    assert observations[0].client == "codex"
    assert observations[0].metadata["project_name"] == "servers"
    assert observations[0].metadata["cwd"] == str(workspace)
    assert "Please inspect the Codex workspace transcript." in observations[0].raw_content
    assert "# AGENTS.md instructions" not in observations[0].raw_content
