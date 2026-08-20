from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.projection_repair import repair_source_observation_projection
from harness_mem.mcp.distill_handlers import _load_distill_semantic_evidence
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.native_sessions import write_jsonl


def _run(coro):
    return asyncio.run(coro)


def _codex_records(workspace: Path, session_id: str) -> list[dict]:
    return [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(workspace),
                "timestamp": "2026-08-02T00:00:00Z",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "turn_id": "turn-1",
                "type": "user_message",
                "message": "Preserve the fast semantic path.",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Completed."}],
            },
        },
    ]


def test_missing_canonical_projection_replays_in_memory_from_verified_ledger(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    sessions_dir = tmp_path / ".codex" / "sessions"
    session_id = "projection-repair"
    session_path = (
        sessions_dir
        / "2026"
        / "08"
        / "02"
        / f"rollout-2026-08-02T00-00-00-{session_id}.jsonl"
    )
    write_jsonl(session_path, _codex_records(workspace, session_id))

    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        adapter = CodexAdapter(
            backend,
            sessions_dir=sessions_dir,
            project_root=workspace,
        )
        result = _run(adapter.sync_session(session_path, session_id, "demo"))
        assert result.source is not None
        assert result.observation_id is not None
        assert _run(backend.verbatim_store.delete(result.observation_id)) is True

        evidence = _load_distill_semantic_evidence(
            backend,
            source_id=result.source.id,
            source_revision=result.source.source_revision,
            detail_level="compact",
            budget_tokens=1900,
        )

        assert evidence is not None
        assert evidence["projection"] == "exchange-outline-v2"
        assert evidence["exchange_count"] == 1
        assert _run(backend.verbatim_store.get(result.observation_id)) is None
    finally:
        _run(backend.close())


def test_projection_repair_does_not_replace_newer_canonical_projection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    sessions_dir = tmp_path / ".codex" / "sessions"
    session_id = "projection-race"
    session_path = sessions_dir / "rollout-projection-race.jsonl"
    write_jsonl(session_path, _codex_records(workspace, session_id))

    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        adapter = CodexAdapter(
            backend,
            sessions_dir=sessions_dir,
            project_root=workspace,
        )
        result = _run(adapter.sync_session(session_path, session_id, "demo"))
        assert result.source is not None
        assert result.observation_id is not None
        old_revision = result.source.source_revision
        write_jsonl(
            session_path,
            [
                {
                    "type": "event_msg",
                    "payload": {
                        "turn_id": "turn-2",
                        "type": "user_message",
                        "message": "This is the newer revision.",
                    },
                }
            ],
            append=True,
        )
        updated = _run(adapter.sync_session(session_path, session_id, "demo"))
        assert updated.source is not None
        assert updated.source.source_revision != old_revision

        repaired = repair_source_observation_projection(
            backend,
            source_id=result.source.id,
            source_revision=old_revision,
        )

        assert repaired is not None
        assert (
            repaired.metadata["projection_repair"]
            == "verified_historical_transcript_ledger"
        )
        assert repaired.raw_content.count("Preserve the fast semantic path.") == 1
        canonical = _run(backend.verbatim_store.get(result.observation_id))
        assert canonical is not None
        assert canonical.metadata["source_revision"] == updated.source.source_revision
    finally:
        _run(backend.close())
