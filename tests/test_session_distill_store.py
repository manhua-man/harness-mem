from __future__ import annotations

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


def _save_source(store: TranscriptStore, value: str) -> TranscriptSource:
    source_id = transcript_source_id(
        client="cursor",
        project_name="demo",
        session_id="session-1",
    )
    native = value.encode("utf-8")
    revision = transcript_bytes_revision(native)
    source = TranscriptSource(
        id=source_id,
        project_name="demo",
        project_root="C:/work/demo",
        client="cursor",
        session_id="session-1",
        source_kind="file",
        source_uri="file:///session.jsonl",
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
        session_id="session-1",
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
