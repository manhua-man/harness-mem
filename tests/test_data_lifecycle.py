from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.data_lifecycle import hard_delete
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_hard_delete_removes_raw_chunks_observation_candidates_truth_and_indexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    project = tmp_path / "project"
    project.mkdir()

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            observation = Observation(
                session_id="erase-me",
                client="codex",
                raw_content="private evidence token",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "demo"},
            )
            snapshot = await persist_session_snapshot(
                backend,
                observation,
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="erase-me",
                source_kind="jsonl",
                source_uri="file:///erase-me.jsonl",
                source_text="private evidence token",
            )
            assert snapshot.source is not None
            candidate = MemoryEntry(
                project_name="demo",
                category="decision",
                content="candidate derived from private evidence token",
                source=str(snapshot.observation_id),
                distill_job_id=snapshot.distill_job_id,
                status="pending",
                provenance={
                    "session_id": "erase-me",
                    "observation_ids": [snapshot.observation_id],
                },
            )
            candidate_id = await backend.structured_store.save_memory_entry(candidate)

            preview = await hard_delete(
                backend,
                project_name="demo",
                session_id="erase-me",
                apply=False,
            )
            assert preview["plan"]["counts"] == {
                "revisions": 1,
                "chunks": 1,
                "distill_jobs": 1,
                "observations": 1,
                "candidates": 1,
                "structured_truth": 0,
                "raw_bytes": len(b"private evidence token"),
            }
            assert backend.transcript_store.get_source(snapshot.source.id) is not None

            applied = await hard_delete(
                backend,
                project_name="demo",
                session_id="erase-me",
                apply=True,
            )
            assert applied["audit"]["counts"]["revisions"] == 1
            assert backend.transcript_store.get_source(snapshot.source.id) is None
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is None
            assert await backend.structured_store.get_memory_entry(candidate_id) is None
            assert backend.structured_store.index.get("memory_entries", candidate_id) is None
            audits = backend.transcript_store.list_deletion_audit(project_name="demo")
            assert len(audits) == 1
            assert "erase-me" not in str(audits[0])
        finally:
            await backend.close()

    asyncio.run(run())


def test_retention_of_old_revision_preserves_newer_session_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    project = tmp_path / "project"
    project.mkdir()

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            first = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="shared-session",
                    client="codex",
                    raw_content="first revision",
                    content_type="transcript",
                    timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="shared-session",
                source_kind="jsonl",
                source_uri="file:///shared-session.jsonl",
                source_text="first revision",
            )
            second = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="shared-session",
                    client="codex",
                    raw_content="second revision",
                    content_type="transcript",
                    timestamp=datetime(2030, 1, 1, tzinfo=timezone.utc),
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="shared-session",
                source_kind="jsonl",
                source_uri="file:///shared-session.jsonl",
                source_text="second revision",
            )
            assert first.source is not None
            assert second.source is not None
            assert second.distill_job_id is not None
            with backend.transcript_store._lock:
                backend.transcript_store._conn.execute(
                    "UPDATE transcript_source_revisions SET captured_at = ? "
                    "WHERE source_id = ? AND source_revision = ?",
                    (
                        "2020-01-01T00:00:00+00:00",
                        first.source.id,
                        first.source.source_revision,
                    ),
                )
                backend.transcript_store._conn.execute(
                    "UPDATE transcript_source_revisions SET captured_at = ? "
                    "WHERE source_id = ? AND source_revision = ?",
                    (
                        "2030-01-01T00:00:00+00:00",
                        second.source.id,
                        second.source.source_revision,
                    ),
                )
                backend.transcript_store._conn.commit()

            current_candidate = MemoryEntry(
                project_name="demo",
                category="decision",
                content="belongs to the retained revision",
                source=str(second.observation_id),
                distill_job_id=second.distill_job_id,
                status="pending",
                provenance={"session_id": "shared-session"},
            )
            candidate_id = await backend.structured_store.save_memory_entry(
                current_candidate
            )

            applied = await hard_delete(
                backend,
                project_name="demo",
                before=datetime(2025, 1, 1, tzinfo=timezone.utc),
                apply=True,
            )

            assert applied["audit"]["counts"]["revisions"] == 1
            assert (
                backend.transcript_store.get_revision(
                    first.source.id,
                    first.source.source_revision,
                )
                is None
            )
            assert (
                backend.transcript_store.get_revision(
                    second.source.id,
                    second.source.source_revision,
                )
                is not None
            )
            assert await backend.structured_store.get_memory_entry(candidate_id) is not None
        finally:
            await backend.close()

    asyncio.run(run())
