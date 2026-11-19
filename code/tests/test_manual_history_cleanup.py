"""Explicit finished-history cleanup through the real MCP consumer; temp data only."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def history(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: CursorAdapter(None, projects_dir=projects))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "cleanup-test-runtime")
    handlers = tool_handlers

    def write(name="closed", text="hello"):
        path = projects / "bucket" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(record) for record in [
            {"role": "user", "cwd": str(root), "message": {"content": [{"type": "text", "text": text}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello, ready to help."}]}},
        ]), encoding="utf-8")
        os.utime(path, (time.time() - 120, time.time() - 120))
        return path

    def prepare(**kwargs):
        return handlers.tool_prepare_session_distill(project_name="project", project_root=str(root), **kwargs)

    def complete(name="closed", *, finish=True, text="hello"):
        path = write(name, text)
        inventory = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])
        selected = [row for row in inventory["sessions"] if row["session_id"] == name]
        packet = prepare(batch_sessions=selected)
        assert packet["success"], packet
        if finish:
            final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], {
                "session_summary": "The session exchanged a greeting without making durable decisions.",
                "final_user_request": "greeting", "final_outcome": "greeting answered",
                "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
                "evidence_status": "answered", "promotion_decision": "no_promotion",
            })
            assert final["success"], final
        return path, packet

    yield backend, root, handlers, prepare, complete
    asyncio.run(backend.close())


def test_preview_apply_inspect_resume_and_replay(history):
    backend, root, handlers, prepare, complete = history
    path, packet = complete()
    before = path.read_bytes()
    job_before = backend.transcript_store.get_distill_job(packet["distill_job_id"]).to_dict()
    preview = prepare(batch_id=packet["batch_id"], cleanup_processed=True)
    assert preview["success"], preview
    assert preview["counts"] == {"ready": 1}
    planned, = preview["sessions"]
    assert planned["position"] == 1 and planned["source_revision"] == packet["source_revision"]
    assert planned["review"]["readback_verified"] and planned["review"]["current_knowledge"] == 0
    assert len(planned["native"]["file_targets"]) == 1
    assert path.read_bytes() == before
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).to_dict() == job_before
    assert backend.transcript_store.list_deletion_audit(project_name="project") == []
    applied = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert applied["success"], applied
    assert applied["counts"] == {"deleted": 1}
    removed, = applied["sessions"]
    assert removed["native"]["file_targets"] == planned["native"]["file_targets"]
    assert removed["native"]["result"]["file_results"] == [
        {**planned["native"]["file_targets"][0], "status": "deleted"},
    ]
    assert not path.exists()
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.retain_source and job.manual_only
    assert job.session_id == "" and job.project_root == ""
    assert job.source_cleanup_status == "deleted"
    assert backend.transcript_store.get_revision(job.source_id, job.source_revision).raw_size_bytes == 0
    inspected = handlers.tool_inspect_sessions(project_root=str(root), project_name="project", batch_id=packet["batch_id"])
    assert inspected["success"] and inspected["progress"]["completed"] == 1, inspected
    resumed = prepare(batch_id=packet["batch_id"])
    assert resumed["success"] and resumed["status"] == "completed", resumed
    replay = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert replay["success"] and replay["counts"] == {"already_deleted": 1}, replay
    assert replay["sessions"][0]["native"] == removed["native"]
    assert len(backend.transcript_store.list_deletion_audit(project_name="project")) == 1


@pytest.mark.parametrize("damage", ["not_completed", "missing_readback", "unfinished", "changed_source", "active_source"])
def test_incomplete_ambiguous_or_active_sources_are_retained(history, damage):
    backend, _root, _handlers, prepare, complete = history
    path, packet = complete(finish=damage != "not_completed")
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    if damage == "missing_readback":
        job.promotion_summary.pop("readback", None)
        backend.transcript_store._distill._upsert_job_locked(job)
    elif damage == "unfinished":
        job.semantic_review["unfinished_work"] = ["Check the source decision."]
        backend.transcript_store._distill._upsert_job_locked(job)
    elif damage == "changed_source":
        path.write_bytes(path.read_bytes() + b"\nnew appended bytes")
    elif damage == "active_source":
        os.utime(path, None)
    before = path.read_bytes()
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"], result
    assert result["sessions"][0]["status"] == "retained", result
    assert path.read_bytes() == before
    assert backend.transcript_store.get_revision(job.source_id, job.source_revision).raw_size_bytes > 0


def test_success_receipt_cannot_certify_another_frozen_reference(history):
    backend, root, handlers, prepare, complete = history
    _path, packet = complete()
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"], result
    receipt, = backend.transcript_store.list_deletion_audit(project_name="project")
    receipt["scope"]["manual_reference_id_sha256"] = "0" * 64
    backend.transcript_store.save_deletion_receipt(receipt)
    inspected = handlers.tool_inspect_sessions(project_root=str(root), project_name="project", batch_id=packet["batch_id"])
    assert not inspected["success"], inspected
    replay = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not replay["success"], replay
    assert replay["sessions"][0]["reason_codes"] == ["job_scope_or_revision_changed"]


def test_apply_requires_cleanup_and_a_frozen_batch(history):
    _backend, _root, _handlers, prepare, _complete = history
    assert not prepare(apply_cleanup=True)["success"]
    assert not prepare(cleanup_processed=True)["success"]


def test_open_handoff_blocks_cleanup_even_with_completed_readback(history):
    from harness_mem.core.schemas.task_handoff import TaskHandoff

    backend, _root, _handlers, prepare, complete = history
    path, packet = complete()
    handoff = TaskHandoff(project_name="project", task_id=packet["distill_job_id"],
                          summary="An independent decision still needs review.", status="pending")
    asyncio.run(backend.structured_store.save_task_handoff(handoff))
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"], result
    assert result["sessions"][0]["reason_codes"] == ["handoff_readback_incomplete"]
    assert path.exists()
    assert backend.transcript_store.list_deletion_audit(project_name="project") == []


def test_shared_container_is_never_deleted(history):
    backend, _root, _handlers, prepare, complete = history
    path, packet = complete()
    source = backend.transcript_store.get_source(packet["source_id"])
    source.source_kind = "sqlite-session-export"
    backend.transcript_store.save_source(source)
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"] and result["counts"] == {"unsupported": 1}, result
    assert path.exists()


def test_reintroduced_native_source_is_not_certified_by_old_receipt(history):
    _backend, _root, _handlers, prepare, complete = history
    path, packet = complete()
    original = path.read_bytes()
    assert prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)["success"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"], result
    assert result["sessions"][0]["reason_codes"] == ["native_source_reappeared"]
    assert path.read_bytes() == original


@pytest.mark.parametrize("stage", ["before_prune", "after_prune"])
def test_failed_structured_cleanup_resumes_same_receipt_without_reprocessing(history, monkeypatch, stage):
    import harness_mem.processed_source_cleanup as cleanup

    backend, _root, _handlers, prepare, complete = history
    path, packet = complete()

    def fail(*_args, **_kwargs):
        raise OSError("isolated failure")

    with monkeypatch.context() as patch:
        if stage == "before_prune":
            patch.setattr(cleanup, "_sanitize_truth", fail)
        else:
            patch.setattr(backend.verbatim_store, "flush_sensitive_deletes", fail)
        failed = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not failed["success"], failed
    assert failed["counts"] == {"partial_failure": 1}, failed
    assert not path.exists()
    resumed = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert resumed["success"] and resumed["counts"] == {"deleted": 1}, resumed
    assert len(backend.transcript_store.list_deletion_audit(project_name="project")) == 1
    assert len(backend.transcript_store.list_distill_jobs()) == 1


def test_cleanup_preserves_committed_knowledge_and_ordinary_search(history):
    backend, root, handlers, prepare, complete = history
    path, packet = complete(finish=False)
    statement = "Keep a separate saved result for each completed task."
    policy = root / "results.txt"
    policy.write_text(statement, encoding="utf-8")
    suggested = handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": policy.name, "distill_job_id": packet["distill_job_id"],
        "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": policy.name,
                               "content_sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "A continuing verified project policy.",
        "canonical_title": "Saved results", "topic_path": ["Results"],
    })
    assert suggested["success"], suggested
    final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], {
        "session_summary": "The completed task confirmed the continuing result retention policy.",
        "final_user_request": "Review the saved result policy.", "final_outcome": "The policy was saved.",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "promote",
        "final_scope_judgment": {suggested["entry_id"]: {"points": [{
            "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
            "source_use": "reusable_knowledge", "reason": "The complete fixture policy supports continuing result retention.",
            "scope_segments": [{"text": "Saved results\n" + statement, "source_use": "reusable_knowledge",
                                "future_scope": "durable", "standalone": True, "content_role": "claim",
                                "source_support": "supported"}],
        }]}},
    })
    assert final["success"], final
    saved = [entry.to_dict() for entry in asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))]
    assert len(saved) == 1 and saved[0]["statement"] == statement
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"], result
    assert not path.exists() and policy.exists()
    assert [entry.to_dict() for entry in asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))] == saved
    found = handlers.tool_search_memory(query="Saved results", scope="project", project_name="project", detail="full")
    assert statement in json.dumps(found, ensure_ascii=False), found


def test_cleaned_old_batch_does_not_block_new_unrelated_history_selection(history):
    _backend, _root, _handlers, prepare, complete = history
    _old, first = complete("first")
    assert prepare(batch_id=first["batch_id"], cleanup_processed=True, apply_cleanup=True)["success"]
    path, second = complete("second")
    assert second["batch_id"] != first["batch_id"]
    assert path.exists()


@pytest.mark.parametrize("state", ["present", "missing", "search_unreadable"])
def test_confirmed_knowledge_requires_current_full_readback(history, monkeypatch, state):
    from test_manual_session_flow import _memory_review, _seed_readable_memory, _suggest_readable_memory

    backend, root, handlers, prepare, complete = history
    statement = "Keep a separate saved result for each completed task."
    entry = _seed_readable_memory(backend, root, title="Saved results", statement=statement)
    path, packet = complete(finish=False)
    target = {"title": entry.title, "statement": entry.statement, "project_name": "project"}
    suggestion = _suggest_readable_memory(backend, root, packet, title=entry.title, statement=entry.statement,
                                           disposition="confirm", targets=[target])
    assert suggestion["success"], suggestion
    final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _memory_review(packet))
    assert final["success"], final
    store = backend.structured_store.knowledge_store
    original = asyncio.run(store.get_entry(entry.id, project_name="project")).to_dict()
    if state == "missing":
        deleted = handlers.tool_govern_memory(action="decide", arguments={
            "kind": "knowledge", "decision": "delete", "project_name": "project", "target_knowledge": [target],
        })
        assert deleted["success"], deleted
    elif state == "search_unreadable":
        import harness_mem.read_knowledge as reading

        async def no_results(*_args, **_kwargs):
            return []

        monkeypatch.setattr(reading, "search_current_knowledge", no_results)
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"] is (state == "present"), result
    assert path.exists() is (state != "present")
    if state != "missing":
        assert asyncio.run(store.get_entry(entry.id, project_name="project")).to_dict() == original


def test_device_scope_metadata_reference_cleanup_inspect_resume(history):
    _backend, root, handlers, _prepare, _complete = history
    # A rootless native source is selected through its metadata-only reference.
    path = root.parent / "cursor" / "bucket" / "agent-transcripts" / "device" / "device.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(value) for value in [
        {"role": "user", "message": {"content": [{"type": "text", "text": "hello"}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello."}]}},
    ]), encoding="utf-8")
    os.utime(path, (time.time() - 120, time.time() - 120))
    inventory = handlers.tool_inspect_sessions(clients=["cursor"])
    selected = [row for row in inventory["sessions"] if row["session_id"] == "device"]
    packet = handlers.tool_prepare_session_distill(batch_sessions=selected, scope="all")
    assert packet["success"], packet
    final = handlers.tool_finalize_session_distill(packet["project_name"], packet["distill_job_id"], {
        "session_summary": "The finished session exchanged greetings and has no durable decision.",
        "final_user_request": "greeting", "final_outcome": "greeting answered",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "no_promotion",
    })
    assert final["success"], final
    applied = handlers.tool_prepare_session_distill(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert applied["success"], applied
    assert not path.exists()
    inspected = handlers.tool_inspect_sessions(batch_id=packet["batch_id"])
    assert inspected["success"] and inspected["progress"]["completed"] == 1, inspected
    resumed = handlers.tool_prepare_session_distill(batch_id=packet["batch_id"])
    assert resumed["success"] and resumed["status"] == "completed", resumed


def _finished_conversation_with_project_work(history):
    backend, root, handlers, prepare, complete = history
    tasks = [
        "Measure one fixed model sample; no model identity or result is established.",
        "Finish the security review requested by the user; it remains unfinished.",
        "Preserve rollback proof for the reported migration v9.1.0 incident; the assistant's rollback claim is not independently verified.",
        "Run the production rollout only after the final result contract is green; that prerequisite is not proved satisfied.",
    ]
    path, packet = complete(finish=False, text="For this project: " + " ".join(tasks))
    created = handlers.tool_govern_memory(action="handoff", arguments={
        "project_name": "project", "distill_job_id": packet["distill_job_id"], "task_id": "remaining-project-work",
        "summary": "The conversation is fully reviewed; original project execution remains pending.",
        "status": "in_progress", "next_steps": tasks,
        "blockers": ["Production rollout requires a green final result contract."],
    })
    assert created["success"], created
    final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], {
        "session_summary": "The conversation established four remaining project tasks with their original conditions and speaker boundaries.",
        "final_user_request": "Preserve the original project tasks and their conditions.",
        "final_outcome": "Source review is complete; the four original project tasks remain saved and unfinished.",
        "last_turn_status": "unfinished", "contradictions": [], "unfinished_work": tasks,
        "evidence_status": "partial", "promotion_decision": "partial",
    })
    assert final["success"], final
    return backend, root, handlers, prepare, path, packet, tasks


def test_finished_conversation_cleans_raw_history_and_preserves_all_original_project_work(history):
    from harness_mem.session_notes import session_note_path
    from harness_mem.mcp.distill_handlers import _session_notes_dir

    backend, root, handlers, prepare, path, packet, tasks = _finished_conversation_with_project_work(history)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    note = session_note_path(_session_notes_dir(backend), job)
    note_before = note.read_bytes()
    handoff_before = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
    assert len(handoff_before) == 1
    preview = prepare(batch_id=packet["batch_id"], cleanup_processed=True)
    assert preview["success"], preview
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"], result
    assert not path.exists()
    assert note.read_bytes() == note_before
    assert backend.structured_store.list_record_payloads("task_handoffs", strict=True) == handoff_before
    assert backend.transcript_store.get_revision(job.source_id, job.source_revision).raw_size_bytes == 0
    after = handlers.tool_inspect_sessions(project_root=str(root), project_name="project", batch_id=packet["batch_id"])
    assert after["success"] and after["progress"]["completed"] == 1, after
    assert after["unfinished_work"] == tasks
    resumed = prepare(batch_id=packet["batch_id"])
    assert resumed["success"] and resumed["unfinished_work"] == tasks, resumed
    replay = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert replay["success"] and replay["counts"] == {"already_deleted": 1}, replay


@pytest.mark.parametrize("damage", ["missing_handoff", "missing_note", "uncovered_work", "deferred_candidate", "native_proof_reference", "sidecar_proof_reference"])
def test_unabsorbed_or_unpreserved_work_still_keeps_original_source(history, damage):
    from harness_mem.session_notes import session_note_path
    from harness_mem.mcp.distill_handlers import _session_notes_dir

    backend, _root, _handlers, prepare, path, packet, _tasks = _finished_conversation_with_project_work(history)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    handoff, = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
    if damage == "missing_handoff":
        backend.structured_store.hard_delete_record("task_handoffs", handoff["id"])
    elif damage == "missing_note":
        session_note_path(_session_notes_dir(backend), job).unlink()
    elif damage == "uncovered_work":
        job.semantic_review["unfinished_work"].append("Preserve a separate original evidence packet.")
        backend.transcript_store._distill._upsert_job_locked(job)
    elif damage == "deferred_candidate":
        job.promotion_summary["points"].append({"candidate_id": "unfinished-meaning", "disposition": "defer"})
        job.output_candidate_ids.append("unfinished-meaning")
        backend.transcript_store._distill._upsert_job_locked(job)
    else:
        from harness_mem.core.schemas.task_handoff import TaskHandoff

        proof = path
        if damage == "sidecar_proof_reference":
            proof = path.parent / "rollback-proof.log"
            proof.write_text("Original rollback evidence bytes must survive.", encoding="utf-8")
        handoff["context"]["proof_refs"] = [{"kind": "repository", "locator": proof.as_uri()}]
        asyncio.run(backend.structured_store.save_task_handoff(TaskHandoff.from_dict(handoff)))
    before = path.read_bytes()
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"], result
    assert path.read_bytes() == before
    assert backend.transcript_store.get_revision(job.source_id, job.source_revision).raw_size_bytes > 0


@pytest.mark.parametrize("changed_output", ["note", "handoff"])
def test_output_changes_after_native_deletion_are_reported_as_partial(history, monkeypatch, changed_output):
    import harness_mem.native_source_cleanup as native
    from harness_mem.core.schemas.task_handoff import TaskHandoff
    from harness_mem.mcp.distill_handlers import _session_notes_dir
    from harness_mem.session_notes import session_note_path

    backend, _root, _handlers, prepare, path, packet, _tasks = _finished_conversation_with_project_work(history)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    note = session_note_path(_session_notes_dir(backend), job)
    original_apply = native.apply_native_source_cleanup

    def mutate_after_delete(plan):
        result = original_apply(plan)
        assert result["status"] == "deleted", result
        if changed_output == "note":
            note.write_bytes(note.read_bytes() + b"\nConcurrent output edit.\n")
        else:
            handoff, = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
            handoff["next_steps"].pop()
            asyncio.run(backend.structured_store.save_task_handoff(TaskHandoff.from_dict(handoff)))
        return result

    monkeypatch.setattr(native, "apply_native_source_cleanup", mutate_after_delete)
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"] and result["counts"] == {"partial_failure": 1}, result
    assert not path.exists()
    receipt, = backend.transcript_store.list_deletion_audit(project_name="project")
    assert receipt["status"] == "partial_failure" and receipt["verification"]["passed"] is False


def test_cleanup_without_handoffs_preserves_existing_prune_call_shape(history, monkeypatch):
    backend, _root, _handlers, prepare, complete = history
    _path, packet = complete()
    original = backend.transcript_store.prune_completed_distill_evidence
    calls = []

    def existing_signature(job_id, *, receipt_id):
        calls.append(job_id)
        return original(job_id, receipt_id=receipt_id)

    monkeypatch.setattr(backend.transcript_store, "prune_completed_distill_evidence", existing_signature)
    result = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"], result
    assert calls == [packet["distill_job_id"]]


def test_finalize_itself_persists_original_project_work_then_cleanup_survives_reopen(history, monkeypatch):
    backend, root, handlers, prepare, complete = history
    tasks = [
        "Measure one fixed model sample next; the source names no model or measurement result.",
        "Preserve rollback proof for the reported migration; the assistant claim is not independently verified.",
        "Run production rollout only after the final result contract is green; that prerequisite is not established.",
    ]
    path, packet = complete(finish=False, text="Keep these original project tasks: " + " ".join(tasks))
    assert backend.structured_store.list_record_payloads("task_handoffs", strict=True) == []
    final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], {
        "session_summary": "The conversation was reviewed completely; three conditional project tasks remain for later execution.",
        "final_user_request": "Retain the original project work and its conditions.",
        "final_outcome": "Original project work remains unfinished, while this conversation review is complete.",
        "last_turn_status": "unfinished", "contradictions": [], "unfinished_work": tasks,
        "evidence_status": "partial", "promotion_decision": "partial",
    })
    assert final["success"], final
    handoffs = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
    assert len(handoffs) == 1 and handoffs[0]["next_steps"] == tasks
    preview = prepare(batch_id=packet["batch_id"], cleanup_processed=True)
    assert preview["success"], preview
    applied = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert applied["success"] and not path.exists(), applied
    data_dir = backend.data_dir
    asyncio.run(backend.close())
    reopened = LocalMemoryBackend(data_dir)
    asyncio.run(reopened.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
        inspected = handlers.tool_inspect_sessions(project_root=str(root), project_name="project", batch_id=packet["batch_id"])
        assert inspected["success"] and inspected["progress"]["completed"] == 1, inspected
        assert inspected["unfinished_work"] == tasks
        assert reopened.structured_store.list_record_payloads("task_handoffs", strict=True) == handoffs
        resumed = prepare(batch_id=packet["batch_id"])
        assert resumed["success"] and resumed["unfinished_work"] == tasks, resumed
    finally:
        asyncio.run(reopened.close())


@pytest.mark.parametrize("failure", ["save", "readback"])
def test_failed_final_handoff_keeps_source_and_already_saved_verified_knowledge(history, monkeypatch, failure):
    from test_manual_session_flow import _memory_review, _suggest_readable_memory
    from harness_mem.mcp import governance_handlers

    backend, root, handlers, _prepare, complete = history
    task = "Run production rollout only after the final result contract is green."
    path, packet = complete(finish=False, text="Adopt the result retention rule. " + task)
    statement = "Keep a separate saved result for each completed task."
    suggestion = _suggest_readable_memory(backend, root, packet, title="Saved results", statement=statement)
    assert suggestion["success"], suggestion
    semantic = {**_memory_review(packet), "promotion_decision": "partial", "unfinished_work": [task]}
    if failure == "save":
        def failed_save(**_kwargs):
            raise OSError("isolated handoff persistence failure")

        monkeypatch.setattr(governance_handlers, "tool_create_task_handoff", failed_save)
    else:
        async def failed_readback(_identity):
            return None

        monkeypatch.setattr(backend.structured_store, "get_task_handoff", failed_readback)
    result = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], semantic)
    assert not result["success"] and result["reason_codes"] == ["unfinished_handoff_not_saved"], result
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).status != "completed"
    assert path.exists()
    saved = asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))
    assert len(saved) == 1 and saved[0].statement == statement
    assert "Verified knowledge may already be saved" in result["error"]
    assert "nothing changed" not in result["error"].lower()
