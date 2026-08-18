from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.storage.transcript_store import TranscriptStore
from harness_mem.transcript_chunking import (
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
    transcript_bytes_revision,
    transcript_source_id,
)


def _save_source(
    store: TranscriptStore,
    value: str,
    *,
    session_id: str = "session-1",
) -> TranscriptSource:
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id=session_id,
    )
    native = value.encode("utf-8")
    revision = transcript_bytes_revision(native)
    source = TranscriptSource(
        id=source_id,
        project_name="demo",
        project_root="C:/work/demo",
        client="cursor",
        session_id=session_id,
        source_kind="file",
        source_uri=f"file:///{session_id}.jsonl",
        source_revision=revision,
        raw_sha256=sha256_bytes(native),
        normalized_sha256=sha256_text(value),
        raw_size_bytes=len(native),
        normalized_size_bytes=len(native),
        status="syncing",
    )
    chunks = chunk_transcript_text(
        value,
        source_id=source_id,
        project_name="demo",
        client="cursor",
        session_id=session_id,
        source_revision=revision,
        max_chars=12,
    )
    store.save_snapshot(source, chunks, raw_bytes=native)
    return source


def test_job_claim_checkpoint_and_finalize(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(
        store,
        "turn one\nanswer one\nturn two\nanswer two\n",
    )

    job = store.enqueue_distill_job(source.id)
    duplicate = store.enqueue_distill_job(source.id)
    claims = store.claim_distill_chunks(
        job.id,
        lease_owner="agent-1",
        limit=20,
    )

    assert duplicate.id == job.id
    assert len(claims) == job.expected_chunk_count
    for chunk, checkpoint in claims:
        job = store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="agent-1",
            result={"summary": f"chunk {checkpoint.chunk_index}"},
        )
    assert job.status == "reviewing"

    completed = store.finalize_distill_job(
        job.id,
        semantic_review={
            "final_user_request": "finish the task",
            "final_outcome": "complete",
            "last_turn_status": "answered",
            "contradictions": [],
            "unfinished_work": [],
            "evidence_status": "answered",
            "promotion_decision": "promote",
        },
        output_candidate_ids=["candidate-1"],
    )
    assert completed.status == "completed"
    assert completed.structural_audit["coverage"] == "complete"
    assert completed.output_candidate_ids == ["candidate-1"]
    outcome = store.record_distill_completion_outcome(
        job.id,
        disposition="promoted",
        reason_codes=["durable_memory_promoted"],
        promotion_summary={"suggested": 1, "promoted": 1, "rejected": 0},
        source_cleanup_status="retained",
    )
    assert outcome.completion_disposition == "promoted"
    assert outcome.source_cleanup_status == "retained"
    store.mark_distill_historical_summary_unavailable(
        job.id,
        reason="immutable_note_missing_after_source_pruned",
    )
    backfilled = store.backfill_distill_session_summary(
        job.id,
        session_summary="The completed session implemented and verified the requested task.",
    )
    assert backfilled.semantic_review["session_summary"].startswith(
        "The completed session"
    )
    assert "historical_summary_status" not in backfilled.semantic_review
    assert "historical_summary_reason" not in backfilled.semantic_review
    store.close()


def test_review_lease_is_exclusive_and_expired_owner_is_recovered(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "User decision\nAssistant answer\n")
    job = store.enqueue_distill_job(source.id)
    for chunk, _checkpoint in store.claim_distill_chunks(
        job.id,
        lease_owner="chunk-reader",
        limit=100,
    ):
        store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="chunk-reader",
            result={"structural": True},
        )

    first = store.claim_distill_review(
        job.id,
        lease_owner="worker-a",
        execution_source="autonomous_worker",
        lease_seconds=30,
    )
    assert first is not None
    assert store.claim_distill_review(
        job.id,
        lease_owner="worker-b",
        execution_source="autonomous_worker",
        lease_seconds=30,
    ) is None

    current = store.get_distill_job(job.id)
    assert current is not None
    current.review_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    store._distill._upsert_job_locked(current)
    store._conn.commit()

    recovered = store.claim_distill_review(
        job.id,
        lease_owner="worker-b",
        execution_source="autonomous_worker",
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered.review_lease_owner == "worker-b"
    assert recovered.recovery_count == 1
    assert "expired_review_lease" in recovered.recovery_reason_codes
    store.close()


def test_active_review_lease_guards_final_write_boundary(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "User decision\nAssistant answer\n")
    job = store.enqueue_distill_job(source.id)
    for chunk, _checkpoint in store.claim_distill_chunks(
        job.id,
        lease_owner="chunk-reader",
        limit=100,
    ):
        store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="chunk-reader",
            result={"structural": True},
        )
    assert store.claim_distill_review(
        job.id,
        lease_owner="worker-a",
        execution_source="autonomous_worker",
        lease_seconds=30,
    ) is not None
    review = {
        "final_user_request": "review",
        "final_outcome": "complete",
        "last_turn_status": "answered",
        "contradictions": [],
        "unfinished_work": [],
        "evidence_status": "answered",
        "promotion_decision": "no_promotion",
    }

    with pytest.raises(PermissionError, match="review lease"):
        store.finalize_distill_job(job.id, semantic_review=review)
    with pytest.raises(PermissionError, match="review lease"):
        store.finalize_distill_job(
            job.id,
            semantic_review=review,
            review_lease_owner="worker-b",
        )
    completed = store.finalize_distill_job(
        job.id,
        semantic_review=review,
        review_lease_owner="worker-a",
    )
    assert completed.status == "completed"
    store.close()


def test_legacy_job_json_defaults_new_completion_fields_to_unknown() -> None:
    legacy = SessionDistillJob.from_dict(
        {
            "id": "legacy-job",
            "idempotency_key": "source:revision:lossless-distill-v1",
            "project_name": "demo",
            "project_root": "C:/work/demo",
            "client": "cursor",
            "session_id": "legacy-session",
            "source_id": "source",
            "source_revision": "revision",
            "status": "completed",
            "phase": "done",
            "output_candidate_ids": ["candidate-1"],
        }
    )

    assert legacy.completion_disposition is None
    assert legacy.source_cleanup_status is None
    assert legacy.completion_reason_codes == []
    assert legacy.promotion_summary == {}


def test_checkpoint_requires_current_lease_owner(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "turn\nanswer\n")
    job = store.enqueue_distill_job(source.id)
    chunk, _checkpoint = store.claim_distill_chunks(
        job.id,
        lease_owner="agent-1",
    )[0]

    with pytest.raises(PermissionError, match="not owned"):
        store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="agent-2",
            result={"summary": "wrong owner"},
        )
    store.close()


def test_new_revision_marks_older_active_job_stale(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    first = _save_source(store, "turn one\nanswer one\n")
    old_job = store.enqueue_distill_job(first.id)
    second = _save_source(store, "turn one\nanswer one\nturn two\n")

    new_job = store.enqueue_distill_job(second.id)

    assert new_job.id != old_job.id
    reloaded = store.get_distill_job(old_job.id)
    assert reloaded is not None
    assert reloaded.status == "stale"
    store.close()


def test_existing_current_job_reconciles_legacy_active_older_revision(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    first = _save_source(store, "turn one\nanswer one\n")
    old_job = store.enqueue_distill_job(first.id)
    second = _save_source(store, "turn one\nanswer one\nturn two\n")
    current_job = store.enqueue_distill_job(second.id)

    row = store._conn.execute(  # type: ignore[attr-defined]
        "SELECT data FROM distill_jobs WHERE id = ?",
        (old_job.id,),
    ).fetchone()
    assert row is not None
    payload = json.loads(row["data"])
    payload["status"] = "retryable"
    store._conn.execute(  # type: ignore[attr-defined]
        "UPDATE distill_jobs SET status = 'retryable', data = ? WHERE id = ?",
        (json.dumps(payload), old_job.id),
    )
    store._conn.commit()  # type: ignore[attr-defined]

    replayed = store.enqueue_distill_job(second.id, active_limit=2)

    assert replayed.id == current_job.id
    stored_current = store.get_distill_job(current_job.id)
    assert stored_current is not None
    assert replayed.status == stored_current.status
    reconciled = store.get_distill_job(old_job.id)
    assert reconciled is not None
    assert reconciled.status == "stale"
    assert reconciled.error == "superseded by a newer transcript source revision"
    store.close()


def test_defer_failed_job_releases_lease_and_keeps_it_retryable(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "turn\nanswer\n")
    job = store.enqueue_distill_job(source.id)
    store.claim_distill_chunks(job.id, lease_owner="broken-agent")

    deferred = store.defer_distill_job(job.id, error="parser failed")
    checkpoints = store.list_distill_checkpoints(job.id)

    assert deferred.status == "retryable"
    assert deferred.error == "parser failed"
    assert checkpoints[0].status == "retryable"
    assert checkpoints[0].lease_owner is None
    assert checkpoints[0].lease_until is None
    store.close()


def test_reconcile_preserves_review_retry_backoff_until_due(tmp_path: Path) -> None:
    """A review-stage timeout must not be reactivated by structural recovery."""

    store = TranscriptStore(tmp_path)
    source = _save_source(store, "turn\nanswer\n")
    job = store.enqueue_distill_job(source.id)
    claims = store.claim_distill_chunks(job.id, lease_owner="worker")
    for chunk, _checkpoint in claims:
        store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="worker",
            result={"summary": "complete"},
        )
    reviewing = store.get_distill_job(job.id)
    assert reviewing is not None and reviewing.status == "reviewing"

    deferred = store.defer_distill_job(job.id, error="semantic provider timed out")
    assert deferred.status == "retryable"
    assert deferred.retry_after is not None

    store.reconcile_distill_jobs(
        project_name="demo",
        now=deferred.retry_after - timedelta(seconds=1),
    )
    waiting = store.get_distill_job(job.id)
    assert waiting is not None
    assert waiting.status == "retryable"
    assert waiting.retry_after == deferred.retry_after

    store.reconcile_distill_jobs(
        project_name="demo",
        now=deferred.retry_after + timedelta(seconds=1),
    )
    ready = store.get_distill_job(job.id)
    assert ready is not None
    assert ready.status == "reviewing"
    assert ready.retry_after is None
    store.close()


def test_reconcile_expired_lease_records_recovery_and_bounds_retries(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "turn\nanswer\n")
    job = store.enqueue_distill_job(source.id)
    store.claim_distill_chunks(job.id, lease_owner="crashed-agent")

    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    row = store._conn.execute(  # type: ignore[attr-defined]
        "SELECT data FROM distill_job_chunks WHERE job_id = ?",
        (job.id,),
    ).fetchone()
    assert row is not None
    payload = json.loads(row["data"])
    payload["lease_until"] = expired_at.isoformat()
    store._conn.execute(  # type: ignore[attr-defined]
        "UPDATE distill_job_chunks SET data = ?, lease_until = ? WHERE job_id = ?",
        (json.dumps(payload), expired_at.isoformat(), job.id),
    )
    store._conn.commit()  # type: ignore[attr-defined]

    first = store.reconcile_distill_jobs(
        project_name="demo",
        now=datetime.now(timezone.utc),
        recovery_budget=2,
    )
    recovered = store.get_distill_job(job.id)
    assert first["recovered"] == 1
    assert recovered is not None
    assert recovered.status == "retryable"
    assert recovered.recovery_count == 1
    assert "expired_chunk_lease" in recovered.recovery_reason_codes
    assert recovered.retry_after is not None
    assert store.list_distill_checkpoints(job.id)[0].status == "retryable"

    # A second restart/lease expiry consumes the bounded budget and becomes a
    # terminal failure instead of remaining active forever.
    row = store._conn.execute(  # type: ignore[attr-defined]
        "SELECT data FROM distill_job_chunks WHERE job_id = ?",
        (job.id,),
    ).fetchone()
    assert row is not None
    payload = json.loads(row["data"])
    payload.update(
        {
            "status": "processing",
            "lease_owner": "second-crashed-agent",
            "lease_until": expired_at.isoformat(),
        }
    )
    store._conn.execute(  # type: ignore[attr-defined]
        "UPDATE distill_job_chunks SET data = ?, status = 'processing', lease_owner = ?, lease_until = ? WHERE job_id = ?",
        (
            json.dumps(payload),
            "second-crashed-agent",
            expired_at.isoformat(),
            job.id,
        ),
    )
    store._conn.commit()  # type: ignore[attr-defined]
    second = store.reconcile_distill_jobs(
        project_name="demo",
        now=datetime.now(timezone.utc),
        recovery_budget=2,
    )
    exhausted = store.get_distill_job(job.id)
    assert second["failed_recovery_budget"] == 1
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.recovery_exhausted_at is not None
    assert store.list_distill_checkpoints(job.id)[0].status == "failed"
    store.close()


def test_direct_claim_counts_expired_leases_and_exhausts_recovery_budget(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(
        store,
        "turn one\nanswer one\nturn two\nanswer two\n",
    )
    job = store.enqueue_distill_job(source.id)

    def expire_current_claim() -> None:
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        row = store._conn.execute(  # type: ignore[attr-defined]
            "SELECT data FROM distill_job_chunks WHERE job_id = ? AND status = 'processing'",
            (job.id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row["data"])
        payload["lease_until"] = expired_at.isoformat()
        store._conn.execute(  # type: ignore[attr-defined]
            "UPDATE distill_job_chunks SET data = ?, lease_until = ? "
            "WHERE job_id = ? AND status = 'processing'",
            (json.dumps(payload), expired_at.isoformat(), job.id),
        )
        store._conn.commit()  # type: ignore[attr-defined]

    def release_backoff() -> None:
        current = store.get_distill_job(job.id)
        assert current is not None
        payload = current.to_dict()
        payload["retry_after"] = None
        store._conn.execute(  # type: ignore[attr-defined]
            "UPDATE distill_jobs SET data = ? WHERE id = ?",
            (json.dumps(payload), job.id),
        )
        store._conn.commit()  # type: ignore[attr-defined]

    assert store.claim_distill_chunks(job.id, lease_owner="agent-1")
    for recovery_number in range(1, 4):
        expire_current_claim()

        # The recovery call only records the expired lease. It must never
        # reclaim semantic work in the same transaction.
        assert store.claim_distill_chunks(job.id, lease_owner="recovery") == []
        recovered = store.get_distill_job(job.id)
        assert recovered is not None
        assert recovered.recovery_count == recovery_number

        if recovery_number < recovered.recovery_budget:
            assert recovered.status == "retryable"
            assert recovered.retry_after is not None
            checkpoint = store.list_distill_checkpoints(job.id)[0]
            assert checkpoint.status == "retryable"
            assert checkpoint.lease_owner is None

            # Backoff blocks an immediate direct claim. Advancing it here
            # simulates the scheduler returning after the durable delay.
            assert store.claim_distill_chunks(job.id, lease_owner="too-soon") == []
            release_backoff()
            assert store.claim_distill_chunks(
                job.id,
                lease_owner=f"agent-{recovery_number + 1}",
            )

    exhausted = store.get_distill_job(job.id)
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.recovery_count == exhausted.recovery_budget == 3
    assert exhausted.recovery_exhausted_at is not None
    terminal_checkpoints = store.list_distill_checkpoints(job.id)
    assert len(terminal_checkpoints) > 1
    assert all(checkpoint.status == "failed" for checkpoint in terminal_checkpoints)
    assert all(checkpoint.lease_owner is None for checkpoint in terminal_checkpoints)
    assert all(checkpoint.lease_until is None for checkpoint in terminal_checkpoints)

    # A terminal job cannot be claimed or consume a fourth recovery event.
    assert store.claim_distill_chunks(job.id, lease_owner="agent-4") == []
    terminal = store.get_distill_job(job.id)
    assert terminal is not None
    assert terminal.recovery_count == 3
    store.close()


def test_reconcile_advances_parent_when_checkpoints_are_complete(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    source = _save_source(store, "turn one\nanswer one\nturn two\nanswer two\n")
    job = store.enqueue_distill_job(source.id)
    for chunk, checkpoint in store.claim_distill_chunks(
        job.id,
        lease_owner="agent",
        limit=20,
    ):
        store.checkpoint_distill_chunk(
            job.id,
            chunk.id,
            lease_owner="agent",
            result={"summary": f"chunk {checkpoint.chunk_index}"},
        )

    reviewing = store.get_distill_job(job.id)
    assert reviewing is not None and reviewing.status == "reviewing"
    payload = reviewing.to_dict()
    payload.update(
        {"status": "processing", "phase": "chunks", "completed_chunk_count": 0}
    )
    store._conn.execute(  # type: ignore[attr-defined]
        "UPDATE distill_jobs SET data = ?, status = 'processing', phase = 'chunks' WHERE id = ?",
        (json.dumps(payload), job.id),
    )
    store._conn.commit()  # type: ignore[attr-defined]

    result = store.reconcile_distill_jobs(project_name="demo")
    reloaded = store.get_distill_job(job.id)
    assert result["advanced_to_review"] == 1
    assert reloaded is not None
    assert reloaded.status == "reviewing"
    assert reloaded.completed_chunk_count == reloaded.expected_chunk_count
    assert reloaded.last_progress_at is not None
    store.close()


def test_rebalance_parks_cold_jobs_and_refills_recent_first(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    sources = [
        _save_source(store, f"content-{index}", session_id=f"session-{index}")
        for index in range(4)
    ]
    jobs = [store.enqueue_distill_job(source.id) for source in sources]

    first = store.rebalance_distill_jobs(
        "demo",
        target_active=2,
        recent_first=True,
    )
    assert first["active"] == 2
    assert first["parked"] == 2
    assert first["selected_recent"] == 2
    assert [
        store.get_distill_job(job.id).status  # type: ignore[union-attr]
        for job in jobs
    ] == ["parked", "parked", "queued", "queued"]

    newest = jobs[-1]
    for chunk, _checkpoint in store.claim_distill_chunks(
        newest.id,
        lease_owner="agent",
        limit=20,
    ):
        store.checkpoint_distill_chunk(
            newest.id,
            chunk.id,
            lease_owner="agent",
            result={"summary": "done"},
        )
    store.finalize_distill_job(
        newest.id,
        semantic_review={
            "final_user_request": "review",
            "final_outcome": "complete",
            "last_turn_status": "answered",
            "contradictions": [],
            "unfinished_work": [],
            "evidence_status": "answered",
            "promotion_decision": "no_promotion",
        },
    )

    second = store.rebalance_distill_jobs(
        "demo",
        target_active=2,
        recent_first=True,
    )
    assert second["active"] == 2
    assert second["parked"] == 1
    promoted = store.get_distill_job(jobs[1].id)
    assert promoted is not None
    assert promoted.status == "queued"
    store.close()


def test_rebalance_uses_three_recent_then_one_oldest_lane(tmp_path: Path) -> None:
    store = TranscriptStore(tmp_path)
    jobs = [
        store.enqueue_distill_job(
            _save_source(store, f"content-{index}", session_id=f"fair-{index}").id
        )
        for index in range(6)
    ]

    selected_lanes: list[str | None] = []
    for _ in range(4):
        store.rebalance_distill_jobs("demo", target_active=1, recent_first=True)
        active = [
            job
            for job in (store.get_distill_job(item.id) for item in jobs)
            if job is not None and job.status == "queued"
        ]
        assert len(active) == 1
        job = active[0]
        selected_lanes.append(job.drainer_lane)
        for chunk, _checkpoint in store.claim_distill_chunks(
            job.id,
            lease_owner="fair-agent",
            limit=20,
        ):
            store.checkpoint_distill_chunk(
                job.id,
                chunk.id,
                lease_owner="fair-agent",
                result={"summary": "done"},
            )
        store.finalize_distill_job(
            job.id,
            semantic_review={
                "final_user_request": "review",
                "final_outcome": "complete",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
            },
        )

    assert selected_lanes == ["recent", "recent", "recent", "oldest"]
    store.close()


def test_deferred_job_has_exponential_backoff_and_does_not_block_healthy_work(
    tmp_path: Path,
) -> None:
    store = TranscriptStore(tmp_path)
    failed = store.enqueue_distill_job(
        _save_source(store, "failed", session_id="failed").id
    )
    healthy = store.enqueue_distill_job(
        _save_source(store, "healthy", session_id="healthy").id
    )
    store.claim_distill_chunks(failed.id, lease_owner="broken-agent")
    deferred = store.defer_distill_job(failed.id, error="parser failed")

    assert deferred.retry_after is not None
    assert deferred.retry_after > datetime.now(timezone.utc)
    result = store.rebalance_distill_jobs("demo", target_active=1, recent_first=True)
    reloaded_failed = store.get_distill_job(failed.id)
    reloaded_healthy = store.get_distill_job(healthy.id)
    assert result["retry_backoff"] == 1
    assert reloaded_failed is not None and reloaded_failed.status == "retryable"
    assert reloaded_healthy is not None and reloaded_healthy.status == "queued"
    store.close()
