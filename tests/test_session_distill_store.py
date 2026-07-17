from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

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
    store.close()


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
