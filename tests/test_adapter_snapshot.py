from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _observation(content: str) -> Observation:
    return Observation(
        session_id="session-1",
        client="cursor",
        raw_content=content,
        content_type="transcript",
        timestamp=datetime.now(timezone.utc),
        metadata={},
        tags=["session", "cursor"],
    )


def test_snapshot_updates_growing_session_and_reuses_observation(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        try:
            first = await persist_session_snapshot(
                backend,
                _observation("derived one"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///session.jsonl",
                source_text="record one\n",
            )
            unchanged = await persist_session_snapshot(
                backend,
                _observation("derived one"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///session.jsonl",
                source_text="record one\n",
            )
            updated = await persist_session_snapshot(
                backend,
                _observation("derived one\nderived two"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///session.jsonl",
                source_text="record one\nrecord two\n",
            )

            assert first.action == "ingested"
            assert unchanged.action == "unchanged"
            assert updated.action == "updated"
            assert first.observation_id == updated.observation_id
            assert first.distill_job_id != updated.distill_job_id
            assert backend.transcript_store.reconstruct(updated.source.id) == (
                "record one\nrecord two\n"
            )
            stored = await backend.verbatim_store.get(updated.observation_id)
            assert stored is not None
            assert stored.raw_content == "derived one\nderived two"
            assert stored.metadata["source_revision"] == updated.source.source_revision
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_same_native_session_id_in_two_sources_does_not_collide(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        try:
            first = await persist_session_snapshot(
                backend,
                _observation("first rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///bucket-a/session.jsonl",
                source_text="first source\n",
            )
            second = await persist_session_snapshot(
                backend,
                _observation("second rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///bucket-b/session.jsonl",
                source_text="second source\n",
            )

            assert first.source.id != second.source.id
            assert backend.transcript_store.reconstruct(first.source.id) == "first source\n"
            assert backend.transcript_store.reconstruct(second.source.id) == "second source\n"
            assert len(
                backend.transcript_store.list_sources(
                    project_name="demo",
                    client="cursor",
                )
            ) == 2
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_moved_session_reuses_verified_source_and_retains_locator_alias(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        try:
            first = await persist_session_snapshot(
                backend,
                _observation("first rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///old/session.jsonl",
                source_text="one\n",
                raw_bytes=b"one\n",
            )
            moved = await persist_session_snapshot(
                backend,
                _observation("second rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///new/session.jsonl",
                source_text="one\ntwo\n",
                raw_bytes=b"one\ntwo\n",
            )

            assert moved.action == "updated"
            assert moved.source.id == first.source.id
            assert moved.source.metadata["native_source_uri"] == "file:///new/session.jsonl"
            assert moved.source.metadata["native_source_aliases"] == [
                "file:///new/session.jsonl",
                "file:///old/session.jsonl",
            ]
            assert len(backend.transcript_store.list_sources(project_name="demo")) == 1
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_reappearing_missing_source_returns_to_synced_without_new_revision(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        try:
            first = await persist_session_snapshot(
                backend,
                _observation("rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///session.jsonl",
                source_text="one\n",
            )
            backend.transcript_store.mark_sources_missing_from_inventory(
                project_name="demo",
                client="cursor",
                observed_session_ids=set(),
            )

            reappeared = await persist_session_snapshot(
                backend,
                _observation("rendering"),
                project_name="demo",
                project_root="C:/work/demo",
                client="cursor",
                session_id="session-1",
                source_kind="file",
                source_uri="file:///session.jsonl",
                source_text="one\n",
            )

            assert reappeared.action == "unchanged"
            assert reappeared.source.id == first.source.id
            assert reappeared.source.status == "synced"
        finally:
            await backend.close()

    asyncio.run(exercise())
