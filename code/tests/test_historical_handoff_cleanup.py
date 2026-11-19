"""Source-wide history cleanup preserves old completed project handoffs; temp data only."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import time

import pytest

from test_manual_history_cleanup import history as history
from test_manual_session_flow import _memory_review, _suggest_readable_memory

from harness_mem.commands.session_inventory import completed_job_ids, current_entries
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.mcp.distill_handlers import _session_notes_dir
from harness_mem.session_notes import session_note_path


def _review(tasks):
    return {
        "session_summary": "The complete conversation was reviewed; earlier saved project tasks remain pending in their original handoffs.",
        "final_user_request": "Keep the original project follow-up and its conditions.",
        "final_outcome": "Source review is complete; original conditional project work remains saved and unfinished.",
        "last_turn_status": "unfinished" if tasks else "answered", "contradictions": [],
        "unfinished_work": tasks, "evidence_status": "partial" if tasks else "answered",
        "promotion_decision": "partial" if tasks else "no_promotion",
    }


def _source_revisions(history, *, revision_count=4):
    backend, root, handlers, prepare, complete = history
    tasks = [
        ["Find the separately saved full dependency map; the assistant reported that its location is still unknown."],
        ["Recheck current upstream service availability; the source reports no completed live service check."],
        ["Choose the multimodal review method after deployment fit and work-review effectiveness are verified.",
         "Complete audio production and continuity fixes; the assistant reports these gaps remain unresolved."],
        ["Verify the project follow-up only after the original final result contract is green."],
    ]
    tasks.extend([f"Complete historical project follow-up {index} only after its explicit source check succeeds."]
                 for index in range(5, revision_count + 1))
    path, packet = complete("historical", finish=False, text="Adopt the result retention rule. " + " ".join(tasks[0]))
    statement = "Keep a separate saved result for each completed task."
    suggested = _suggest_readable_memory(backend, root, packet, title="Saved results", statement=statement)
    assert suggested["success"], suggested
    first_review = {**_memory_review(packet), **_review(tasks[0]), "promotion_decision": "partial"}
    first_review["final_scope_judgment"] = packet["_fixture_final_judgments"]
    final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], first_review)
    assert final["success"], final
    packets = [packet]
    for steps in tasks[1:]:
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n" + json.dumps({"role": "user", "cwd": str(root), "message": {"content": [{"type": "text", "text": " ".join(steps)}]}}))
            stream.write("\n" + json.dumps({"role": "assistant", "message": {"content": [{"type": "text", "text": "The original project work remains unfinished."}]}}))
        os.utime(path, (time.time() - 120, time.time() - 120))
        inventory = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])
        selected = [row for row in inventory["sessions"] if row["session_id"] == "historical" and row.get("origin") == "native"]
        assert len(selected) == 1, inventory
        packet = prepare(batch_sessions=selected)
        assert packet["success"], packet
        final = handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _review(steps))
        assert final["success"], final
        packets.append(packet)
    jobs = [backend.transcript_store.get_distill_job(value["distill_job_id"]) for value in packets]
    assert len({job.source_id for job in jobs}) == 1
    assert len({job.source_revision for job in jobs}) == revision_count
    return backend, root, handlers, prepare, path, packets, jobs, tasks, statement


@pytest.mark.parametrize("old_truth_removed", [False, True])
def test_current_complete_source_cleans_all_raw_revisions_but_keeps_historical_task_outputs(history, old_truth_removed):
    backend, root, handlers, prepare, path, packets, jobs, tasks, statement = _source_revisions(history)
    store = backend.structured_store.knowledge_store
    current = asyncio.run(store.list_entries("project"))
    assert len(current) == 1
    removed_identity = current[0].id
    if old_truth_removed:
        result = handlers.tool_govern_memory(action="decide", arguments={
            "kind": "knowledge", "decision": "delete", "project_name": "project",
            "target_knowledge": [{"title": current[0].title, "statement": current[0].statement, "project_name": "project"}],
        })
        assert result["success"], result
    notes = {job.id: session_note_path(_session_notes_dir(backend), job) for job in jobs}
    note_bytes = {identity: note.read_bytes() for identity, note in notes.items()}
    handoffs = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
    assert len(handoffs) == 4 and sum(len(row["next_steps"]) for row in handoffs) == 5
    preview = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True)
    assert preview["success"], preview
    applied = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert applied["success"], applied
    assert not path.exists()
    assert all(revision.raw_size_bytes == 0 for revision in backend.transcript_store.list_revisions(jobs[-1].source_id))
    assert {identity: note.read_bytes() for identity, note in notes.items()} == note_bytes
    assert backend.structured_store.list_record_payloads("task_handoffs", strict=True) == handoffs
    for job, original_work in zip(jobs, tasks):
        saved = backend.transcript_store.get_distill_job(job.id)
        assert saved.status == "completed" and saved.semantic_review["unfinished_work"] == original_work
    receipt, = backend.transcript_store.list_deletion_audit(project_name="project")
    assert set(receipt["preserved_outputs"]["historical_notes"]) == {job.id for job in jobs[:-1]}
    assert set(receipt["preserved_outputs"]["handoffs"]) == {row["id"] for row in handoffs}
    assert all(row["status"] == "in_progress" for row in handoffs)
    inspected = handlers.tool_inspect_sessions(project_root=str(root), project_name="project", batch_id=packets[-1]["batch_id"])
    assert inspected["success"] and inspected["unfinished_work"] == tasks[-1], inspected
    replay = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert replay["success"] and replay["counts"] == {"already_deleted": 1}, replay
    if old_truth_removed:
        assert asyncio.run(store.list_entries("project")) == []
        assert receipt["preserved_outputs"]["historical_unavailable_truth_ids"] == {jobs[0].id: [removed_identity]}
        proven, _ = completed_job_ids(backend.transcript_store.list_distill_jobs(), current_entries(backend.data_dir, None))
        assert jobs[0].id not in proven and jobs[-1].id in proven
    else:
        found = handlers.tool_search_memory(query="Saved results", project_name="project", scope="project", detail="full")
        assert statement in json.dumps(found), found


@pytest.mark.parametrize("damage", ["missing_handoff", "unrecorded_old_handoff", "old_source_binding", "missing_old_readback", "old_semantic_defer", "active_old_lease", "native_proof_dependency", "old_work_not_saved", "current_readback_missing", "old_memory_unreadable"])
def test_old_project_work_is_retained_but_missing_proof_and_unresolved_meaning_still_block_cleanup(history, monkeypatch, damage):
    backend, _root, handlers, prepare, path, packets, jobs, _tasks, statement = _source_revisions(history)
    first = jobs[0]
    handoff = next(row for row in backend.structured_store.list_record_payloads("task_handoffs", strict=True)
                   if row["context"]["distill_job_id"] == first.id)
    if damage == "missing_handoff":
        backend.structured_store.hard_delete_record("task_handoffs", handoff["id"])
    elif damage in {"old_source_binding", "native_proof_dependency"}:
        if damage == "old_source_binding":
            handoff["context"]["source_id"] = "a-different-logical-source"
        else:
            handoff["context"]["proof_refs"] = [{"kind": "repository", "locator": path.as_uri()}]
        asyncio.run(backend.structured_store.save_task_handoff(TaskHandoff.from_dict(handoff)))
    elif damage == "old_memory_unreadable":
        import harness_mem.read_knowledge as reading
        original = reading.search_current_knowledge

        async def hidden_entry(*args, **kwargs):
            return [] if kwargs.get("query") == statement else await original(*args, **kwargs)

        monkeypatch.setattr(reading, "search_current_knowledge", hidden_entry)
    else:
        target = jobs[-1] if damage == "current_readback_missing" else first
        if damage == "unrecorded_old_handoff":
            target.semantic_review["unfinished_work"] = []
            target.promotion_summary["unfinished_work"] = []
            target.promotion_summary["readback"]["handoff_ids"] = []
        elif damage in {"missing_old_readback", "current_readback_missing"}:
            target.promotion_summary.pop("readback", None)
        elif damage == "old_semantic_defer":
            target.promotion_summary["points"].append({"candidate_id": "unfinished-semantic-point", "disposition": "defer"})
            target.output_candidate_ids.append("unfinished-semantic-point")
        elif damage == "active_old_lease":
            target.review_lease_owner = "another-real-reviewer"
            target.review_lease_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        else:
            target.semantic_review["unfinished_work"].append("An additional original condition is not saved in the handoff.")
        backend.transcript_store._distill._upsert_job_locked(target)
    original_bytes = path.read_bytes()
    result = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"], result
    assert path.read_bytes() == original_bytes
    assert all(revision.raw_size_bytes > 0 for revision in backend.transcript_store.list_revisions(first.source_id))


@pytest.mark.parametrize("changed_output", ["historical_note", "historical_handoff"])
def test_changes_to_old_retained_outputs_after_native_delete_remain_honest_partial(history, monkeypatch, changed_output):
    import harness_mem.native_source_cleanup as native

    backend, _root, _handlers, prepare, path, packets, jobs, _tasks, _statement = _source_revisions(history)
    note = session_note_path(_session_notes_dir(backend), jobs[0])
    before_digest = hashlib.sha256(note.read_bytes()).hexdigest()
    original_apply = native.apply_native_source_cleanup

    def changed_after_native(plan):
        result = original_apply(plan)
        assert result["status"] == "deleted", result
        if changed_output == "historical_note":
            note.write_bytes(note.read_bytes() + b"\nConcurrent historical Note change.\n")
        else:
            handoff = next(row for row in backend.structured_store.list_record_payloads("task_handoffs", strict=True)
                           if row["context"]["distill_job_id"] == jobs[0].id)
            handoff["summary"] += " Concurrent change."
            asyncio.run(backend.structured_store.save_task_handoff(TaskHandoff.from_dict(handoff)))
        return result

    monkeypatch.setattr(native, "apply_native_source_cleanup", changed_after_native)
    result = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not result["success"] and result["counts"] == {"partial_failure": 1}, result
    assert not path.exists()
    receipt, = backend.transcript_store.list_deletion_audit(project_name="project")
    assert receipt["status"] == "partial_failure" and receipt["verification"]["passed"] is False
    assert receipt["preserved_outputs"]["historical_notes"][jobs[0].id] == before_digest


def test_sourcewide_cleanup_leaves_no_raw_observation_for_supported_append_intake(history):
    backend, _root, _handlers, prepare, path, packets, jobs, _tasks, _statement = _source_revisions(history)
    source_id = jobs[-1].source_id
    original = [row for row in backend.verbatim_store.list_record_payloads_for_lifecycle()
                if row.get("metadata", {}).get("transcript_source_id") == source_id]
    assert original
    result = prepare(batch_id=packets[-1]["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"] and not path.exists(), result
    remaining = [row for row in backend.verbatim_store.list_record_payloads_for_lifecycle()
                 if row.get("metadata", {}).get("transcript_source_id") == source_id]
    assert remaining == [], "All source revisions are pruned; their raw observation copies must not remain."


def test_moved_native_alias_keeps_exact_frozen_batch_binding_after_eight_revision_cleanup(history):
    from harness_mem.adapters.snapshot import persist_inspected_session
    from harness_mem.commands.session_inventory import collect_session_inventory, session_reference
    from harness_mem.storage.manual_batch_store import ManualBatchStore

    backend, root, handlers, prepare, path, _packets, jobs, tasks, _statement = _source_revisions(history, revision_count=8)
    canonical_job = jobs[-1]
    archived_directory = root.parent / "cursor" / "archive-bucket" / "agent-transcripts" / "historical"
    archived_directory.parent.mkdir(parents=True)
    path.parent.rename(archived_directory)
    archived_path = archived_directory / path.name
    inventory = handlers.tool_inspect_sessions(project_root=str(root), clients=["cursor"])
    selected = [row for row in inventory["sessions"] if row["session_id"] == "historical" and row.get("origin") == "native"]
    assert len(selected) == 1, inventory
    assert selected[0]["source_id"] != canonical_job.source_id
    # Refresh the moved locator through the existing full-read/capture owner,
    # retaining its canonical source/job identity rather than editing metadata.
    complete_inventory = collect_session_inventory(backend.data_dir, project_root=root, project_name="project",
                                                   clients=["cursor"], selected_sessions=selected)
    native, = complete_inventory.native.values()
    rebound_source = asyncio.run(persist_inspected_session(
        backend, native, project_name="project", project_root=str(root), capture_config=native.capture_config,
        expected_source_id=canonical_job.source_id, expected_source_revision=canonical_job.source_revision,
    ))
    assert rebound_source.source.id == canonical_job.source_id
    rebound = prepare(batch_sessions=selected)
    assert rebound["success"] and rebound["status"] == "completed", rebound
    manifest = ManualBatchStore(backend.data_dir).load(rebound["batch_id"], "project", str(root))
    frozen, = manifest["sessions"]
    assert manifest["bindings"][frozen["reference_id"]] == canonical_job.id
    assert frozen["source_id"] != canonical_job.source_id
    result = prepare(batch_id=rebound["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert result["success"] and not archived_path.exists(), json.dumps(result, ensure_ascii=False)
    assert all(revision.raw_size_bytes == 0 for revision in backend.transcript_store.list_revisions(canonical_job.source_id))
    inspected = handlers.tool_inspect_sessions(project_name="project", project_root=str(root), batch_id=rebound["batch_id"])
    assert inspected["success"] and inspected["progress"]["completed"] == 1, inspected
    assert inspected["unfinished_work"] == tasks[-1]
    resumed = prepare(batch_id=rebound["batch_id"])
    assert resumed["success"] and resumed["status"] == "completed", resumed
    replay = prepare(batch_id=rebound["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert replay["success"] and replay["counts"] == {"already_deleted": 1}, replay
    manifest_path = backend.data_dir / "manual-batches" / f"{rebound['batch_id']}.json"
    original_manifest = manifest_path.read_bytes()
    receipt_before = backend.transcript_store.list_deletion_audit(project_name="project")
    for recompute_identity in (False, True):
        altered = json.loads(original_manifest)
        changed = {**frozen, "source_id": "another-native-source"}
        if recompute_identity:
            changed = session_reference(*(changed[key] for key in ("client", "session_id", "source_id", "source_revision")))
            altered["bindings"] = {changed["reference_id"]: canonical_job.id}
        altered["sessions"] = [changed]
        manifest_path.write_text(json.dumps(altered), encoding="utf-8")
        rejected = handlers.tool_inspect_sessions(project_name="project", project_root=str(root), batch_id=rebound["batch_id"])
        assert not rejected["success"], rejected
        manifest_path.write_bytes(original_manifest)
    assert backend.transcript_store.list_deletion_audit(project_name="project") == receipt_before
    assert handlers.tool_inspect_sessions(project_name="project", project_root=str(root), batch_id=rebound["batch_id"])["success"]
