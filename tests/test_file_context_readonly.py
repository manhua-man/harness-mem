"""Read-only invariant for the v2.5.2 file-context helper."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas import MemoryEntry, Observation, ProjectProfile, RetrievalSignal, Skill, TaskHandoff
from harness_mem.file_context import build_file_context
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


def _sqlite_logical_rows(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        parts: list[str] = []
        for table in table_names:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            except sqlite3.DatabaseError:
                continue
            parts.append(f"TABLE {table}\n" + "\n".join(sorted(repr(row) for row in rows)))
        return "\n".join(parts)
    finally:
        conn.close()


def _state_digest(data_dir: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(data_dir)).replace("\\", "/")
        if path.suffix == ".sqlite":
            hasher.update(f"SQLITE:{rel}\n".encode())
            hasher.update(_sqlite_logical_rows(path).encode())
        elif path.suffix in (".sqlite-wal", ".sqlite-shm"):
            continue
        else:
            hasher.update(f"FILE:{rel}\n".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def test_build_file_context_is_read_only(data_dir: Path) -> None:
    project_name = "file-context-readonly"
    query_path = "harness_mem/mcp/server.py"
    known_last_accessed = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            LocalProjectProfileStore(backend.data_dir).save(
                ProjectProfile(
                    project_name=project_name,
                    description="Readonly file-context project",
                    key_files=[query_path],
                )
            )
        )
        observation = Observation(
            session_id="readonly-file-context",
            client="codex",
            raw_content="Touched harness_mem/mcp/server.py while protecting MCP stdout.",
            content_type="transcript",
            metadata={"project_name": project_name},
        )
        run(backend.verbatim_store.save(observation))
        entry = MemoryEntry(
            project_name=project_name,
            category="architecture",
            content="harness_mem/mcp/server.py owns MCP tool registration.",
            source="manual",
            usage_count=9,
            last_accessed_at=known_last_accessed,
        )
        run(backend.structured_store.save_memory_entry(entry))
        skill = Skill(
            project_name=project_name,
            name="MCP stdout guardrail",
            activation_condition="When editing harness_mem/mcp/server.py",
            steps=["Never print file-context payloads to stdout."],
            termination_condition="Validation passes.",
            usage_count=5,
        )
        run(backend.structured_store.save_skill(skill))
        handoff = TaskHandoff(
            project_name=project_name,
            task_id="readonly-handoff",
            summary="Resume file_context work in harness_mem/mcp/server.py",
        )
        run(backend.structured_store.save_task_handoff(handoff))
        signal = RetrievalSignal(
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=entry.id,
        )
        run(backend.structured_store.save_retrieval_signal(signal))

        digest_before = _state_digest(data_dir)
        signals_before = len(run(backend.structured_store.query_retrieval_signals(project_name)))

        result = run(build_file_context(backend, project_name=project_name, path=query_path))

        digest_after = _state_digest(data_dir)
        signals_after = len(run(backend.structured_store.query_retrieval_signals(project_name)))
        refetched_entry = run(backend.structured_store.get_memory_entry(entry.id))
        refetched_skill = run(backend.structured_store.get_skill(skill.id))
    finally:
        run(backend.close())

    assert result.items
    assert digest_after == digest_before
    assert signals_after == signals_before
    assert refetched_entry is not None
    assert refetched_entry.usage_count == 9
    assert refetched_entry.last_accessed_at == known_last_accessed
    assert refetched_skill is not None
    assert refetched_skill.usage_count == 5

