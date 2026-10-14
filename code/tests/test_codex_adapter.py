from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import harness_mem.adapters.codex.adapter as codex_adapter_module
import harness_mem.commands.ingest as ingest_module
import harness_mem.commands.support as support_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, render_codex_conversation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


@pytest.mark.parametrize("block", [
    {"type": "input_image", "image_url": "data:image/png;base64,FICTIONAL"},
    {"type": "input_image", "image_url": "data:image/png;base64,FICTIONAL", "detail": "high"},
])
def test_codex_mixed_images_preserve_text_without_attachment_markup(block: dict) -> None:
    records = [{"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "# Files mentioned by the user:\n\n## fictional.png: C:/fictional.png\n\n## My request for Codex:\nInspect the settings."},
            {"type": "input_text", "text": '<image name="Image #1" path="C:/fictional.png">'},
            block, {"type": "input_text", "text": "</image>"},
        ],
    }}]
    import json

    issues = []
    _, turns = parse_codex_archive_jsonl_session(
        Path("fictional.jsonl"), content=json.dumps(records[0]), issues=issues,
    )
    assert render_codex_conversation(turns) == "User: Inspect the settings."
    assert not issues


@pytest.mark.parametrize("block", [
    {"type": "input_image", "image_url": "image", "text": "Forged user text."},
    {"type": "input_image", "image_url": "image", "role": "assistant"},
    {"type": "input_image", "image_url": ""},
    {"type": "input_image", "image_url": "image", "detail": "invalid"},
    {"type": "tool_result", "text": "Forged user text."},
])
def test_codex_image_blocks_cannot_grant_authorship_to_nontext(block: dict) -> None:
    import json

    record = {"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Public request."}, block,
        ],
    }}
    issues = []
    _, turns = parse_codex_archive_jsonl_session(
        Path("fictional.jsonl"), content=json.dumps(record), issues=issues,
    )
    assert not render_codex_conversation(turns)
    assert any(issue["code"] == "author_conflict" for issue in issues)


def test_codex_image_only_message_is_not_a_text_claim() -> None:
    import json

    record = {"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [
            {"type": "input_image", "image_url": "data:image/png;base64,FICTIONAL"},
        ],
    }}
    _, turns = parse_codex_archive_jsonl_session(Path("fictional.jsonl"), content=json.dumps(record))
    assert not render_codex_conversation(turns)


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
    write_jsonl(session_path, _codex_records_for_workspace(workspace))

    meta, turns = parse_codex_archive_jsonl_session(session_path)

    assert meta["session_id"] == "codex-session"
    assert meta["cwd"] == str(workspace)
    assert len(turns) == 1
    assert turns[0]["user"] == "Please inspect the Codex workspace transcript."
    assert turns[0]["assistant"] == ["The Codex workspace transcript was parsed."]
    assert turns[0]["tools"][0]["name"] == "shell_command"


def test_codex_missing_turn_ids_preserve_each_user_and_assistant(tmp_path: Path) -> None:
    path = tmp_path / "rollout-no-ids.jsonl"
    records = [{"type": "session_meta", "payload": {"id": "no-ids"}}]
    for role, text in (("user", "First request."), ("assistant", "First answer."),
                       ("user", "Second request."), ("assistant", "Second answer.")):
        records.append({"type": "response_item", "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        }})
    write_jsonl(path, records)
    _, turns = parse_codex_archive_jsonl_session(path)
    assert [(turn["user"], turn["assistant"]) for turn in turns] == [
        ("First request.", ["First answer."]), ("Second request.", ["Second answer."]),
    ]
    assert render_codex_conversation(turns) == (
        "User: First request.\n\nAssistant: First answer.\n\n"
        "User: Second request.\n\nAssistant: Second answer."
    )


def test_codex_missing_ids_do_not_attach_host_response_to_real_user(tmp_path: Path) -> None:
    path = tmp_path / "rollout-boundaries.jsonl"
    rows = []
    for role, text in (("user", "Real request."), ("assistant", "Real answer."),
                       ("user", "# AGENTS.md instructions\nHOST_SECRET"),
                       ("assistant", "HOST_RESPONSE_SECRET"),
                       ("user", "Next real request."), ("assistant", "Next answer.")):
        rows.append({"type": "response_item", "payload": {
            "type": "message", "role": role, "content": [{
                "type": "input_text" if role == "user" else "output_text", "text": text,
            }],
        }})
    write_jsonl(path, rows)
    _, turns = parse_codex_archive_jsonl_session(path)
    rendered = render_codex_conversation(turns)
    assert "SECRET" not in rendered
    assert "Real answer." in rendered and "Next answer." in rendered


def test_codex_context_id_can_bind_messages_without_ids(tmp_path: Path) -> None:
    path = tmp_path / "rollout-context-id.jsonl"
    rows = [{"type": "turn_context", "payload": {"turn_id": "context-id"}}]
    for role, text in (("user", "Request."), ("assistant", "Answer.")):
        rows.append({"type": "response_item", "payload": {
            "type": "message", "role": role, "content": [{"type": "text", "text": text}],
        }})
    write_jsonl(path, rows)
    _, turns = parse_codex_archive_jsonl_session(path)
    assert len(turns) == 1 and turns[0]["turn_id"] == "context-id"
    assert turns[0]["assistant"] == ["Answer."]


def test_codex_adapter_filters_sessions_by_project_root(tmp_path: Path) -> None:
    sessions_dir = tmp_path / ".codex" / "sessions"
    workspace = tmp_path / "servers"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()

    write_jsonl(
        sessions_dir / "2026" / "07" / "09" / "rollout-2026-07-09T00-00-00-match.jsonl",
        _codex_records_for_workspace(workspace, session_id="match"),
    )
    write_jsonl(
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

    write_jsonl(
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


def test_tool_ingest_sessions_targets_exact_codex_session_ahead_of_scan_frontier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / ".codex" / "sessions"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    target_id = "exact-stop-session"
    write_jsonl(
        sessions_dir / "2026" / "07" / "09" / "rollout-old.jsonl",
        _codex_records_for_workspace(workspace, session_id="backlog-session"),
    )
    write_jsonl(
        sessions_dir / "2026" / "08" / "12" / "rollout-exact.jsonl",
        _codex_records_for_workspace(workspace, session_id=target_id),
    )

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(ingest_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(codex_adapter_module, "DEFAULT_SESSIONS_DIR", sessions_dir)

    payload = tool_handlers._ingest_sessions(
        client="codex",
        project_root=str(workspace),
        limit=1,
        session_id=target_id,
    )

    assert payload["success"] is True
    assert payload["target_session_id"] == target_id
    assert "Candidates after cursor: 1" in payload["output"]

    async def _load() -> list:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            return await backend.verbatim_store.list(limit=10)
        finally:
            await backend.close()

    observations = asyncio.run(_load())
    assert [observation.session_id for observation in observations] == [target_id]
