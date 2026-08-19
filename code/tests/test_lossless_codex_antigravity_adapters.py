from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


def _json_line(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8") + b"\r\n"


def _codex_bytes(workspace: Path, session_id: str, text: str) -> bytes:
    return b"\xef\xbb\xbf" + b"".join(
        (
            _json_line(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "cwd": str(workspace),
                        "timestamp": "2026-07-15T00:00:00Z",
                    },
                }
            ),
            _json_line(
                {
                    "type": "event_msg",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "user_message",
                        "message": text,
                    },
                }
            ),
            _json_line(
                {
                    "type": "response_item",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "complete"}],
                    },
                }
            ),
        )
    )


def _antigravity_bytes(text: str) -> bytes:
    return b"\xef\xbb\xbf" + b"".join(
        (
            _json_line(
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": text,
                }
            ),
            _json_line(
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "content": "complete",
                }
            ),
        )
    )


def _write_antigravity_history(
    path: Path,
    *,
    session_id: str,
    workspace: Path,
    prompts: list[str],
    start_timestamp: int = 1_700_000_000_000,
) -> None:
    records = [
        {
            "conversationId": session_id,
            "workspace": str(workspace),
            "display": prompt,
            "timestamp": start_timestamp + index,
        }
        for index, prompt in enumerate(prompts)
    ]
    write_jsonl(path, records, append=True)


def _write_session(
    root: Path,
    kind: str,
    workspace: Path,
    session_id: str,
    text: str,
) -> Path:
    if kind == "codex":
        path = root / "2026" / "07" / "15" / f"rollout-{session_id}.jsonl"
        native = _codex_bytes(workspace, session_id, text)
    elif kind == "codex-archive":
        path = root / f"rollout-{session_id}.jsonl"
        native = _codex_bytes(workspace, session_id, text)
    else:
        path = root / session_id / ".system_generated" / "logs" / "transcript.jsonl"
        native = _antigravity_bytes(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(native)
    return path


def _make_adapter(
    kind: str,
    backend: LocalMemoryBackend,
    root: Path,
    workspace: Path,
) -> CodexAdapter | CodexArchiveAdapter | AntigravityAdapter:
    if kind == "codex":
        return CodexAdapter(backend, sessions_dir=root, project_root=workspace)
    if kind == "codex-archive":
        return CodexArchiveAdapter(backend, archive_dir=root)
    return AntigravityAdapter(backend, brain_dir=root)


async def _ingest(
    kind: str,
    adapter: CodexAdapter | CodexArchiveAdapter | AntigravityAdapter,
    workspace: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    if kind == "codex-archive":
        assert isinstance(adapter, CodexArchiveAdapter)
        return await adapter.ingest(
            "repo",
            limit=limit,
            project_root=workspace,
            scope="project",
        )
    return await adapter.ingest("repo", limit=limit)


@pytest.mark.parametrize("kind", ["codex", "codex-archive", "antigravity"])
def test_adapter_snapshot_preserves_native_bytes_and_complete_decode(
    tmp_path: Path,
    kind: str,
) -> None:
    async def run() -> None:
        workspace = tmp_path / "repo"
        workspace.mkdir()
        root = tmp_path / kind
        marker = "end-of-long-source"
        path = _write_session(root, kind, workspace, "session-1", "x" * 60_000 + marker)
        with path.open("ab") as handle:
            handle.write(b"\xfftrailing-invalid-byte\r\n")
        native = path.read_bytes()

        backend = LocalMemoryBackend(tmp_path / f"data-{kind}")
        await backend.init()
        try:
            adapter = _make_adapter(kind, backend, root, workspace)
            result = await adapter.sync_session(path, "session-1", "repo")

            assert result.action == "ingested"
            assert backend.transcript_store.reconstruct_raw(result.source.id) == native
            normalized = backend.transcript_store.reconstruct(result.source.id)
            assert normalized == native.decode("utf-8-sig", errors="replace")
            assert marker in normalized
            assert normalized.endswith("\ufffdtrailing-invalid-byte\r\n")
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["codex", "codex-archive", "antigravity"])
def test_ingest_updates_growth_and_scans_past_unchanged_sessions(
    tmp_path: Path,
    kind: str,
) -> None:
    async def run() -> None:
        workspace = tmp_path / "repo"
        workspace.mkdir()
        root = tmp_path / kind
        older = _write_session(root, kind, workspace, "older", "first revision")
        newer = _write_session(root, kind, workspace, "newer", "unchanged revision")
        os.utime(older, ns=(1_700_000_000_000_000_000,) * 2)
        os.utime(newer, ns=(1_700_000_100_000_000_000,) * 2)

        backend = LocalMemoryBackend(tmp_path / f"data-{kind}")
        await backend.init()
        try:
            adapter = _make_adapter(kind, backend, root, workspace)
            first = await _ingest(kind, adapter, workspace, limit=10)
            assert first["ingested"] == 2
            assert first["updated"] == 0
            assert first["unchanged"] == 0

            with older.open("ab") as handle:
                if kind.startswith("codex"):
                    handle.write(
                        _json_line(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "turn_id": "turn-1",
                                    "type": "agent_message",
                                    "phase": "final_answer",
                                    "message": "grown revision",
                                },
                            }
                        )
                    )
                else:
                    handle.write(
                        _json_line(
                            {
                                "step_index": 2,
                                "source": "MODEL",
                                "type": "PLANNER_RESPONSE",
                                "content": "grown revision",
                            }
                        )
                    )
            os.utime(older, ns=(1_700_000_050_000_000_000,) * 2)

            second = await _ingest(kind, adapter, workspace, limit=1)
            assert second["ingested"] == 0
            assert second["updated"] == 1
            assert second["unchanged"] == 1
            assert second["sessions_scanned"] == 2

            source = backend.transcript_store.find_source(
                project_name="repo",
                client=kind,
                session_id="older",
            )
            assert source is not None
            assert len(backend.transcript_store.list_revisions(source.id)) == 2

            third = await _ingest(kind, adapter, workspace, limit=1)
            assert third["ingested"] == 0
            assert third["updated"] == 0
            assert third["unchanged"] == 2
        finally:
            await backend.close()

    asyncio.run(run())


def test_codex_current_and_archive_share_one_logical_source(tmp_path: Path) -> None:
    async def run() -> None:
        workspace = tmp_path / "repo"
        workspace.mkdir()
        codex_root = tmp_path / ".codex"
        current_root = codex_root / "sessions"
        archive_root = codex_root / "archived_sessions"
        current = _write_session(
            current_root,
            "codex",
            workspace,
            "shared-session",
            "same revision",
        )
        archive = archive_root / current.name
        archive.parent.mkdir(parents=True, exist_ok=True)

        backend = LocalMemoryBackend(tmp_path / "data-codex-union")
        await backend.init()
        try:
            adapter = CodexAdapter(
                backend,
                sessions_dir=current_root,
                archive_dir=archive_root,
                project_root=workspace,
            )
            first = await adapter.ingest("repo", limit=5)
            assert first["ingested"] == 1
            archive.write_bytes(current.read_bytes())
            current.unlink()

            second = await adapter.ingest("repo", limit=5)
            assert second["errors"] == 0, second["error_details"][0]["message"]
            assert second["ingested"] == 0
            assert second["updated"] == 0
            assert second["unchanged"] == 1

            sources = backend.transcript_store.list_sources(
                project_name="repo",
                client="codex",
            )
            assert len(sources) == 1
            assert sources[0].source_kind == "codex-archive"
            assert len(sources[0].metadata["native_source_aliases"]) == 2
            jobs = backend.transcript_store.list_distill_jobs(project_name="repo")
            assert len(jobs) == 1
        finally:
            await backend.close()

    asyncio.run(run())


def test_antigravity_cli_history_is_project_scoped_lossless_and_revision_aware(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        workspace = tmp_path / "wanted"
        other_workspace = tmp_path / "other"
        workspace.mkdir()
        other_workspace.mkdir()
        cli_root = tmp_path / ".gemini" / "antigravity-cli"
        history = cli_root / "history.jsonl"
        _write_antigravity_history(
            history,
            session_id="agy-wanted",
            workspace=workspace,
            prompts=["wanted-one"],
        )
        _write_antigravity_history(
            history,
            session_id="agy-other",
            workspace=other_workspace,
            prompts=["other-one"],
        )

        backend = LocalMemoryBackend(tmp_path / "data-agy-cli")
        await backend.init()
        try:
            adapter = AntigravityAdapter(
                backend,
                brain_dir=tmp_path / "missing-brain",
                cli_root=cli_root,
                project_root=workspace,
            )
            sessions = adapter.list_sessions(min_size_kb=0)
            assert [session["session_id"] for session in sessions] == ["agy-wanted"]

            first = await adapter.sync_session(history, "agy-wanted", "repo")
            unchanged = await adapter.sync_session(history, "agy-wanted", "repo")
            _write_antigravity_history(
                history,
                session_id="agy-wanted",
                workspace=workspace,
                prompts=["wanted-two"],
                start_timestamp=1_700_000_100_000,
            )
            updated = await adapter.sync_session(history, "agy-wanted", "repo")
            transcript = (
                cli_root
                / "brain"
                / "agy-wanted"
                / ".system_generated"
                / "logs"
                / "transcript_full.jsonl"
            )
            transcript.parent.mkdir(parents=True)
            transcript.write_bytes(_antigravity_bytes("transcript-complete"))
            with_transcript = await adapter.sync_session(
                history,
                "agy-wanted",
                "repo",
            )

            assert first.action == "ingested"
            assert unchanged.action == "unchanged"
            assert updated.action == "updated"
            assert with_transcript.action == "updated"
            assert first.source.id == updated.source.id
            assert first.source.id == with_transcript.source.id
            assert updated.source.source_kind == "antigravity-cli-session-export"
            assert len(backend.transcript_store.list_revisions(updated.source.id)) == 3
            raw = backend.transcript_store.reconstruct_raw(updated.source.id)
            assert b"wanted-two" in raw
            assert b"other-one" not in raw
            normalized = backend.transcript_store.reconstruct(updated.source.id)
            assert "transcript-complete" in normalized
            observation = await backend.verbatim_store.get(
                with_transcript.observation_id
            )
            assert observation is not None
            assert "wanted-two" in observation.raw_content
            assert "transcript-complete" in observation.raw_content
            assert "other-one" not in observation.raw_content
        finally:
            await backend.close()

    asyncio.run(run())


def test_codex_and_antigravity_exclude_other_workspace_sources(tmp_path: Path) -> None:
    async def run() -> None:
        workspace = tmp_path / "wanted"
        other_workspace = tmp_path / "other"
        workspace.mkdir()
        other_workspace.mkdir()
        backend = LocalMemoryBackend(tmp_path / "data-isolation")
        await backend.init()
        try:
            codex_root = tmp_path / "codex"
            _write_session(codex_root, "codex", workspace, "wanted", "wanted work")
            _write_session(codex_root, "codex", other_workspace, "other", "other work")
            codex = CodexAdapter(
                backend, sessions_dir=codex_root, project_root=workspace
            )
            assert [
                item["session_id"] for item in codex.list_sessions(min_size_kb=0)
            ] == ["wanted"]

            antigravity_root = tmp_path / "antigravity"
            wanted_path = _write_session(
                antigravity_root,
                "antigravity",
                workspace,
                "wanted-antigravity",
                "wanted work",
            )
            other_path = _write_session(
                antigravity_root,
                "antigravity",
                other_workspace,
                "other-antigravity",
                "other work",
            )
            for path, root in ((wanted_path, workspace), (other_path, other_workspace)):
                with path.open("ab") as handle:
                    handle.write(
                        _json_line({"tool_calls": [{"args": {"cwd": str(root)}}]})
                    )
            antigravity = AntigravityAdapter(
                backend,
                brain_dir=antigravity_root,
                project_root=workspace,
            )
            assert [item["session_id"] for item in antigravity.list_sessions()] == [
                "wanted-antigravity"
            ]
        finally:
            await backend.close()

    asyncio.run(run())
