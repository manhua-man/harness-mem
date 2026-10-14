"""Governance updates use existing handoffs without reopening memory jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.mcp import governance_handlers, tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def handoff_backend(tmp_path, monkeypatch):
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    # Seed unrelated current truth so accidental deletion is observable too.
    entry = KnowledgeEntry(
        project_name="project", module_path=["Policy"], title="Keep sources",
        statement="Retain source material during handoff updates.",
    )
    backend.structured_store.write_record_payload("knowledge_entries", entry.id, entry.to_dict())

    def make_job(status="reviewing", project="project", session="source"):
        native = tmp_path / f"native-source-{project}-{session}.jsonl"
        text = "User: Finish the follow-up.\nAssistant: Work remains pending.\n"
        native.write_text(text, encoding="utf-8")
        captured = asyncio.run(persist_session_snapshot(
            backend,
            Observation(session_id=session, client="codex", raw_content=text,
                        content_type="transcript", metadata={}),
            project_name=project, project_root=str(tmp_path), client="codex",
            session_id=session, source_kind="jsonl", source_uri=native.as_uri(),
            source_text=text, capture_config=MergedConfig(),
        ))
        job = backend.transcript_store.get_distill_job(captured.distill_job_id)
        # Fixture setup only: the handler must leave the entire ledger unchanged.
        job.status = status
        ledger = backend.transcript_store
        with ledger._lock, ledger._conn:
            ledger._distill._upsert_job_locked(job)
        return job

    yield backend, make_job
    asyncio.run(backend.close())


def _handoffs(backend, project="project"):
    return asyncio.run(backend.structured_store.get_latest_handoffs(project, limit=None))


def _protected_state(backend):
    store = backend.structured_store
    return (
        {name: store.list_record_payloads(name)
         for name in store._subdirs if name != "task_handoffs"},
        tuple(backend.transcript_store._conn.iterdump()),
        {str(path): path.read_bytes()
         for path in backend.data_dir.parent.glob("native-source-*.jsonl")},
    )


def _govern(backend, task_id="follow-up", **overrides):
    protected = _protected_state(backend)
    before = backend.structured_store.list_record_payloads("task_handoffs")
    result = governance_handlers.tool_govern_memory(action="handoff", arguments={
        "project_name": "project", "task_id": task_id,
        "summary": "Updated progress", "status": "in_progress", **overrides,
    })
    assert _protected_state(backend) == protected
    if not result["success"]:
        assert backend.structured_store.list_record_payloads("task_handoffs") == before
    return result


def _seed_handoff(backend, *, task_id="follow-up", context=None, **kwargs):
    handoff = TaskHandoff(
        project_name="project", task_id=task_id, summary="Old progress",
        status="pending", context=context or {}, **kwargs,
    )
    asyncio.run(backend.structured_store.save_task_handoff(handoff))
    return handoff


def test_same_task_updates_existing_id_and_preserves_metadata(handoff_backend):
    backend, _ = handoff_backend
    old = _seed_handoff(
        backend, context={"paths": ["work.py"], "checkpoint": {"step": 2}},
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
        last_activity=datetime(2020, 1, 2, tzinfo=timezone.utc),
        provenance={"session_id": "original"},
    )
    result = _govern(backend, summary="New progress", status="blocked",
                     next_steps=["Finish tests"], blockers=["Pending review"])
    assert result["success"], result
    assert result["handoff_id"] == old.id
    saved, = _handoffs(backend)
    assert (saved.summary, saved.status, saved.next_steps, saved.blockers) == (
        "New progress", "blocked", ["Finish tests"], ["Pending review"],
    )
    assert saved.context == old.context and saved.provenance == old.provenance
    assert saved.created_at == old.created_at
    assert saved.updated_at > old.updated_at and saved.last_activity > old.last_activity


@pytest.mark.parametrize("explicit", [False, True])
def test_reviewing_bound_task_updates_in_place(handoff_backend, explicit):
    backend, make_job = handoff_backend
    job = make_job()
    first = _govern(backend, distill_job_id=job.id, next_steps=["Old next step"])
    assert first["success"], first
    old, = _handoffs(backend)
    result = _govern(backend, status="blocked", blockers=["Need review"],
                     **({"distill_job_id": job.id} if explicit else {}))
    assert result["success"] and result["handoff_id"] == old.id
    saved, = _handoffs(backend)
    assert saved.context == old.context == {"distill_job_id": job.id}
    assert saved.created_at == old.created_at
    assert saved.next_steps == [] and saved.blockers == ["Need review"]


@pytest.mark.parametrize("explicit", [False, True])
def test_completed_bound_job_can_close_existing_handoff_after_reopen(handoff_backend, explicit):
    backend, make_job = handoff_backend
    job = make_job(status="completed")
    old = _seed_handoff(backend, context={"distill_job_id": job.id, "paths": ["work.py"]})
    asyncio.run(backend.close())
    asyncio.run(backend.init())
    result = _govern(backend, status="done",
                     **({"distill_job_id": job.id} if explicit else {}))
    assert result["success"], result
    assert result["handoff_id"] == old.id and result["distill_job_id"] == job.id
    saved, = _handoffs(backend)
    assert saved.status == "done" and saved.context == old.context
    assert saved.created_at == old.created_at
    assert _govern(backend, status="done")["handoff_id"] == old.id


def test_completed_legacy_task_id_binding_can_close_without_rewriting_context(handoff_backend):
    backend, make_job = handoff_backend
    job = make_job(status="completed")
    old = _seed_handoff(backend, task_id=job.id, context={"paths": ["old.py"]})
    result = _govern(backend, task_id=job.id, status="done")
    assert result["success"] and result["handoff_id"] == old.id
    saved, = _handoffs(backend)
    assert saved.context == old.context and saved.created_at == old.created_at
    assert result["distill_job_id"] == job.id


@pytest.mark.parametrize("status", ["in_progress", "pending", "blocked"])
def test_completed_job_cannot_reopen_or_extend_handoff(handoff_backend, status):
    backend, make_job = handoff_backend
    job = make_job(status="completed")
    _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, status=status)
    assert not result["success"] and "can only close" in result["error"]


@pytest.mark.parametrize("job_status", ["queued", "processing", "completed", "retryable", "parked", "failed", "stale"])
@pytest.mark.parametrize("status", ["in_progress", "done"])
def test_unknown_new_task_still_requires_review_ready_job(handoff_backend, job_status, status):
    backend, make_job = handoff_backend
    job = make_job(status=job_status)
    _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, task_id="follow-up-new", distill_job_id=job.id, status=status)
    assert not result["success"] and "all chunks are reviewed" in result["error"]
    # The implicit task_id binding cannot bypass the new-task gate either.
    result = _govern(backend, task_id=job.id, status=status)
    assert not result["success"] and "all chunks are reviewed" in result["error"]


@pytest.mark.parametrize("job_status", ["queued", "processing", "retryable", "parked", "failed", "stale"])
def test_existing_handoff_does_not_bypass_non_review_ready_job(handoff_backend, job_status):
    backend, make_job = handoff_backend
    job = make_job(status=job_status)
    _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, status="done")
    assert not result["success"] and "reviewed job" in result["error"]


@pytest.mark.parametrize("other_project", ["project", "other"])
def test_existing_handoff_rejects_different_job(handoff_backend, other_project):
    backend, make_job = handoff_backend
    job = make_job()
    other = make_job(project=other_project, session="other-job")
    _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, distill_job_id=other.id, status="done")
    assert not result["success"] and "another distill job" in result["error"]


def test_existing_unbound_handoff_cannot_be_rebound_to_job(handoff_backend):
    backend, make_job = handoff_backend
    job = make_job()
    _seed_handoff(backend)
    result = _govern(backend, distill_job_id=job.id)
    assert not result["success"] and "another distill job" in result["error"]


@pytest.mark.parametrize("existing", [False, True])
def test_wrong_project_job_is_rejected(handoff_backend, existing):
    backend, make_job = handoff_backend
    job = make_job(project="other")
    if existing:
        _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, distill_job_id=job.id, status="done")
    assert not result["success"] and "another project" in result["error"]


@pytest.mark.parametrize("existing", [False, True])
def test_missing_job_is_rejected(handoff_backend, existing):
    backend, _ = handoff_backend
    if existing:
        _seed_handoff(backend, context={"distill_job_id": "missing-job"})
    result = _govern(backend, distill_job_id="missing-job", status="done")
    assert not result["success"] and "not found" in result["error"]


@pytest.mark.parametrize("bound", [False, True])
def test_duplicate_task_is_ambiguous_even_with_explicit_job(handoff_backend, bound):
    backend, make_job = handoff_backend
    job = make_job()
    old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _seed_handoff(backend, context={"distill_job_id": job.id} if bound else {}, last_activity=old_time)
    # Duplicates and the desired task may be older than the default five rows.
    for index in range(6):
        _seed_handoff(backend, task_id=f"unrelated-{index}")
    _seed_handoff(backend, context={"distill_job_id": job.id})
    result = _govern(backend, distill_job_id=job.id, status="done")
    assert not result["success"] and "multiple handoffs" in result["error"]


def test_update_finds_old_task_beyond_default_limit(handoff_backend):
    backend, _ = handoff_backend
    old = _seed_handoff(backend, last_activity=datetime(2020, 1, 1, tzinfo=timezone.utc))
    for index in range(6):
        _seed_handoff(backend, task_id=f"newer-{index}")
    result = _govern(backend, status="done")
    assert result["success"] and result["handoff_id"] == old.id
    assert len(_handoffs(backend)) == 7


def test_same_task_in_other_project_is_unchanged(handoff_backend):
    backend, _ = handoff_backend
    other = TaskHandoff(project_name="other", task_id="follow-up", summary="Other project")
    asyncio.run(backend.structured_store.save_task_handoff(other))
    first = _govern(backend)
    assert first["success"] and first["handoff_id"] != other.id
    second = _govern(backend, status="done")
    assert second["success"] and second["handoff_id"] == first["handoff_id"]
    assert _handoffs(backend, "other")[0].to_dict() == other.to_dict()


def test_update_keeps_schema_validation(handoff_backend):
    backend, _ = handoff_backend
    _seed_handoff(backend)
    result = _govern(backend, next_steps="invalid list")
    assert not result["success"] and "next_steps" in result["error"]
