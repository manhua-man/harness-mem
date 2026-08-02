from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.evidence import EvidenceRef
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.skill import Skill
from harness_mem.processed_source_cleanup import (
    begin_processed_source_cleanup,
    cleanup_processed_source,
    retry_retained_source_cleanups,
)
from harness_mem.commands.wake import build_wake_injection
from harness_mem.mcp.distill_projection import (
    DISTILL_INCREMENTAL_PROJECTION,
    build_append_aware_distill_projection,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.canonical_store import canonical_store_path


def _run(coro):
    return asyncio.run(coro)


def test_cleanup_retry_requires_explicit_authorization(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            result = await retry_retained_source_cleanups(
                backend,
                project_name="demo",
                authorized=False,
            )
            assert result["attempted"] == 0
            assert result["reason"] == "source_cleanup_not_authorized"
        finally:
            await backend.close()

    _run(run())


async def _completed_snapshot(
    backend: LocalMemoryBackend,
    project: Path,
    *,
    session_id: str,
    private_text: str,
):
    snapshot = await persist_session_snapshot(
        backend,
        Observation(
            session_id=session_id,
            client="codex",
            raw_content=private_text,
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": "demo"},
        ),
        project_name="demo",
        project_root=str(project),
        client="codex",
        session_id=session_id,
        source_kind="jsonl",
        source_uri=f"file:///{session_id}.jsonl",
        source_text=private_text,
    )
    assert snapshot.source is not None
    assert snapshot.distill_job_id is not None
    claims = backend.transcript_store.claim_distill_chunks(
        snapshot.distill_job_id,
        lease_owner="cleanup-test",
        limit=100,
    )
    for chunk, _checkpoint in claims:
        backend.transcript_store.checkpoint_distill_chunk(
            snapshot.distill_job_id,
            chunk.id,
            lease_owner="cleanup-test",
            result={"outline": private_text},
        )
    backend.transcript_store.finalize_distill_job(
        snapshot.distill_job_id,
        semantic_review={
            "final_user_request": private_text,
            "final_outcome": private_text,
            "last_turn_status": "answered",
            "contradictions": [],
            "unfinished_work": [],
            "evidence_status": "answered",
            "promotion_decision": "promote",
        },
    )
    return snapshot


def test_cleanup_prunes_raw_evidence_and_preserves_sanitized_truth(
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
            private_text = "private transcript sentinel"
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id="cleanup-session",
                private_text=private_text,
            )
            truth = MemoryEntry(
                id="durable-truth",
                project_name="demo",
                category="decision",
                content="Use the stable cleanup contract.",
                confidence=0.95,
                status="auto_confirmed",
                source=str(snapshot.observation_id),
                distill_job_id=snapshot.distill_job_id,
                provenance={
                    "session_id": "cleanup-session",
                    "observation_ids": [snapshot.observation_id],
                    "private": private_text,
                },
                evidence_basis="repository",
                verification_outcome="verified",
                verification_reason_codes=["repository_refs_current"],
                verification_refs=[
                    EvidenceRef(
                        kind="repository",
                        locator="private/path.md",
                        content_sha256="b" * 64,
                    )
                ],
            )
            await backend.structured_store.save_memory_entry(truth)
            confirmed_rule = ConfirmedRule(
                id="durable-rule",
                project_name="demo",
                pattern="Keep promoted truth.",
                trigger="After distill",
                source_candidate_id=truth.id,
                source_session_id="cleanup-session",
                provenance={"session_id": "cleanup-session"},
            )
            await backend.structured_store.save_confirmed_rule(confirmed_rule)
            skill = Skill(
                id="durable-skill",
                project_name="demo",
                name="Safe cleanup",
                activation_condition="A completed source is eligible",
                steps=["Preserve truth", "Prune evidence"],
                termination_condition="Verification passes",
                source_candidate_id=truth.id,
                source_session_id="cleanup-session",
                source_ids=[truth.id, "cleanup-session"],
            )
            await backend.structured_store.save_skill(skill)
            backend.transcript_store.record_distill_completion_outcome(
                snapshot.distill_job_id,
                disposition="promoted",
                reason_codes=["truth_promoted"],
                promotion_summary={"confirmed": 1},
                source_cleanup_status="retained",
            )

            begun = begin_processed_source_cleanup(
                backend,
                job_id=snapshot.distill_job_id,
                native_preview={
                    "locator_sha256": "a" * 64,
                    "counts": {"planned": 1},
                },
            )
            assert begun["success"] is True
            in_progress = backend.transcript_store.list_deletion_audit(
                project_name="demo"
            )
            assert len(in_progress) == 1
            assert in_progress[0]["status"] == "in_progress"

            result = await cleanup_processed_source(
                backend,
                job_id=snapshot.distill_job_id,
                native_cleanup={
                    "status": "deleted",
                    "path": "C:/private/cleanup-session.jsonl",
                    "reason_code": "native_source_deleted",
                },
                receipt_id=begun["receipt_id"],
            )

            assert result["success"] is True, result
            assert result["status"] == "deleted"
            assert result["receipt_id"]
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is None
            assert backend.verbatim_store.index.get(
                "observations", str(snapshot.observation_id)
            ) is None
            assert backend.transcript_store.list_chunks(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            ) == []
            assert backend.transcript_store.reconstruct_raw(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            ) == b""
            assert backend.transcript_store.list_distill_checkpoints(
                snapshot.distill_job_id
            ) == []

            retained = await backend.structured_store.get_memory_entry(truth.id)
            assert retained is not None
            assert retained.content == truth.content
            assert retained.status == "auto_confirmed"
            assert retained.source == "processed_source_pruned"
            assert retained.distill_job_id is None
            assert retained.provenance == {
                "evidence_state": "source_pruned",
                "cleanup_receipt_id": result["receipt_id"],
            }
            assert retained.evidence_basis == "repository"
            assert retained.verification_outcome == "verified"
            assert retained.verification_refs[0].locator is None
            assert retained.verification_refs[0].locator_sha256 == hashlib.sha256(
                b"private/path.md"
            ).hexdigest()
            assert retained.verification_refs[0].content_sha256 == "b" * 64
            wake = await build_wake_injection(
                backend,
                "demo",
                apply_surface_side_effects=False,
            )
            assert truth.content in wake
            assert private_text not in wake
            retained_rule = await backend.structured_store.get_confirmed_rule(
                confirmed_rule.id
            )
            assert retained_rule is not None
            assert retained_rule.pattern == confirmed_rule.pattern
            assert retained_rule.source_session_id == ""
            assert retained_rule.provenance == {
                "evidence_state": "source_pruned",
                "cleanup_receipt_id": result["receipt_id"],
            }
            retained_skill = await backend.structured_store.get_skill(skill.id)
            assert retained_skill is not None
            assert retained_skill.steps == skill.steps
            assert retained_skill.source_session_id == ""
            assert "cleanup-session" not in retained_skill.source_ids

            job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.session_id == ""
            assert job.project_root == ""
            assert job.source_cleanup_status == "deleted"
            assert private_text not in str(job.to_dict())

            receipts = backend.transcript_store.list_deletion_audit(
                project_name="demo"
            )
            assert len(receipts) == 1
            assert receipts[0]["kind"] == "processed_source_cleanup"
            assert receipts[0]["status"] == "succeeded"
            assert receipts[0]["native_cleanup"] == {
                "status": "deleted",
                "locator_sha256": "a" * 64,
                "planned_actions": 1,
            }
            assert "cleanup-session" not in str(receipts[0])
            assert "C:/private" not in str(receipts[0])
            assert private_text not in str(receipts[0])
            replayed = backend.transcript_store.finalize_distill_job(
                snapshot.distill_job_id,
                semantic_review={
                    "final_user_request": private_text,
                    "final_outcome": private_text,
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                },
            )
            assert replayed.id == snapshot.distill_job_id
            assert replayed.source_cleanup_status == "deleted"
            recapture = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="cleanup-session",
                    client="codex",
                    raw_content=private_text,
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="cleanup-session",
                source_kind="jsonl",
                source_uri="file:///cleanup-session.jsonl",
                source_text=private_text,
            )
            assert recapture.action == "ignored"
            assert recapture.reason == "hard_delete_tombstone"
        finally:
            await backend.close()

    _run(run())


def test_cleanup_fails_closed_while_candidate_is_unresolved(
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
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id="pending-session",
                private_text="pending raw evidence",
            )
            pending = MemoryEntry(
                id="pending-memory",
                project_name="demo",
                category="decision",
                content="Not reviewed yet",
                status="pending",
                source=str(snapshot.observation_id),
                distill_job_id=snapshot.distill_job_id,
            )
            await backend.structured_store.save_memory_entry(pending)

            result = await cleanup_processed_source(
                backend,
                job_id=snapshot.distill_job_id,
                native_cleanup={"status": "deleted"},
            )

            assert result["success"] is False
            assert result["status"] == "partial_failure"
            assert "unresolved_candidates" in result["reason_codes"]
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is not None
            assert backend.transcript_store.list_chunks(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            )
            assert await backend.structured_store.get_memory_entry(pending.id) is not None
            job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
            assert job is not None
            assert job.source_cleanup_status == "partial_failure"
        finally:
            await backend.close()

    _run(run())


def test_cleanup_completes_no_candidate_session_without_creating_truth(
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
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id="low-value-session",
                private_text="hello only",
            )
            backend.transcript_store.record_distill_completion_outcome(
                snapshot.distill_job_id,
                disposition="no_candidate",
                reason_codes=["no_durable_candidate"],
                promotion_summary={"promoted": 0},
                source_cleanup_status="retained",
            )
            result = await cleanup_processed_source(
                backend,
                job_id=snapshot.distill_job_id,
                native_cleanup={"status": "deleted"},
            )

            assert result["success"] is True
            job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
            assert job is not None
            assert job.completion_disposition == "no_candidate"
            assert job.source_cleanup_status == "deleted"
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is None
        finally:
            await backend.close()

    _run(run())


def test_unsupported_native_cleanup_retains_all_local_evidence(
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
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id="unsupported-session",
                private_text="retained raw evidence",
            )
            result = await cleanup_processed_source(
                backend,
                job_id=snapshot.distill_job_id,
                native_cleanup={
                    "status": "unsupported",
                    "reason_code": "shared_database_unsupported",
                },
            )

            assert result["success"] is False
            assert result["status"] == "unsupported"
            assert await backend.verbatim_store.get(str(snapshot.observation_id)) is not None
            assert backend.transcript_store.list_chunks(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            )
            job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
            assert job is not None
            assert job.source_cleanup_status == "unsupported"
        finally:
            await backend.close()

    _run(run())


def test_existing_post_turn_maintenance_retry_cleans_quiet_retained_source(
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
            session_id = "019f0000-0000-7000-8000-000000000099"
            private_text = "quiet completed native transcript"
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id=session_id,
                private_text=private_text,
            )
            native_root = tmp_path / ".codex" / "sessions"
            native_path = native_root / f"rollout-2026-07-28-{session_id}.jsonl"
            native_path.parent.mkdir(parents=True)
            native_path.write_bytes(private_text.encode("utf-8"))
            old = time.time() - 300
            os.utime(native_path, (old, old))
            source = snapshot.source
            source.source_uri = native_path.absolute().as_uri()
            source.metadata = {
                **source.metadata,
                "native_source_uri": source.source_uri,
                "native_input_sha256": hashlib.sha256(
                    private_text.encode("utf-8")
                ).hexdigest(),
                "native_cleanup_descriptor": {
                    "version": 1,
                    "allowed_root_uris": [native_root.absolute().as_uri()],
                },
            }
            backend.transcript_store.save_source(source)
            backend.transcript_store.record_distill_completion_outcome(
                snapshot.distill_job_id,
                disposition="no_candidate",
                reason_codes=["no_durable_candidate"],
                promotion_summary={"suggested": 0, "promoted": 0, "rejected": 0},
                source_cleanup_status="retained",
            )

            cooled_down = await retry_retained_source_cleanups(
                backend,
                project_name="demo",
                authorized=True,
            )
            assert cooled_down["attempted"] == 0

            result = await retry_retained_source_cleanups(
                backend,
                project_name="demo",
                authorized=True,
                minimum_age_seconds=0,
            )

            assert result["deleted"] == 1
            assert not native_path.exists()
            assert backend.transcript_store.reconstruct_raw(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            ) == b""
            completed = backend.transcript_store.get_distill_job(
                snapshot.distill_job_id
            )
            assert completed is not None
            assert completed.completion_disposition == "no_candidate"
            assert completed.source_cleanup_status == "deleted"
        finally:
            await backend.close()

    _run(run())


def test_existing_post_turn_maintenance_retries_partial_failure(
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
            session_id = "019f0000-0000-7000-8000-000000000098"
            private_text = "retry cleanup after transient failure"
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id=session_id,
                private_text=private_text,
            )
            native_root = tmp_path / ".codex" / "sessions"
            native_path = native_root / f"rollout-2026-07-28-{session_id}.jsonl"
            native_path.parent.mkdir(parents=True)
            native_path.write_bytes(private_text.encode("utf-8"))
            old = time.time() - 300
            os.utime(native_path, (old, old))
            source = snapshot.source
            source.source_uri = native_path.absolute().as_uri()
            source.metadata = {
                **source.metadata,
                "native_source_uri": source.source_uri,
                "native_input_sha256": hashlib.sha256(
                    private_text.encode("utf-8")
                ).hexdigest(),
                "native_cleanup_descriptor": {
                    "version": 1,
                    "allowed_root_uris": [native_root.absolute().as_uri()],
                },
            }
            backend.transcript_store.save_source(source)
            backend.transcript_store.record_distill_completion_outcome(
                snapshot.distill_job_id,
                disposition="no_candidate",
                reason_codes=["no_durable_candidate", "dream_postprocess_failed"],
                promotion_summary={"suggested": 0, "promoted": 0, "rejected": 0},
                source_cleanup_status="partial_failure",
            )

            result = await retry_retained_source_cleanups(
                backend,
                project_name="demo",
                authorized=True,
                minimum_age_seconds=0,
            )

            assert result["attempted"] == 1
            assert result["deleted"] == 1
            assert not native_path.exists()
            completed = backend.transcript_store.get_distill_job(
                snapshot.distill_job_id
            )
            assert completed is not None
            assert completed.source_cleanup_status == "deleted"
        finally:
            await backend.close()

    _run(run())


def test_cleanup_fails_closed_when_source_revision_changed(
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
            first = await _completed_snapshot(
                backend,
                project,
                session_id="racing-session",
                private_text="first completed revision",
            )
            second = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="racing-session",
                    client="codex",
                    raw_content="newer revision must survive",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="racing-session",
                source_kind="jsonl",
                source_uri="file:///racing-session.jsonl",
                source_text="newer revision must survive",
            )
            assert second.source is not None
            assert first.source is not None
            assert second.source.source_revision != first.source.source_revision

            result = await cleanup_processed_source(
                backend,
                job_id=first.distill_job_id,
                native_cleanup={"status": "deleted"},
            )

            assert result["success"] is False
            assert result["status"] == "partial_failure"
            assert backend.transcript_store.reconstruct_raw(
                second.source.id,
                source_revision=second.source.source_revision,
            ) == b"newer revision must survive"
            assert await backend.verbatim_store.get(str(second.observation_id)) is not None
        finally:
            await backend.close()

    _run(run())


def test_cleanup_prunes_every_historical_revision_for_logical_source(
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
            first = await _completed_snapshot(
                backend,
                project,
                session_id="revision-history",
                private_text="old revision secret",
            )
            second = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="revision-history",
                    client="codex",
                    raw_content="new revision secret",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="revision-history",
                source_kind="jsonl",
                source_uri="file:///revision-history.jsonl",
                source_text="new revision secret",
            )
            assert second.distill_job_id is not None
            claims = backend.transcript_store.claim_distill_chunks(
                second.distill_job_id,
                lease_owner="cleanup-test-new",
                limit=100,
            )
            for chunk, _checkpoint in claims:
                backend.transcript_store.checkpoint_distill_chunk(
                    second.distill_job_id,
                    chunk.id,
                    lease_owner="cleanup-test-new",
                    result={"outline": "new revision secret"},
                )
            backend.transcript_store.finalize_distill_job(
                second.distill_job_id,
                semantic_review={
                    "final_user_request": "new",
                    "final_outcome": "done",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                },
            )
            backend.transcript_store.record_distill_completion_outcome(
                second.distill_job_id,
                disposition="no_candidate",
                reason_codes=[],
                promotion_summary={},
                source_cleanup_status="retained",
            )
            _content, _summary, projection = build_append_aware_distill_projection(
                "new revision secret",
                source_revision=second.source.source_revision,
                source_bytes=b"new revision secret",
            )
            projection["source_id"] = second.source.id
            backend.transcript_store.save_distill_projection(projection)

            result = await cleanup_processed_source(
                backend,
                job_id=second.distill_job_id,
                native_cleanup={"status": "deleted"},
            )

            assert result["success"] is True
            assert result["counts"]["revisions_pruned"] == 2
            assert result["counts"]["semantic_projections_deleted"] == 1
            assert backend.transcript_store.get_distill_projection(
                second.source.id,
                second.source.source_revision,
                record_version=DISTILL_INCREMENTAL_PROJECTION,
            ) is None
            assert backend.transcript_store.reconstruct_raw(
                first.source.id,
                source_revision=first.source.source_revision,
            ) == b""
            assert backend.transcript_store.reconstruct_raw(
                second.source.id,
                source_revision=second.source.source_revision,
            ) == b""
            old_recapture = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="revision-history",
                    client="codex",
                    raw_content="old revision secret",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="revision-history",
                source_kind="jsonl",
                source_uri="file:///revision-history.jsonl",
                source_text="old revision secret",
            )
            assert old_recapture.action == "ignored"
            assert old_recapture.reason == "hard_delete_tombstone"
        finally:
            await backend.close()

    _run(run())


def test_managed_migration_backup_blocks_cleanup_before_native_delete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    project = tmp_path / "project"
    project.mkdir()

    async def run() -> None:
        data_dir = tmp_path / "data"
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            snapshot = await _completed_snapshot(
                backend,
                project,
                session_id="backup-session",
                private_text="managed backup secret",
            )
            backend.transcript_store.record_distill_completion_outcome(
                snapshot.distill_job_id,
                disposition="no_candidate",
                reason_codes=[],
                promotion_summary={},
                source_cleanup_status="retained",
            )
            backup = data_dir / "store_v2" / "backups" / "canonical-test.sqlite"
            backup.parent.mkdir(parents=True)
            source_db = sqlite3.connect(canonical_store_path(data_dir))
            backup_db = sqlite3.connect(backup)
            try:
                source_db.backup(backup_db)
            finally:
                backup_db.close()
                source_db.close()

            begun = begin_processed_source_cleanup(
                backend,
                job_id=snapshot.distill_job_id,
                native_preview={
                    "locator_sha256": "b" * 64,
                    "counts": {"planned": 1},
                },
            )

            assert begun["success"] is False
            assert begun["reason_codes"] == [
                "managed_backup_contains_source_evidence"
            ]
            assert backend.transcript_store.reconstruct_raw(
                snapshot.source.id,
                source_revision=snapshot.source.source_revision,
            ) == b"managed backup secret"
        finally:
            await backend.close()

    _run(run())


def test_cleanup_does_not_cascade_by_ambiguous_session_id(
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
            session_id = "shared-session-id"
            first = await _completed_snapshot(
                backend,
                project,
                session_id=session_id,
                private_text="first source evidence",
            )
            second = await persist_session_snapshot(
                backend,
                Observation(
                    session_id=session_id,
                    client="cursor",
                    raw_content="second source must survive",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                ),
                project_name="demo",
                project_root=str(project),
                client="cursor",
                session_id=session_id,
                source_kind="jsonl",
                source_uri="file:///alternate/shared-session-id.jsonl",
                source_text="second source must survive",
            )
            assert first.source is not None
            assert second.source is not None
            assert first.source.id != second.source.id
            ambiguous_truth = MemoryEntry(
                id="other-source-truth",
                project_name="demo",
                category="decision",
                content="This record belongs to the other logical source.",
                confidence=0.95,
                status="auto_confirmed",
                source="manual",
                provenance={"session_id": session_id, "owner": "second-source"},
            )
            await backend.structured_store.save_memory_entry(ambiguous_truth)
            backend.transcript_store.record_distill_completion_outcome(
                first.distill_job_id,
                disposition="no_candidate",
                reason_codes=["no_durable_candidate"],
                promotion_summary={"promoted": 0},
                source_cleanup_status="retained",
            )

            result = await cleanup_processed_source(
                backend,
                job_id=first.distill_job_id,
                native_cleanup={"status": "deleted"},
            )

            assert result["success"] is True, result
            preserved = await backend.structured_store.get_memory_entry(
                ambiguous_truth.id
            )
            assert preserved is not None
            assert preserved.source == "manual"
            assert preserved.provenance == {
                "session_id": session_id,
                "owner": "second-source",
            }
            assert await backend.verbatim_store.get(str(second.observation_id)) is not None
            assert backend.transcript_store.reconstruct_raw(
                second.source.id,
                source_revision=second.source.source_revision,
            ) == b"second source must survive"
        finally:
            await backend.close()

    _run(run())
