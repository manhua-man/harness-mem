"""Minimal native transcript fixtures for offline host qualification only."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from harness_mem.adapters.antigravity import AntigravityAdapter
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.cursor.adapter import (
    CursorAdapter,
    cursor_project_name_candidates_from_path,
)
from harness_mem.adapters.grok.adapter import GrokAdapter, grok_project_bucket
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.opencode import OpenCodeAdapter
from harness_mem.adapters.protocol import SessionAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

QUALIFICATION_HOSTS = (
    "claude-code",
    "codex",
    "cursor",
    "grok",
    "hermes",
    "opencode",
    "antigravity",
)


def build_native_fixture_adapter(
    host: str,
    *,
    root: Path,
    backend: LocalMemoryBackend,
    project: Path,
    project_name: str,
    fact: str,
) -> SessionAdapter:
    """Create one deterministic native fixture and its real adapter."""

    if host == "claude-code":
        sessions = root / "claude-sessions"
        _write_jsonl(
            sessions / project_name / "claude-session.jsonl",
            [
                {"type": "user", "message": {"content": fact}},
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Recorded."}]},
                },
            ],
        )
        return ClaudeCodeAdapter(backend, sessions_dir=sessions)

    if host == "codex":
        sessions = root / "codex-sessions"
        _write_jsonl(
            sessions / "2026" / "08" / "02" / "rollout-codex-session.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {"id": "codex-session", "cwd": str(project)},
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "user_message",
                        "message": fact,
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Recorded."}],
                    },
                },
            ],
        )
        return CodexAdapter(
            backend,
            sessions_dir=sessions,
            archive_dir=root / "codex-archive",
            project_root=project,
        )

    if host == "cursor":
        projects = root / "cursor-projects"
        bucket = cursor_project_name_candidates_from_path(project)[0]
        _write_jsonl(
            projects / bucket / "agent-transcripts" / "cursor-session" / "session.jsonl",
            [
                {
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": fact}]},
                },
                {
                    "role": "assistant",
                    "message": {"content": [{"type": "text", "text": "Recorded."}]},
                },
                {"type": "turn_ended", "status": "success"},
            ],
        )
        return CursorAdapter(backend, projects_dir=projects, project_root=project)

    if host == "grok":
        sessions = root / "grok-sessions"
        _write_jsonl(
            sessions
            / grok_project_bucket(project.resolve())
            / "grok-session"
            / "chat_history.jsonl",
            [
                {"type": "user", "content": [{"type": "text", "text": fact}]},
                {"type": "assistant", "content": "Recorded."},
            ],
        )
        return GrokAdapter(backend, sessions_dir=sessions, project_root=project)

    if host == "hermes":
        sessions = root / "hermes-sessions"
        session = sessions / "session_qualification.json"
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text(
            json.dumps(
                {
                    "session_id": "session_qualification",
                    "messages": [
                        {"role": "user", "content": f"{fact} in {project.resolve()}"},
                        {"role": "assistant", "content": "Recorded."},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return HermesAdapter(
            backend,
            sessions_dir=sessions,
            project_root=project,
            scope="project",
        )

    if host == "opencode":
        resolved_project = project.resolve(strict=False)
        database = root / "opencode.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as db:
            db.executescript(
                """
                CREATE TABLE session (
                    id TEXT PRIMARY KEY, directory TEXT NOT NULL, title TEXT NOT NULL,
                    time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL
                );
                CREATE TABLE message (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    time_created INTEGER NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE part (
                    id TEXT PRIMARY KEY, message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, data TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?)",
                ("opencode-session", str(resolved_project), "Qualification", 1, 2),
            )
            db.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?)",
                ("message-user", "opencode-session", 1, json.dumps({"role": "user"})),
            )
            db.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?)",
                (
                    "part-user",
                    "message-user",
                    "opencode-session",
                    json.dumps({"type": "text", "text": fact}),
                ),
            )
            db.commit()
        return OpenCodeAdapter(backend, database_path=database, project_root=project)

    if host == "antigravity":
        resolved_project = project.resolve(strict=False)
        brain = root / "antigravity-brain"
        transcript = (
            brain
            / "antigravity-session"
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )
        _write_jsonl(
            transcript,
            [
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": fact,
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "list_dir", "args": {"Cwd": str(resolved_project)}}
                    ],
                },
            ],
        )
        return AntigravityAdapter(backend, brain_dir=brain, project_root=project)

    raise ValueError(f"unsupported qualification host: {host}")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


__all__ = ["QUALIFICATION_HOSTS", "build_native_fixture_adapter"]
