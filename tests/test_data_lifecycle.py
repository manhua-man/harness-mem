from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.data_lifecycle import hard_delete
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import (
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
    transcript_bytes_revision,
)


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
            truth_id = await backend.structured_store.save_confirmed_rule(
                ConfirmedRule(
                    project_name="demo",
                    pattern="private evidence token",
                    trigger="privacy lifecycle test",
                    source_candidate_id=candidate_id,
                    source_session_id="erase-me",
                )
            )

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
                "structured_truth": 1,
                "indexes": preview["plan"]["counts"]["indexes"],
                "index_artifacts": preview["plan"]["counts"]["index_artifacts"],
                "raw_bytes": len(b"private evidence token"),
            }
            assert preview["plan"]["counts"]["indexes"] == 3
            assert preview["plan"]["counts"]["index_artifacts"] >= 3
            assert preview["plan"]["index_counts"]["entity_rows"] == 3
            assert backend.transcript_store.get_source(snapshot.source.id) is not None

            applied = await hard_delete(
                backend,
                project_name="demo",
                session_id="erase-me",
                apply=True,
            )
            assert applied["audit"]["counts"]["revisions"] == 1
            assert applied["success"] is True
            assert applied["receipt"]["status"] == "succeeded"
            assert applied["receipt"]["verification"]["passed"] is True
            assert not any(applied["receipt"]["verification"]["remaining"].values())
            assert backend.transcript_store.get_source(snapshot.source.id) is None
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is None
            assert await backend.structured_store.get_memory_entry(candidate_id) is None
            assert await backend.structured_store.get_confirmed_rule(truth_id) is None
            assert backend.structured_store.index.get("memory_entries", candidate_id) is None
            audits = backend.transcript_store.list_deletion_audit(project_name="demo")
            assert len(audits) == 1
            assert "erase-me" not in str(audits[0])
            assert "private evidence token" not in str(audits[0])
            assert audits[0]["plan_counts"] == preview["plan"]["counts"]
            assert audits[0]["actual_removal"] == applied["receipt"]["actual_removal"]
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


def test_hard_delete_partial_failure_is_durable_and_never_reports_success(
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
            private_text = "private failure evidence must not enter receipt"
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="private-session-id",
                    client="codex",
                    raw_content=private_text,
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="private-session-id",
                source_kind="jsonl",
                source_uri="file:///private-source.jsonl",
                source_text=private_text,
            )
            candidate_id = await backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content=private_text,
                    source=str(snapshot.observation_id),
                    distill_job_id=snapshot.distill_job_id,
                    status="pending",
                    provenance={"session_id": "private-session-id"},
                )
            )

            structured_store = backend.structured_store
            original_delete = structured_store.hard_delete_record

            def delete_then_fail(collection: str, entity_id: str) -> bool:
                original_delete(collection, entity_id)
                raise RuntimeError(private_text)

            monkeypatch.setattr(
                structured_store,
                "hard_delete_record",
                delete_then_fail,
            )
            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="private-session-id",
                reason=private_text,
                apply=True,
            )

            assert result["success"] is False
            assert result["applied"] is True
            assert result["partial"] is True
            assert result["receipt"]["status"] == "partial_failure"
            assert result["receipt"]["verification"]["passed"] is False
            assert result["receipt"]["failure"] == {
                "operation": "structured_records",
                "error_type": "RuntimeError",
            }
            assert result["receipt"]["reason"] == "custom_reason"
            assert result["receipt"]["reason_sha256"]
            assert await structured_store.get_memory_entry(candidate_id) is None
            receipts = backend.transcript_store.list_deletion_audit(project_name="demo")
            assert len(receipts) == 1
            assert receipts[0]["status"] == "partial_failure"
            serialized = str(receipts[0])
            assert private_text not in serialized
            assert "private-session-id" not in serialized
            assert "private-source.jsonl" not in serialized
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_no_match_keeps_safe_noop_and_records_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="missing-private-session",
                apply=True,
            )
            assert result["success"] is True
            assert result["applied"] is False
            assert result["skipped"] is True
            assert result["receipt"]["status"] == "skipped"
            assert result["receipt"]["verification"]["passed"] is True
            receipts = backend.transcript_store.list_deletion_audit(project_name="demo")
            assert len(receipts) == 1
            assert "missing-private-session" not in str(receipts[0])
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_no_match_reports_receipt_finalization_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            original_save = backend.transcript_store.save_deletion_receipt
            calls = 0

            def fail_second_save(receipt):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("receipt store unavailable")
                return original_save(receipt)

            monkeypatch.setattr(
                backend.transcript_store,
                "save_deletion_receipt",
                fail_second_save,
            )
            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="missing-session",
                apply=True,
            )

            assert result["success"] is False
            assert result["reason"] == "receipt_finalization_failed"
            assert result["receipt_persisted"] is False
            receipts = backend.transcript_store.list_deletion_audit(
                project_name="demo"
            )
            assert len(receipts) == 1
            assert receipts[0]["status"] == "in_progress"
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_includes_compacted_observations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    project = tmp_path / "project"
    project.mkdir()

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="soft-deleted-session",
                    client="codex",
                    raw_content="soft deleted private evidence",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="soft-deleted-session",
                source_kind="jsonl",
                source_uri="file:///soft-deleted.jsonl",
                source_text="soft deleted private evidence",
            )
            assert snapshot.observation_id is not None
            assert await backend.verbatim_store.soft_delete(snapshot.observation_id)

            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="soft-deleted-session",
                apply=True,
            )

            assert result["success"] is True
            assert result["plan"]["counts"]["observations"] == 1
            assert await backend.verbatim_store.get(snapshot.observation_id) is None
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_follows_governance_signal_and_run_reference_closure(
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
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="closure-session",
                    client="codex",
                    raw_content="closure private evidence",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="closure-session",
                source_kind="jsonl",
                source_uri="file:///closure.jsonl",
                source_text="closure private evidence",
            )
            candidate_id = await backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id="candidate-private",
                    project_name="demo",
                    category="decision",
                    content="closure private evidence",
                    source=str(snapshot.observation_id),
                    distill_job_id=snapshot.distill_job_id,
                    status="pending",
                )
            )
            records = {
                "supersede_candidates": {
                    "id": "supersede-private",
                    "project_name": "demo",
                    "source": candidate_id,
                    "target_id": "unrelated-a",
                    "replacement_id": "unrelated-b",
                    "evidence": "closure private evidence",
                },
                "retrieval_signals": {
                    "id": "signal-private",
                    "project_name": "demo",
                    "target_id": candidate_id,
                    "context": {"private": "closure private evidence"},
                },
                "merge_suggestion_candidates": {
                    "id": "merge-private",
                    "project_name": "demo",
                    "target_a_id": candidate_id,
                    "target_b_id": "unrelated-c",
                    "evidence_signal_ids": ["signal-private"],
                },
                "stale_truth_suggestion_candidates": {
                    "id": "stale-private",
                    "project_name": "demo",
                    "target_id": "unrelated-d",
                    "evidence_signal_ids": ["signal-private"],
                },
                "confirmed_rules": {
                    "id": "rule-private",
                    "project_name": "demo",
                    "source_candidate_id": candidate_id,
                    "pattern": "closure private evidence",
                },
                "skills": {
                    "id": "skill-private",
                    "project_name": "demo",
                    "source_candidate_id": candidate_id,
                    "content": "closure private evidence",
                },
                "metabolism_runs": {
                    "id": "metabolism-private",
                    "project_name": "demo",
                    "selected_signal_ids": ["signal-private"],
                    "input_window": {"signal_ids": ["signal-private"]},
                },
                "dream_runs": {
                    "id": "dream-private",
                    "project_name": "demo",
                    "selected_signal_ids": [],
                    "input_window": {},
                    "items": [
                        {
                            "source_id": "unrelated-dream-item",
                            "evidence_ids": [],
                            "undo": {
                                "restore_truth_snapshots": [
                                    {"truth_id": candidate_id}
                                ]
                            },
                        }
                    ],
                },
            }
            for collection, payload in records.items():
                backend.structured_store.write_record_payload(
                    collection,
                    str(payload["id"]),
                    payload,
                )

            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="closure-session",
                apply=True,
            )

            assert result["success"] is True
            for collection, payload in records.items():
                assert not backend.structured_store.record_payload_exists(
                    collection,
                    str(payload["id"]),
                )
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_detects_revision_created_after_plan(
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
            snapshot = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="racing-session",
                    client="codex",
                    raw_content="first private revision",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="racing-session",
                source_kind="jsonl",
                source_uri="file:///racing.jsonl",
                source_text="first private revision",
            )
            assert snapshot.source is not None
            original_delete = backend.transcript_store.hard_delete_revisions
            concurrent_text = "concurrent private revision"
            concurrent_bytes = concurrent_text.encode()
            concurrent_revision = transcript_bytes_revision(concurrent_bytes)

            def inject_revision(revision_keys, **kwargs):
                source = TranscriptSource.from_dict(snapshot.source.to_dict())
                source.source_revision = concurrent_revision
                source.raw_sha256 = sha256_bytes(concurrent_bytes)
                source.normalized_sha256 = sha256_text(concurrent_text)
                source.raw_size_bytes = len(concurrent_bytes)
                source.normalized_size_bytes = len(concurrent_bytes)
                chunks = chunk_transcript_text(
                    concurrent_text,
                    source_id=source.id,
                    project_name="demo",
                    client="codex",
                    session_id="racing-session",
                    source_revision=concurrent_revision,
                )
                backend.transcript_store.save_snapshot(
                    source,
                    chunks,
                    raw_bytes=concurrent_bytes,
                )
                return original_delete(revision_keys, **kwargs)

            monkeypatch.setattr(
                backend.transcript_store,
                "hard_delete_revisions",
                inject_revision,
            )
            result = await hard_delete(
                backend,
                project_name="demo",
                session_id="racing-session",
                apply=True,
            )

            assert result["success"] is False
            assert result["receipt"]["status"] == "partial_failure"
            assert result["receipt"]["verification"]["remaining"]["revisions"] == 1
            assert (
                backend.transcript_store.get_revision(
                    snapshot.source.id,
                    concurrent_revision,
                )
                is not None
            )
        finally:
            await backend.close()

    asyncio.run(run())


def test_hard_delete_scope_guard_and_tombstone_block_recapture(
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
            try:
                await hard_delete(backend, project_name="demo", apply=True)
            except ValueError as exc:
                assert "requires session_id, source_id, or before" in str(exc)
            else:
                raise AssertionError("project-wide hard delete must require explicit scope")

            kwargs = {
                "project_name": "demo",
                "project_root": str(project),
                "client": "codex",
                "session_id": "tombstoned-session",
                "source_kind": "jsonl",
                "source_uri": "file:///tombstone.jsonl",
                "source_text": "private tombstone text",
            }
            first = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="tombstoned-session",
                    client="codex",
                    raw_content="private tombstone text",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                **kwargs,
            )
            assert first.action == "ingested"
            deleted = await hard_delete(
                backend,
                project_name="demo",
                session_id="tombstoned-session",
                apply=True,
            )
            assert deleted["success"] is True

            recapture = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="tombstoned-session",
                    client="codex",
                    raw_content="private tombstone text",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                **kwargs,
            )
            assert recapture.action == "ignored"
            assert recapture.reason == "hard_delete_tombstone"
        finally:
            await backend.close()

    asyncio.run(run())


def test_source_tombstone_blocks_recapture_from_moved_uri(
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
                    session_id="moved-source-session",
                    client="codex",
                    raw_content="moved private evidence",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="moved-source-session",
                source_kind="jsonl",
                source_uri="file:///original-location.jsonl",
                source_text="moved private evidence",
            )
            assert first.source is not None
            deleted = await hard_delete(
                backend,
                project_name="demo",
                source_id=first.source.id,
                apply=True,
            )
            assert deleted["success"] is True

            recapture = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="moved-source-session",
                    client="codex",
                    raw_content="moved private evidence",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="moved-source-session",
                source_kind="jsonl",
                source_uri="file:///new-location.jsonl",
                source_text="moved private evidence",
            )
            assert recapture.action == "ignored"
            assert recapture.reason == "hard_delete_tombstone"
        finally:
            await backend.close()

    asyncio.run(run())
