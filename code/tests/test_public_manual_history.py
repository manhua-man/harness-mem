"""Public prepare_session_distill historical organization. tmp_path and fakes only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.commands.manual_distill import ManualBatchStore, is_manual_distill_job
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.distill import Distill
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _review():
    return {
        "session_summary": "The session exchanged a greeting without making durable decisions.",
        "final_user_request": "greeting", "final_outcome": "greeting answered",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "no_promotion",
    }


@pytest.fixture
def public_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    sentinel = tmp_path / "forbidden-default-store"
    import harness_mem.commands.support as support_module
    import harness_mem.mcp.distill_handlers as distill_handlers
    import harness_mem.storage.local_memory_backend as backend_module

    monkeypatch.setattr(backend_module, "DEFAULT_DATA_DIR", sentinel)
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", sentinel)
    monkeypatch.setattr(distill_handlers, "DEFAULT_DATA_DIR", sentinel)
    original_init = LocalMemoryBackend.__init__

    def guarded(self, data_dir):
        if Path(data_dir).resolve() == sentinel.resolve():
            raise AssertionError("default store was constructed")
        return original_init(self, data_dir)

    monkeypatch.setattr(LocalMemoryBackend, "__init__", guarded)
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    from harness_mem.commands import manual_distill, session_inventory

    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: CursorAdapter(None, projects_dir=projects))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "public-history-runtime")
    calls = []

    def bomb(*_args, **_kwargs):
        calls.append("build_semantic_executor")
        raise AssertionError("semantic executor must not be built")

    import harness_mem.autonomous.executors.registry as registry
    import harness_mem.autonomous.worker as worker

    monkeypatch.setattr(registry, "build_semantic_executor", bomb)
    monkeypatch.setattr(worker, "build_semantic_executor", bomb)

    def write(name, text="hello"):
        path = projects / "bucket" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"role": "user", "cwd": str(root), "message": {"content": [{"type": "text", "text": text}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello, ready to help."}]}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        return path

    handlers = tool_handlers
    yield backend, root, write, handlers, calls
    assert calls == []
    assert MergedConfig().distill_autonomous_enabled is False
    assert not sentinel.exists()
    if backend.initialized:
        asyncio.run(backend.close())


def _prepare(handlers, root, **kwargs):
    return handlers.tool_prepare_session_distill(project_name="project", project_root=str(root), **kwargs)


def _manifest(backend, batch_id, root):
    return ManualBatchStore(backend.data_dir).load(batch_id, "project", str(root))


def _rewrite_job(backend, job_id, **changes):
    distill = backend.transcript_store._distill
    with distill._lock:
        distill._conn.execute("BEGIN IMMEDIATE")
        try:
            job = distill._get_job_locked(job_id)
            updated = job.model_copy(update={"updated_at": datetime.now(timezone.utc), **changes})
            distill._upsert_job_locked(updated)
            distill._conn.commit()
        except Exception:
            distill._conn.rollback()
            raise


def test_manual_selection_pauses_without_progress_then_continues(public_history):
    backend, root, write, handlers, _calls = public_history
    with pytest.raises(ValueError, match="session selection"):
        Distill(backend.data_dir).prepare()
    correction = handlers.tool_prepare_session_distill(target_knowledge=[{"title": "Old rule", "statement": "Keep the old rule."}])
    assert correction["success"] is False
    assert "未改动" in correction["error"]

    source_a = write("a")
    source_b = write("b")
    originals = {source_a: source_a.read_bytes(), source_b: source_b.read_bytes()}
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    created = _prepare(handlers, root, batch_sessions=sessions)
    assert created["success"], created
    assert created["session_id"] == "a"
    batch_id = created["batch_id"]
    job_id = created["distill_job_id"]
    resumed = _prepare(handlers, root, batch_id=batch_id)
    assert resumed["success"] and resumed["distill_job_id"] == job_id
    frozen = backend.transcript_store.get_distill_job(job_id).to_dict()
    bound = _manifest(backend, batch_id, root)
    assert list(bound["bindings"]) == [bound["sessions"][0]["reference_id"]]
    assert len(backend.transcript_store.list_distill_jobs(project_name="project")) == 1

    paused = _prepare(handlers, root, batch_id=batch_id, pause=True)
    assert paused["success"] and paused["paused"] is True and paused["status"] == "paused"
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == frozen
    assert _manifest(backend, batch_id, root)["bindings"] == bound["bindings"]
    assert _manifest(backend, batch_id, root)["failures"] == {}
    assert _manifest(backend, batch_id, root)["sessions"] == bound["sessions"]
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("project")) == []
    assert len(backend.transcript_store.list_distill_jobs(project_name="project")) == 1
    manifest_path = ManualBatchStore(backend.data_dir).root / f"{batch_id}.json"
    held_bytes = manifest_path.read_bytes()
    inspected = handlers.tool_inspect_sessions(str(root), batch_id=batch_id)
    assert inspected["success"]
    assert manifest_path.read_bytes() == held_bytes
    again = _prepare(handlers, root, batch_id=batch_id)
    assert again["success"] and again["status"] == "paused" and again.get("distill_job_id") is None
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == frozen
    assert manifest_path.read_bytes() == held_bytes

    continued = _prepare(handlers, root, batch_id=batch_id, continue_batch=True)
    assert continued["success"], continued
    assert continued["distill_job_id"] == job_id
    assert _manifest(backend, batch_id, root)["state"] == "active"
    assert {path: path.read_bytes() for path in originals} == originals


def test_public_no_write_partial_and_failed_states_stay_retained(public_history):
    backend, root, write, handlers, _calls = public_history
    source_a = write("a")
    source_b = write("b")
    source_a_bytes = source_a.read_bytes()
    source_b_bytes = source_b.read_bytes()
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    created = _prepare(handlers, root, batch_sessions=sessions)
    assert created["session_id"] == "a"
    batch_id = created["batch_id"]
    final = handlers.tool_finalize_session_distill("project", created["distill_job_id"], _review())
    assert final["success"], final
    assert final["knowledge_changes"] == []
    assert final["not_written"] == [{"reason": "没有需要长期记住的内容", "count": 1}]
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("project")) == []
    source_b.unlink()
    blocked = _prepare(handlers, root, batch_id=batch_id)
    assert blocked["success"], blocked
    assert blocked["status"] == "partial"
    assert blocked["progress"]["states"]["blocked"] == 1
    failures = _manifest(backend, batch_id, root)["failures"]
    assert failures
    paused = _prepare(handlers, root, batch_id=batch_id, pause=True)
    assert paused["success"] and paused["status"] == "paused"
    assert _manifest(backend, batch_id, root)["failures"] == failures
    denied = _prepare(handlers, root, batch_id=batch_id, retry_failures=True)
    assert denied["success"] is False and denied["error"] == "batch_paused" and denied["status"] == "paused"
    assert denied["retained_failures"]
    assert _manifest(backend, batch_id, root)["failures"] == failures
    continued = _prepare(handlers, root, batch_id=batch_id, continue_batch=True)
    assert continued["success"] and continued["status"] == "partial"
    assert _manifest(backend, batch_id, root)["failures"] == failures
    assert _manifest(backend, batch_id, root)["state"] == "active"
    source_b.write_bytes(source_b_bytes)
    retried = _prepare(handlers, root, batch_id=batch_id, retry_failures=True)
    assert retried["success"] and retried["distill_job_id"]
    assert retried["distill_job_id"] != created["distill_job_id"]
    assert source_a.read_bytes() == source_a_bytes
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("project")) == []


def test_public_write_reopens_sqlite_search_and_note(public_history, monkeypatch):
    backend, root, write, handlers, _calls = public_history
    source = write("decision", "Keep an explicit local cache contract.")
    source_bytes = source.read_bytes()
    statement = "The cache retains only verified current entries."
    evidence = root / "policy.txt"
    evidence.write_text(statement, encoding="utf-8")
    created = _prepare(handlers, root, batch_sessions=handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert created["success"], created
    candidate = handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": f"distill-job:{created['distill_job_id']}", "confidence": 0.99,
        "distill_job_id": created["distill_job_id"], "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "A current verified cache rule is useful for later maintenance.",
        "canonical_title": "Verified current cache", "topic_path": ["cache"],
    })
    assert candidate["success"], candidate
    semantic = _review()
    judgment = runpy.run_path(str(Path(__file__).with_name("test_manual_session_flow.py")))["_scope_judgment"]
    semantic.update(promotion_decision="promote", final_outcome="Verified the cache rule against current policy.",
                    final_scope_judgment={candidate["entry_id"]: judgment("Verified current cache", statement)})
    final = handlers.tool_finalize_session_distill("project", created["distill_job_id"], semantic)
    assert final["success"], final
    assert final["knowledge_changes"] == [{
        "change": "added", "module": ["cache"], "title": "Verified current cache", "statement": statement,
    }]
    note = Path(final["note"]["path"])
    assert statement in note.read_text(encoding="utf-8")
    assert hashlib.sha256(note.read_bytes()).hexdigest() == final["note"]["sha256"]
    assert Path(final["note"]["latest_path"]).read_bytes() == note.read_bytes()
    assert source.read_bytes() == source_bytes
    data_dir = backend.data_dir
    asyncio.run(backend.close())
    reopened = LocalMemoryBackend(data_dir)
    asyncio.run(reopened.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
    try:
        entries = asyncio.run(reopened.structured_store.knowledge_store.list_entries("project"))
        assert [entry.statement for entry in entries] == [statement]
        found = handlers.tool_search_memory(query="verified current cache", project_name="project", scope="project")
        assert found["memories"] == [{"title": "Verified current cache", "statement": statement}]
        listed = handlers.tool_search_memory(query="", project_name="project", scope="project")
        assert listed["memories"] == [{"module": ["cache"], "title": "Verified current cache", "statement": statement}]
        committed = [entry.to_dict() for entry in entries]
        replay = handlers.tool_finalize_session_distill("project", created["distill_job_id"], {})
        assert replay["success"] and replay["idempotent_replay"], replay
        assert [entry.to_dict() for entry in asyncio.run(reopened.structured_store.knowledge_store.list_entries("project"))] == committed
        assert Path(replay["note"]["path"]).read_bytes() == note.read_bytes()
    finally:
        asyncio.run(reopened.close())


def test_integrity_stop_cannot_be_toggled_active(public_history):
    backend, root, write, handlers, _calls = public_history
    source = write("a")
    source_bytes = source.read_bytes()
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    created = _prepare(handlers, root, batch_sessions=sessions)
    store = ManualBatchStore(backend.data_dir)
    frozen = store.load(created["batch_id"], "project", str(root))["sessions"]
    store.record_failure(created["batch_id"], "project", str(root), frozen[0]["reference_id"], "unsafe", stop_batch=True)
    path = store.root / f"{created['batch_id']}.json"
    held = path.read_bytes()
    for kwargs in ({"pause": True}, {"continue_batch": True}, {"retry_failures": True}):
        result = _prepare(handlers, root, batch_id=created["batch_id"], **kwargs)
        assert result["success"] is False, result
        assert result["error"] == "batch_stopped"
        assert result["state"] == "stopped"
        assert result["retained_reason"] == "unsafe"
        assert path.read_bytes() == held
    new_batch = _prepare(handlers, root, batch_sessions=sessions)
    assert new_batch["success"] is False
    assert new_batch["status"] == "stopped"
    assert new_batch["error"] == "manual_batch_stopped"
    assert path.read_bytes() == held
    assert source.read_bytes() == source_bytes


def test_public_resume_rejects_replacement_and_other_project(public_history):
    backend, root, write, handlers, _calls = public_history
    write("a")
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    created = _prepare(handlers, root, batch_sessions=sessions)
    path = ManualBatchStore(backend.data_dir).root / f"{created['batch_id']}.json"
    held = path.read_bytes()
    replaced = _prepare(handlers, root, batch_id=created["batch_id"], batch_sessions=sessions)
    assert replaced["success"] is False
    assert "cannot be replaced" in replaced["error"]
    foreign = handlers.tool_prepare_session_distill(project_name="other", project_root=str(root), batch_id=created["batch_id"])
    assert foreign["success"] is False
    assert "another project" in foreign["error"]
    conflict = _prepare(handlers, root, batch_id=created["batch_id"], pause=True, continue_batch=True)
    assert conflict["success"] is False
    assert "separate" in conflict["error"]
    assert path.read_bytes() == held
    assert _manifest(backend, created["batch_id"], root)["state"] == "active"


def test_public_resume_stops_on_owner_or_source_change(public_history):
    backend, root, write, handlers, _calls = public_history
    source = write("a")
    source_bytes = source.read_bytes()
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    created = _prepare(handlers, root, batch_sessions=sessions)
    _rewrite_job(backend, created["distill_job_id"], project_name="other-owner")
    changed = _prepare(handlers, root, batch_id=created["batch_id"])
    assert changed["success"] is False
    assert changed["error"] == "job_scope_or_revision_changed"
    assert changed["status"] == "stopped"
    failures = _manifest(backend, created["batch_id"], root)["failures"]
    continued = _prepare(handlers, root, batch_id=created["batch_id"], continue_batch=True)
    assert continued["success"] is False
    assert continued["error"] == "batch_stopped"
    assert continued["retained_reason"] == "job_scope_or_revision_changed"
    assert _manifest(backend, created["batch_id"], root)["state"] == "stopped"
    assert _manifest(backend, created["batch_id"], root)["failures"] == failures
    paused = _prepare(handlers, root, batch_id=created["batch_id"], pause=True)
    assert paused["success"] is False and paused["error"] == "batch_stopped"
    assert _manifest(backend, created["batch_id"], root)["state"] == "stopped"

    write("b")
    selected = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    second = _prepare(handlers, root, batch_sessions=[row for row in selected if row["session_id"] == "b"])
    assert second["success"], second
    _rewrite_job(backend, second["distill_job_id"], source_revision="sha256:" + "f" * 64)
    revised = _prepare(handlers, root, batch_id=second["batch_id"])
    assert revised["success"] is False and revised["error"] == "job_scope_or_revision_changed"
    assert _manifest(backend, second["batch_id"], root)["state"] == "stopped"
    assert source.read_bytes() == source_bytes


def test_public_batch_does_not_steal_background_lease(public_history):
    backend, root, write, handlers, _calls = public_history
    source = write("owned-background")
    captured = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(source, "owned-background", "project"))
    job_id = captured.distill_job_id
    while True:
        claimed = backend.transcript_store.claim_distill_chunks(job_id, lease_owner="interactive")
        if not claimed:
            break
        for chunk, _checkpoint in claimed:
            backend.transcript_store.checkpoint_distill_chunk(
                job_id, chunk.id, lease_owner="interactive", result={},
            )
    assert backend.transcript_store.get_distill_job(job_id).status == "reviewing"
    assert backend.transcript_store.claim_distill_review(
        job_id, lease_owner="background", execution_source="autonomous_worker",
    ) is not None
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    denied = _prepare(handlers, root, batch_sessions=sessions)
    assert denied["success"] is False
    assert denied["error"] == "background review already owns this session"
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    assert not list((backend.data_dir / "manual-batches").glob("*.json"))

    chunk_source = write("chunk-owned")
    chunk_job = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(chunk_source, "chunk-owned", "project")).distill_job_id
    assert backend.transcript_store.claim_distill_chunks(chunk_job, lease_owner="interactive")
    chunk_before = backend.transcript_store.get_distill_job(chunk_job).to_dict()
    sessions = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    chunk_denied = _prepare(handlers, root, batch_sessions=[
        row for row in sessions if row["session_id"] == "chunk-owned"
    ])
    assert chunk_denied["success"] is False
    assert chunk_denied["error"] == "chunk processing already owns this session"
    assert backend.transcript_store.get_distill_job(chunk_job).to_dict() == chunk_before
    published = list((backend.data_dir / "manual-batches").glob("*.json"))
    assert published == []


def test_bound_history_releases_later_revision_and_stopped_unbound_stays(public_history):
    from harness_mem.commands.distill_lifecycle import pending_distill_jobs

    backend, root, write, handlers, _calls = public_history
    source = write("a", "Keep the first revision.")
    original_bytes = source.read_bytes()
    created = _prepare(handlers, root, batch_sessions=handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert created["success"], created
    assert handlers.tool_finalize_session_distill("project", created["distill_job_id"], _review())["success"]
    original = backend.transcript_store.get_distill_job(created["distill_job_id"])
    assert original.status == "completed"
    with source.open("a", encoding="utf-8") as stream:
        stream.write("\n" + json.dumps({
            "role": "user", "cwd": str(root),
            "message": {"content": [{"type": "text", "text": "A later revision arrived."}]},
        }))
    later_capture = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(source, "a", "project"))
    later = backend.transcript_store.get_distill_job(later_capture.distill_job_id)
    assert later.id != original.id
    assert later.source_revision != original.source_revision
    assert later.session_id == original.session_id
    assert not is_manual_distill_job(backend, later)
    backend.transcript_store.reserve_manual_distill_job(later.id)
    later = backend.transcript_store.get_distill_job(later.id)
    assert later.manual_only
    assert not is_manual_distill_job(backend, later)
    assert is_manual_distill_job(backend, backend.transcript_store.get_distill_job(original.id))
    offered = pending_distill_jobs(
        backend, project_name="project", background_only=True, record_offer=False,
    )
    assert later.id in [job.id for job in offered]
    assert original.id not in [job.id for job in offered]
    assert source.read_bytes() != original_bytes

    write("b")
    path_c = write("c")
    selected = handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    fresh = [row for row in selected if row["session_id"] in {"b", "c"}]
    packet = _prepare(handlers, root, batch_sessions=fresh)
    assert packet["success"] and packet["session_id"] == "b", packet
    captured_c = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(path_c, "c", "project"))
    store = ManualBatchStore(backend.data_dir)
    manifest = store.load(packet["batch_id"], "project", str(root))
    assert captured_c.distill_job_id not in manifest["bindings"].values()
    captured_job = backend.transcript_store.get_distill_job(captured_c.distill_job_id)
    assert not captured_job.manual_only
    assert is_manual_distill_job(backend, captured_job)
    store.record_failure(
        packet["batch_id"], "project", str(root), manifest["sessions"][0]["reference_id"],
        "fixture_stop", stop_batch=True,
    )
    assert is_manual_distill_job(backend, backend.transcript_store.get_distill_job(captured_c.distill_job_id))
    assert is_manual_distill_job(backend, backend.transcript_store.get_distill_job(packet["distill_job_id"]))


def test_public_pause_blocks_chunk_finalize_and_direct_prepare(public_history):
    backend, root, write, handlers, _calls = public_history
    source = write("a", "hello " * 10000)
    source_bytes = source.read_bytes()
    created = _prepare(
        handlers, root,
        batch_sessions=handlers.tool_inspect_sessions(str(root), clients=["cursor"])["sessions"],
        evidence_mode="raw", chunk_limit=1,
    )
    assert created["success"] and created.get("chunks"), created
    job_id = created["distill_job_id"]
    paused = _prepare(handlers, root, batch_id=created["batch_id"], pause=True)
    assert paused["status"] == "paused", paused
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    submitted = handlers.tool_submit_distill_chunk(
        job_id=job_id, chunk_id=created["chunks"][0]["chunk_id"],
        lease_owner=created["lease_owner"], result={"summary": "A read completed before pause."},
    )
    assert submitted["success"] is False
    assert submitted["error"] == "batch_paused"
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    with pytest.raises(ValueError, match="batch_paused"):
        backend.transcript_store.checkpoint_distill_chunk(
            job_id, created["chunks"][0]["chunk_id"], lease_owner=created["lease_owner"],
            result={"summary": "A leased write after pause."},
        )
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    direct = handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=job_id, run_ingest=False,
    )
    assert direct["success"] is False
    assert direct["reason_codes"] == ["batch_paused"]
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    finalized = handlers.tool_finalize_session_distill("project", job_id, _review())
    assert finalized["success"] is False
    assert finalized["error"] == "batch_paused"
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    assert source.read_bytes() == source_bytes
    continued = _prepare(handlers, root, batch_id=created["batch_id"], continue_batch=True, evidence_mode="raw", chunk_limit=1)
    assert continued["success"], continued
    assert continued["distill_job_id"] == job_id
    assert _manifest(backend, created["batch_id"], root)["state"] == "active"
