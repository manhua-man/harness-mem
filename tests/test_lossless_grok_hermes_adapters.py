from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path

from harness_mem.adapters.grok.adapter import GrokAdapter, grok_project_bucket
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _jsonl_bytes(records: list[dict]) -> bytes:
    text = (
        "\r\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        + "\r\n"
    )
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def _grok_path(sessions_dir: Path, workspace: Path, session_id: str) -> Path:
    return (
        sessions_dir
        / grok_project_bucket(workspace.resolve())
        / session_id
        / "chat_history.jsonl"
    )


def _grok_records(label: str) -> list[dict]:
    return [
        {"type": "user", "content": f"user-{label}"},
        {"type": "assistant", "content": f"assistant-{label}"},
    ]


def _hermes_bytes(session_id: str, labels: list[str]) -> bytes:
    messages = []
    for label in labels:
        messages.extend(
            [
                {"role": "user", "content": f"user-{label}"},
                {"role": "assistant", "content": f"assistant-{label}"},
            ]
        )
    text = json.dumps(
        {"session_id": session_id, "messages": messages},
        ensure_ascii=False,
        indent=2,
    ).replace("\n", "\r\n")
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def _create_hermes_state_db(
    path: Path,
    *,
    workspace: Path,
    other_workspace: Path,
) -> None:
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                started_at REAL,
                ended_at REAL,
                message_count INTEGER,
                cwd TEXT,
                git_repo_root TEXT,
                model TEXT,
                archived INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_name TEXT,
                active INTEGER DEFAULT 1
            );
            """
        )
        for session_id, root in (
            ("hermes-db-wanted", workspace),
            ("hermes-db-other", other_workspace),
        ):
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    session_id,
                    "cli",
                    1_700_000_000.0,
                    1_700_000_100.0,
                    2,
                    str(root),
                    str(root),
                    "hermes-test",
                    0,
                ),
            )
            db.executemany(
                "INSERT INTO messages (session_id, role, content, tool_name) "
                "VALUES (?, ?, ?, ?)",
                (
                    (session_id, "user", f"user-{session_id}", ""),
                    (session_id, "assistant", f"assistant-{session_id}", ""),
                ),
            )


def test_grok_snapshot_preserves_bytes_and_updates_revision(tmp_path: Path) -> None:
    async def exercise() -> None:
        data_dir = tmp_path / "data"
        sessions_dir = tmp_path / ".grok" / "sessions"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        session_path = _grok_path(sessions_dir, workspace, "grok-session")
        session_path.parent.mkdir(parents=True)
        initial_bytes = _jsonl_bytes(_grok_records("one"))
        session_path.write_bytes(initial_bytes)

        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            adapter = GrokAdapter(
                backend,
                sessions_dir=sessions_dir,
                project_root=workspace,
            )
            first = await adapter.sync_session(
                session_path,
                "grok-session",
                "demo",
            )
            unchanged = await adapter.sync_session(
                session_path,
                "grok-session",
                "demo",
            )

            updated_bytes = _jsonl_bytes(_grok_records("one") + _grok_records("two"))
            session_path.write_bytes(updated_bytes)
            updated = await adapter.sync_session(
                session_path,
                "grok-session",
                "demo",
            )

            assert first.action == "ingested"
            assert unchanged.action == "unchanged"
            assert updated.action == "updated"
            assert first.source.id == updated.source.id
            assert first.observation_id == updated.observation_id
            assert (
                backend.transcript_store.reconstruct_raw(
                    updated.source.id,
                    source_revision=first.source.source_revision,
                )
                == initial_bytes
            )
            assert (
                backend.transcript_store.reconstruct_raw(updated.source.id)
                == updated_bytes
            )
            assert len(backend.transcript_store.list_revisions(updated.source.id)) == 2
            observation = await backend.verbatim_store.get(updated.observation_id)
            assert observation is not None
            assert "user-two" in observation.raw_content
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_hermes_snapshot_preserves_bytes_and_updates_revision(tmp_path: Path) -> None:
    async def exercise() -> None:
        data_dir = tmp_path / "data"
        sessions_dir = tmp_path / ".hermes" / "sessions"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        session_id = "session_hermes"
        session_path = sessions_dir / f"{session_id}.json"
        session_path.parent.mkdir(parents=True)
        initial_bytes = _hermes_bytes(session_id, ["one"])
        session_path.write_bytes(initial_bytes)

        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            adapter = HermesAdapter(
                backend,
                sessions_dir=sessions_dir,
                project_root=workspace,
                scope="all",
            )
            first = await adapter.sync_session(session_path, session_id, "demo")
            unchanged = await adapter.sync_session(session_path, session_id, "demo")

            updated_bytes = _hermes_bytes(session_id, ["one", "two"])
            session_path.write_bytes(updated_bytes)
            updated = await adapter.sync_session(session_path, session_id, "demo")

            assert first.action == "ingested"
            assert unchanged.action == "unchanged"
            assert updated.action == "updated"
            assert first.source.id == updated.source.id
            assert first.observation_id == updated.observation_id
            assert (
                backend.transcript_store.reconstruct_raw(
                    updated.source.id,
                    source_revision=first.source.source_revision,
                )
                == initial_bytes
            )
            assert (
                backend.transcript_store.reconstruct_raw(updated.source.id)
                == updated_bytes
            )
            assert len(backend.transcript_store.list_revisions(updated.source.id)) == 2
            observation = await backend.verbatim_store.get(updated.observation_id)
            assert observation is not None
            assert "user-two" in observation.raw_content
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_hermes_state_db_is_project_scoped_lossless_and_revision_aware(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        workspace = tmp_path / "wanted"
        other_workspace = tmp_path / "other"
        workspace.mkdir()
        other_workspace.mkdir()
        state_db = tmp_path / "AppData" / "Local" / "hermes" / "state.db"
        _create_hermes_state_db(
            state_db,
            workspace=workspace,
            other_workspace=other_workspace,
        )

        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            json_sessions = tmp_path / ".hermes" / "sessions"
            json_sessions.mkdir(parents=True)
            json_path = json_sessions / "session_hermes-db-wanted.json"
            json_path.write_bytes(_hermes_bytes("hermes-db-wanted", ["json-source"]))
            json_adapter = HermesAdapter(
                backend,
                sessions_dir=json_sessions,
                project_root=workspace,
                scope="all",
            )
            json_first = await json_adapter.sync_session(
                json_path,
                "hermes-db-wanted",
                "demo",
            )
            adapter = HermesAdapter(
                backend,
                sessions_dir=tmp_path / "missing-json-sessions",
                state_db=state_db,
                project_root=workspace,
            )
            sessions = adapter.list_sessions(min_size_kb=0)
            assert [session["session_id"] for session in sessions] == [
                "hermes-db-wanted"
            ]

            first = await adapter.sync_session(
                state_db,
                "hermes-db-wanted",
                "demo",
            )
            unchanged = await adapter.sync_session(
                state_db,
                "hermes-db-wanted",
                "demo",
            )
            with sqlite3.connect(state_db) as db:
                db.execute(
                    "INSERT INTO messages (session_id, role, content, tool_name) "
                    "VALUES (?, ?, ?, ?)",
                    ("hermes-db-wanted", "assistant", "assistant-added", ""),
                )
                db.execute(
                    "UPDATE sessions SET ended_at = ?, message_count = ? WHERE id = ?",
                    (1_700_000_200.0, 3, "hermes-db-wanted"),
                )
            updated = await adapter.sync_session(
                state_db,
                "hermes-db-wanted",
                "demo",
            )

            assert json_first.action == "ingested"
            assert first.action == "updated"
            assert unchanged.action == "unchanged"
            assert updated.action == "updated"
            assert json_first.source.id == first.source.id
            assert first.source.id == updated.source.id
            assert updated.source.source_kind == "sqlite-session-export"
            assert len(backend.transcript_store.list_revisions(updated.source.id)) == 3
            assert len(
                backend.transcript_store.list_sources(
                    project_name="demo",
                    client="hermes",
                )
            ) == 1
            raw = backend.transcript_store.reconstruct_raw(updated.source.id)
            assert b"assistant-added" in raw
            observation = await backend.verbatim_store.get(updated.observation_id)
            assert observation is not None
            assert "assistant-added" in observation.raw_content
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_grok_limit_counts_changed_work_after_unchanged_recent_session(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        data_dir = tmp_path / "data"
        sessions_dir = tmp_path / ".grok" / "sessions"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        recent_path = _grok_path(sessions_dir, workspace, "recent")
        older_path = _grok_path(sessions_dir, workspace, "older")
        recent_path.parent.mkdir(parents=True)
        older_path.parent.mkdir(parents=True)
        recent_path.write_bytes(_jsonl_bytes(_grok_records("recent")))
        older_path.write_bytes(_jsonl_bytes(_grok_records("older")))
        os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
        os.utime(recent_path, ns=(2_000_000_000, 2_000_000_000))

        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            adapter = GrokAdapter(
                backend,
                sessions_dir=sessions_dir,
                project_root=workspace,
            )
            initial = await adapter.ingest("demo", limit=2, min_size_kb=0)
            assert initial["ingested"] == 2

            older_path.write_bytes(
                _jsonl_bytes(_grok_records("older") + _grok_records("changed"))
            )
            os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
            result = await adapter.ingest("demo", limit=1, min_size_kb=0)

            assert result["ingested"] == 0
            assert result["updated"] == 1
            assert result["unchanged"] == 1
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_hermes_limit_counts_changed_work_after_unchanged_recent_session(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        data_dir = tmp_path / "data"
        sessions_dir = tmp_path / ".hermes" / "sessions"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        recent_id = "session_recent"
        older_id = "session_older"
        recent_path = sessions_dir / f"{recent_id}.json"
        older_path = sessions_dir / f"{older_id}.json"
        sessions_dir.mkdir(parents=True)
        recent_path.write_bytes(_hermes_bytes(recent_id, ["recent"]))
        older_path.write_bytes(_hermes_bytes(older_id, ["older"]))
        os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
        os.utime(recent_path, ns=(2_000_000_000, 2_000_000_000))

        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            adapter = HermesAdapter(
                backend,
                sessions_dir=sessions_dir,
                project_root=workspace,
                scope="all",
            )
            initial = await adapter.ingest("demo", limit=2, min_size_kb=0)
            assert initial["ingested"] == 2

            older_path.write_bytes(_hermes_bytes(older_id, ["older", "changed"]))
            os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
            result = await adapter.ingest("demo", limit=1, min_size_kb=0)

            assert result["ingested"] == 0
            assert result["updated"] == 1
            assert result["unchanged"] == 1
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_grok_and_hermes_renderers_do_not_slice_or_omit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    long_user = "u" * 2100 + "-user-end"
    long_assistant = "a" * 1100 + "-assistant-end"

    grok_path = _grok_path(tmp_path / ".grok", workspace, "long-grok")
    grok_path.parent.mkdir(parents=True)
    grok_records: list[dict] = []
    for turn_number in range(1, 22):
        grok_records.append({"type": "user", "content": f"{turn_number}-{long_user}"})
        for response_number in range(4):
            grok_records.append(
                {
                    "type": "assistant",
                    "content": f"{turn_number}-{response_number}-{long_assistant}",
                    "tool_calls": [
                        {"name": f"GrokTool-{turn_number}-{tool_number}"}
                        for tool_number in range(6)
                    ]
                    if response_number == 3
                    else [],
                }
            )
    grok_path.write_bytes(_jsonl_bytes(grok_records))
    grok_observation = GrokAdapter(
        None,
        sessions_dir=tmp_path / ".grok",
        project_root=workspace,
    ).session_to_observation(grok_path, "long-grok", "demo")

    hermes_id = "session_long_hermes"
    hermes_path = tmp_path / ".hermes" / f"{hermes_id}.json"
    hermes_path.parent.mkdir(parents=True)
    hermes_messages: list[dict] = []
    for turn_number in range(1, 22):
        hermes_messages.append(
            {"role": "user", "content": f"{turn_number}-{long_user}"}
        )
        for response_number in range(4):
            hermes_messages.append(
                {
                    "role": "assistant",
                    "content": f"{turn_number}-{response_number}-{long_assistant}",
                    "codex_message_items": [
                        {
                            "type": "tool_use",
                            "name": f"HermesTool-{turn_number}-{tool_number}",
                            "input": {"value": "x" * 400},
                        }
                        for tool_number in range(6)
                    ]
                    if response_number == 3
                    else [],
                }
            )
    hermes_path.write_text(
        json.dumps(
            {"session_id": hermes_id, "messages": hermes_messages},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    hermes_observation = HermesAdapter(
        None,
        sessions_dir=tmp_path / ".hermes",
        project_root=workspace,
        scope="all",
    ).session_to_observation(hermes_path, hermes_id, "demo")

    for observation, tool_name in (
        (grok_observation, "GrokTool-21-5"),
        (hermes_observation, "HermesTool-21-5"),
    ):
        assert "## Turn 21" in observation.raw_content
        assert "11-" + long_user in observation.raw_content
        assert "21-3-" + long_assistant in observation.raw_content
        assert tool_name in observation.raw_content
        assert "omitted" not in observation.raw_content
        assert "[TRUNCATED]" not in observation.raw_content


def test_grok_and_hermes_exclude_other_workspace_sessions(tmp_path: Path) -> None:
    workspace = tmp_path / "wanted"
    other_workspace = tmp_path / "other"
    workspace.mkdir()
    other_workspace.mkdir()

    grok_root = tmp_path / ".grok" / "sessions"
    wanted_grok = _grok_path(grok_root, workspace, "wanted-grok")
    other_grok = _grok_path(grok_root, other_workspace, "other-grok")
    wanted_grok.parent.mkdir(parents=True)
    other_grok.parent.mkdir(parents=True)
    wanted_grok.write_bytes(_jsonl_bytes(_grok_records("wanted")))
    other_grok.write_bytes(_jsonl_bytes(_grok_records("other")))
    grok = GrokAdapter(None, sessions_dir=grok_root, project_root=workspace)
    assert [item["session_id"] for item in grok.list_sessions(min_size_kb=0)] == ["wanted-grok"]

    hermes_root = tmp_path / ".hermes" / "sessions"
    hermes_root.mkdir(parents=True)
    wanted_hermes = hermes_root / "session_wanted.json"
    other_hermes = hermes_root / "session_other.json"
    wanted_hermes.write_bytes(_hermes_bytes("session_wanted", [str(workspace)]))
    other_hermes.write_bytes(_hermes_bytes("session_other", [str(other_workspace)]))
    hermes = HermesAdapter(
        None,
        sessions_dir=hermes_root,
        project_root=workspace,
        scope="project",
    )
    assert [item["session_id"] for item in hermes.list_sessions(min_size_kb=0)] == ["session_wanted"]
