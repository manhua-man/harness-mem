from __future__ import annotations

import asyncio
import json
from pathlib import Path

from harness_mem import cli
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.core.schemas import MemoryEntry, Observation


def run(coro):
    return asyncio.run(coro)


def read_events(data_dir: Path) -> list[dict]:
    events_path = data_dir / "events.log"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_claude_session(
    sessions_root: Path,
    project_name: str,
    session_id: str,
    user_text: str,
    assistant_texts: list[str],
) -> Path:
    project_dir = sessions_root / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    session_path = project_dir / f"{session_id}.jsonl"
    records = [
        {"type": "user", "message": {"content": user_text}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": text} for text in assistant_texts],
            },
        },
    ]
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    return session_path


def write_codex_session(sessions_root: Path, session_id: str, text: str) -> Path:
    session_path = sessions_root / f"{session_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps({"role": "user", "content": text}) + "\n", encoding="utf-8")
    return session_path


def patch_cli_adapters(
    monkeypatch,
    *,
    claude_sessions_root: Path | None = None,
    codex_sessions_root: Path | None = None,
) -> None:
    if claude_sessions_root is not None:
        monkeypatch.setattr(
            cli,
            "ClaudeCodeAdapter",
            lambda backend: ClaudeCodeAdapter(backend, sessions_dir=claude_sessions_root),
        )
    if codex_sessions_root is not None:
        monkeypatch.setattr(
            cli,
            "CodexAdapter",
            lambda backend: CodexAdapter(backend, sessions_dir=codex_sessions_root),
        )


def fake_embed_texts(self, texts: list[str]) -> list[list[float]]:
    return [[1.0, float(len(text))] for text in texts]


def no_embed_texts(self, texts: list[str]) -> None:
    return None


async def seed_search_backend(
    backend,
    *,
    project_name: str = "test-project",
    session_id: str = "test-session-001",
) -> None:
    observation = Observation(
        session_id=session_id,
        client="claude-code",
        raw_content="We decided to use SQLite FTS5 for full-text search in this project.",
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "claude-code"],
    )
    await backend.verbatim_store.save(observation)

    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="SQLite FTS5 is used for full-text search indexing",
        confidence=0.9,
        source="manual",
        tags=["architecture", "search"],
    )
    await backend.structured_store.save_memory_entry(entry)
