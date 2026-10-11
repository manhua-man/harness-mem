from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import governance_handlers, tool_handlers
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def manual_fixture(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: CursorAdapter(None, projects_dir=projects))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "fixture-runtime")

    def write(name, text="hello"):
        path = projects / "bucket" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"role": "user", "cwd": str(root), "message": {"content": [{"type": "text", "text": text}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello, ready to help."}]}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        return path

    yield backend, root, write
    asyncio.run(backend.close())


def start(root, sessions, **options):
    return tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(root), batch_sessions=sessions, **options)


def resume(root, batch_id, **options):
    return tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(root), batch_id=batch_id, **options)


def review(packet):
    return {
        "session_summary": "The session exchanged a greeting without making durable decisions.",
        "final_user_request": "greeting", "final_outcome": "greeting answered",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "no_promotion",
        "zero_candidate_challenge": {
            **packet["zero_candidate_challenge_template"],
            "evidence_fidelity": "complete", "future_utility": "session_only",
            "conclusion": "no_durable_candidate",
            "rationale": "The complete source contains only greetings and no reusable decision.",
            "checks": {key: "absent" for key in packet["zero_candidate_challenge_template"]["checks"]},
        },
    }


def test_manual_batch_is_not_offered_to_background(manual_fixture):
    from harness_mem.commands.distill_lifecycle import pending_distill_jobs

    backend, root, write = manual_fixture
    write("manual-only")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    job_id = packet["distill_job_id"]
    offered = pending_distill_jobs(backend, project_name="project", background_only=True)
    assert job_id not in [job.id for job in offered]
    assert backend.transcript_store.get_distill_job(job_id).last_agent_offered_at is None
    assert resume(root, packet["batch_id"])["distill_job_id"] == job_id


def test_background_preferred_manual_job_does_not_call_provider(manual_fixture):
    from harness_mem.autonomous.worker import run_autonomous_distill_batch

    backend, root, write = manual_fixture
    source = write("preferred-manual")
    source_before = source.read_bytes()
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    before = job.to_dict()

    class NoCalls:
        name = "test_cli"

        def __getattr__(self, name):
            pytest.fail(f"background tried to call provider: {name}")

    result = run_autonomous_distill_batch(
        backend, project_name="project", project_root=root,
        config=MergedConfig(distill_autonomous_enabled=True),
        trigger_id=job.session_id, client="cursor", provider=NoCalls(),
        preferred_job_id=job.id,
    )
    assert result["outcomes"] == []
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == before
    assert source.read_bytes() == source_before
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))


def test_background_excludes_frozen_but_not_yet_bound_source(manual_fixture):
    from harness_mem.commands.distill_lifecycle import pending_distill_jobs
    from harness_mem.commands.manual_distill import is_manual_distill_job

    backend, root, write = manual_fixture
    write("first")
    later = write("later")
    sessions = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    packet = start(root, sessions)
    # A Hook may capture a selected later source while the Agent handles first.
    adapter = CursorAdapter(backend, projects_dir=root.parent / "cursor", project_root=root)
    captured = asyncio.run(adapter.sync_session(later, "later", "project"))
    job = backend.transcript_store.get_distill_job(captured.distill_job_id)
    assert not job.manual_only
    assert is_manual_distill_job(backend, job)
    assert pending_distill_jobs(backend, project_name="project", background_only=True) == []
    # Selection is reserved even when the batch stops, rather than handed to Dream.
    manifest = manual_distill.ManualBatchStore(backend.data_dir).load(packet["batch_id"], "project", str(root))
    manual_distill.ManualBatchStore(backend.data_dir).record_failure(
        packet["batch_id"], "project", str(root), manifest["sessions"][0]["reference_id"],
        "fixture_stop", stop_batch=True,
    )
    assert is_manual_distill_job(backend, job)


def test_manual_job_rejects_background_prepare_and_review_claim(manual_fixture):
    from harness_mem.storage.transcript_store import TranscriptStore

    backend, root, write = manual_fixture
    write("manual-claim")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    job_id = packet["distill_job_id"]
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    result = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=job_id,
        run_ingest=False, _distill_source="autonomous_worker",
    )
    assert result["reason_codes"] == ["manual_session_owned"]
    assert backend.transcript_store.claim_distill_review(
        job_id, lease_owner="background", execution_source="autonomous_worker",
    ) is None
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    reopened = TranscriptStore(backend.data_dir)
    try:
        assert reopened.get_distill_job(job_id).manual_only
    finally:
        reopened.close()
    assert backend.transcript_store.claim_distill_review(
        job_id, lease_owner="interactive", execution_source="interactive_agent",
    ) is not None


def test_explicit_manual_session_is_reserved_without_batch(manual_fixture):
    backend, root, write = manual_fixture
    source = write("single-manual")
    adapter = CursorAdapter(backend, projects_dir=root.parent / "cursor", project_root=root)
    captured = asyncio.run(adapter.sync_session(source, "single-manual", "project"))
    packet = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=captured.distill_job_id,
        run_ingest=False,
    )
    assert packet["success"]
    assert backend.transcript_store.get_distill_job(captured.distill_job_id).manual_only


def test_manual_cannot_steal_active_background_review(manual_fixture):
    backend, root, write = manual_fixture
    source = write("owned-background")
    adapter = CursorAdapter(backend, projects_dir=root.parent / "cursor", project_root=root)
    captured = asyncio.run(adapter.sync_session(source, "owned-background", "project"))
    job_id = captured.distill_job_id
    packet = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=job_id,
        run_ingest=False, _distill_source="autonomous_worker",
    )
    assert packet["success"]
    assert backend.transcript_store.claim_distill_review(
        job_id, lease_owner="background", execution_source="autonomous_worker",
    ) is not None
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    result = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=job_id, run_ingest=False,
    )
    assert not result["success"]
    assert result["reason_codes"] == ["review_already_owned"]
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before


def test_unbound_frozen_selection_blocks_store_review_claim(manual_fixture):
    from harness_mem.storage.transcript_store import TranscriptStore

    backend, root, write = manual_fixture
    write("first")
    later = write("later-frozen")
    selected = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    start(root, selected)
    captured = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(later, "later-frozen", "project"))
    job_id = captured.distill_job_id
    assert not backend.transcript_store.get_distill_job(job_id).manual_only
    for chunk, _ in backend.transcript_store.claim_distill_chunks(job_id, lease_owner="interactive"):
        backend.transcript_store.checkpoint_distill_chunk(job_id, chunk.id, lease_owner="interactive", result={})
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    other = TranscriptStore(backend.data_dir)
    try:
        assert other.claim_distill_review(
            job_id, lease_owner="background", execution_source="autonomous_worker",
        ) is None
        assert other.get_distill_job(job_id).to_dict() == before
    finally:
        other.close()


def test_manifest_publish_blocks_claim_before_job_reservation(manual_fixture, monkeypatch):
    from threading import Event, Thread
    from harness_mem.storage.manual_batch_store import ManualBatchStore
    from harness_mem.storage.transcript_store import TranscriptStore

    backend, root, write = manual_fixture
    source = write("publish-race")
    captured = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(source, "publish-race", "project"))
    job_id = captured.distill_job_id
    for chunk, _ in backend.transcript_store.claim_distill_chunks(job_id, lease_owner="interactive"):
        backend.transcript_store.checkpoint_distill_chunk(job_id, chunk.id, lease_owner="interactive", result={})
    selected = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    original = ManualBatchStore.create
    denied = []
    threads = []
    started = Event()
    other = TranscriptStore(backend.data_dir)

    def publish(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        def compete():
            try:
                started.set()
                denied.append(other.claim_distill_review(
                    job_id, lease_owner="background", execution_source="autonomous_worker",
                ) is None)
            finally:
                other.close()
        thread = Thread(target=compete)
        thread.start()
        threads.append(thread)
        assert started.wait(timeout=2)
        return result

    monkeypatch.setattr(ManualBatchStore, "create", publish)
    result = start(root, selected)
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert result["success"], result
    assert denied == [True]


def test_freeze_refuses_existing_background_claim_without_manifest(manual_fixture):
    from harness_mem.storage.manual_batch_store import ManualBatchStore

    backend, root, write = manual_fixture
    source = write("preexisting-lease")
    captured = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(source, "preexisting-lease", "project"))
    packet = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root), distill_job_id=captured.distill_job_id,
        run_ingest=False, _distill_source="autonomous_worker",
    )
    job_id = packet["distill_job_id"]
    assert backend.transcript_store.claim_distill_review(
        job_id, lease_owner="background", execution_source="autonomous_worker",
    ) is not None
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    result = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert not result["success"]
    assert not list(ManualBatchStore(backend.data_dir).root.glob("*.json"))
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before


def test_unbound_frozen_selection_blocks_background_chunks(manual_fixture):
    backend, root, write = manual_fixture
    write("first")
    later = write("later-chunks")
    start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    captured = asyncio.run(CursorAdapter(
        backend, projects_dir=root.parent / "cursor", project_root=root,
    ).sync_session(later, "later-chunks", "project"))
    job_id = captured.distill_job_id
    before = backend.transcript_store.get_distill_job(job_id).to_dict()
    assert backend.transcript_store.claim_distill_chunks(
        job_id, lease_owner="background", execution_source="autonomous_worker",
    ) == []
    assert backend.transcript_store.get_distill_job(job_id).to_dict() == before
    assert backend.transcript_store.claim_distill_chunks(job_id, lease_owner="interactive")


def _seed_readable_memory(backend, root, *, title, statement, module="Progress", project="project"):
    """Only seed a fictional isolated store; production callers use governance."""
    from datetime import datetime, timezone
    from uuid import uuid4
    from harness_mem.core.schemas import AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef

    policy = root / f"seed-{uuid4().hex}.txt"
    policy.write_text(statement, encoding="utf-8")
    candidate = KnowledgeCandidate(project_name=project, candidate_type="memory", statement=statement)
    entry = KnowledgeEntry(project_name=project, module_path=[module], title=title,
                           statement=statement, verified_at=datetime.now(timezone.utc))
    asyncio.run(backend.structured_store.knowledge_store.apply_current_change(
        project_root=root, candidate_before=candidate,
        candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=AssimilationDecision(project_name=project, candidate_id=candidate.id,
                                      disposition="add", canonical_truth_ids=[entry.id], reason="Seed fictional current knowledge."),
        added_entries=[entry], predecessor_entries=[], source_refs_by_entry={entry.id: [
            ProjectKnowledgeSourceRef(label=policy.name, target=policy.resolve().as_uri(), kind="repository",
                                      digest=hashlib.sha256(policy.read_bytes()).hexdigest())]},
    ))
    return entry


def _suggest_readable_memory(backend, root, packet, *, title, statement, disposition="add", targets=None):
    policy = root / (title.replace(" ", "-") + ".txt")
    policy.write_text(statement, encoding="utf-8")
    return governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": "policy.txt", "distill_job_id": packet["distill_job_id"],
        "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": policy.name,
                               "content_sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}],
        "assimilation_disposition": disposition, "assimilation_reason": "Verified independent current project requirement.",
        "canonical_title": title, "topic_path": ["Progress"], "target_knowledge": targets or [],
    })


def _memory_review(packet):
    semantic = {key: value for key, value in review(packet).items() if key != "zero_candidate_challenge"}
    return {**semantic, "promotion_decision": "promote", "final_outcome": "已记住全部内容。"}


@pytest.mark.parametrize("disposition", ["add", "no_write"])
def test_invalid_review_preserves_candidates_before_any_assimilation(manual_fixture, disposition):
    backend, root, write = manual_fixture
    write("invalid-review", "Adopt the project result policy.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    suggestion = _suggest_readable_memory(backend, root, packet, title="Result policy",
                                         statement="The service stores a result for each task.", disposition=disposition)
    candidate_id = suggestion["entry_id"]
    store = backend.structured_store.knowledge_store
    before = asyncio.run(store.get_candidate(candidate_id)).to_dict()
    evidence_before = [item.to_dict() for item in asyncio.run(store.list_evidence(candidate_id))]
    invalid = {**_memory_review(packet), "last_turn_status": "partial"}
    result = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], invalid)
    assert not result["success"] and result["reason_codes"] == ["semantic_review_invalid"]
    assert asyncio.run(store.get_candidate(candidate_id)).to_dict() == before
    assert [item.to_dict() for item in asyncio.run(store.list_evidence(candidate_id))] == evidence_before
    assert not asyncio.run(store.list_entries("project"))
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).status == "reviewing"


def test_manual_replaces_by_old_text_and_saves_unrelated_memory(manual_fixture):
    backend, root, write = manual_fixture
    old = _seed_readable_memory(backend, root, title="Saved progress", statement="The service saves progress once per day.")
    write("change", "Adopt the new progress and result policies.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    search = tool_handlers.tool_search_memory(project_name="project", query="")
    selection = next(item for item in search["memories"] if item["title"] == old.title)
    assert "id" not in selection
    changed = "The service saves progress before finishing a task."
    added = "The service stores a separate result for each task."
    assert _suggest_readable_memory(backend, root, packet, title="Saved progress", statement=changed,
                                   disposition="replace", targets=[selection])["success"]
    assert _suggest_readable_memory(backend, root, packet, title="Task results", statement=added)["success"]
    final = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _memory_review(packet))
    assert final["success"], final
    assert final["organization_status"] == "completed"
    assert final["promotion"]["promoted"] == 2
    persisted = asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))
    assert {item.statement for item in persisted} == {changed, added}
    assert old.id not in {item.id for item in persisted}
    normal = json.dumps(tool_handlers.tool_search_memory(project_name="project", query=""))
    assert changed in normal and added in normal and old.statement not in normal
    assert {item["change"] for item in final["knowledge_changes"]} == {"added", "replaced"}


@pytest.mark.parametrize("add_new", [False, True])
def test_manual_confirmation_is_not_shown_as_newly_written(manual_fixture, monkeypatch, add_new):
    from pathlib import Path
    from harness_mem.mcp import distill_handlers

    backend, root, write = manual_fixture
    monkeypatch.setattr(distill_handlers, "_session_notes_dir", lambda _: backend.data_dir / "notes")
    old = _seed_readable_memory(backend, root, title="Existing rule", statement="The service preserves progress.")
    write("confirmation", "Confirm the existing rule and adopt an independent result rule.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert _suggest_readable_memory(backend, root, packet, title=old.title,
                                   statement=old.statement, disposition="confirm")["success"]
    if add_new:
        assert _suggest_readable_memory(backend, root, packet, title="Result rule",
                                       statement="Each task retains its result.")["success"]
    final = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _memory_review(packet))
    assert final["success"], final
    assert final["promotion"]["confirmed"] == 1
    written = final["answer_packet"]["promoted_items"]
    assert len(written) == int(add_new)
    assert all(item["title"] != old.title for item in written)
    note = Path(final["note"]["path"]).read_text(encoding="utf-8")
    assert f"形成长期记忆：{int(add_new)} 条" in note
    assert "写入 2 条" not in note
    assert len(final["knowledge_changes"]) == int(add_new)


@pytest.mark.parametrize("problem", ["missing", "ambiguous", "changed", "foreign", "bad_module", "missing_decision"])
def test_unresolved_manual_point_does_not_block_valid_add(manual_fixture, monkeypatch, problem):
    from harness_mem.mcp import distill_handlers
    backend, root, write = manual_fixture
    monkeypatch.setattr(distill_handlers, "_session_notes_dir", lambda _: backend.data_dir / "notes")
    old = _seed_readable_memory(backend, root, title="Saved progress", statement="The service saves progress once per day.")
    if problem == "ambiguous":
        _seed_readable_memory(backend, root, title=old.title, statement="The service saves progress every hour.", module="Other progress")
    foreign = _seed_readable_memory(backend, root, title="Foreign progress", statement="The other project retains progress.", project="elsewhere")
    source = write("partial", "Adopt the progress and result policies independently.")
    before = source.read_bytes()
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    selection = [] if problem == "missing" else [{"title": old.title}] if problem == "ambiguous" else [
        {"title": foreign.title if problem == "foreign" else old.title,
         "statement": foreign.statement if problem == "foreign" else "The old content has changed." if problem == "changed" else old.statement}]
    changed = "The service saves progress before finishing a task."
    broken = _suggest_readable_memory(backend, root, packet, title="Saved progress",
                                     statement=changed,
                                     disposition="replace", targets=selection)
    assert broken["success"], broken
    if problem in {"missing_decision", "bad_module"}:
        candidate = asyncio.run(backend.structured_store.knowledge_store.get_candidate(broken["entry_id"]))
        if problem == "missing_decision":
            candidate.assimilation_disposition = None
        else:
            candidate.topic_path = ["candidate promotion"]
        asyncio.run(backend.structured_store.knowledge_store.save_candidate(candidate))
    added = "The service stores a separate result for each task."
    assert _suggest_readable_memory(backend, root, packet, title="Task results", statement=added)["success"]
    final = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _memory_review(packet))
    assert final["success"], final
    assert final["organization_status"] == "partial"
    assert final["promotion"]["promoted"] == 1 and final["promotion"]["deferred"] == 1
    assert [item["statement"] for item in final["knowledge_changes"]] == [added]
    assert final["unfinished_work"] and any("还没保存" in item for item in final["unfinished_work"])
    entries = asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))
    assert old.statement in {item.statement for item in entries}
    assert added in {item.statement for item in entries} and changed not in {item.statement for item in entries}
    assert asyncio.run(backend.structured_store.knowledge_store.get_entry(foreign.id, project_name="elsewhere")) is not None
    pending = asyncio.run(backend.structured_store.knowledge_store.get_candidate(broken["entry_id"]))
    assert pending is not None and pending.status == "deferred"
    assert source.read_bytes() == before
    assert "已记住全部内容" not in final["session_summary"]["final_outcome"]
    note = __import__("pathlib").Path(final["note"]["path"]).read_text(encoding="utf-8")
    assert added in note and "已记住全部内容" not in note
    batch = tool_inspect_sessions(str(root), batch_id=packet["batch_id"])
    assert batch["organization_status"] == "partial"
    assert batch["knowledge_changes"] == final["knowledge_changes"]
    assert batch["unfinished_work"] == final["unfinished_work"]
    asyncio.run(backend.close())
    asyncio.run(backend.init())
    replay = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], _memory_review(packet))
    assert replay["success"] and replay["organization_status"] == "partial"
    assert replay["knowledge_changes"] == final["knowledge_changes"]
    assert replay["unfinished_work"] == final["unfinished_work"]


def test_unfinished_batch_shows_saved_handoff_before_finalize(manual_fixture):
    backend, root, write = manual_fixture
    write("todo", "Run the production rollout after verification succeeds.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    handoff = governance_handlers.tool_govern_memory(action="handoff", arguments={
        "project_name": "project", "task_id": packet["distill_job_id"],
        "summary": "The production rollout is unfinished.", "status": "unfinished",
        "next_steps": ["Verify the result and run the production rollout."],
    })
    assert handoff["success"] and handoff["distill_job_id"] == packet["distill_job_id"]
    stored = asyncio.run(backend.structured_store.get_task_handoff(handoff["handoff_id"]))
    assert stored.context["distill_job_id"] == packet["distill_job_id"]
    # Preserve legacy task_id-only handoffs as readable pending work too.
    stored.context = {}
    asyncio.run(backend.structured_store.save_task_handoff(stored))
    batch = tool_inspect_sessions(str(root), batch_id=packet["batch_id"])
    assert batch["progress"]["completed"] == 0
    assert batch["unfinished_work"] == ["Verify the result and run the production rollout."]
    assert batch["knowledge_changes"] == []


def test_review_delete_uses_current_prose_without_identifier(manual_fixture):
    backend, root, _write = manual_fixture
    old = _seed_readable_memory(backend, root, title="Saved progress", statement="The service saves progress once per day.")
    result = governance_handlers.tool_govern_memory(action="decide", arguments={
        "kind": "knowledge", "decision": "delete", "project_name": "project",
        "target_knowledge": [{"title": old.title, "statement": old.statement}],
    })
    assert result["success"], result
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("project")) == []


def test_manual_batch_runs_without_background_and_retains_sources(manual_fixture, monkeypatch):
    backend, root, write = manual_fixture
    paths = [write("a"), write("b")]
    before = {path: path.read_bytes() for path in paths}
    monkeypatch.setattr(tool_handlers, "_ingest_sessions", lambda **_: pytest.fail("batch must not broad-ingest"))
    inventory = tool_inspect_sessions(str(root), clients=["cursor"])
    assert inventory["success"]
    packet = start(root, inventory["sessions"])
    assert packet["success"], packet
    batch_id = packet["batch_id"]
    for _ in paths:
        assert packet["distill_status"] == "reviewing", packet
        finalized = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], review(packet))
        assert finalized["success"], finalized
        assert finalized["source_cleanup"]["status"] == "retained"
        assert finalized["knowledge_changes"] == []
        assert finalized["not_written"] == [{"reason": "没有需要长期记住的内容", "count": 1}]
        packet = resume(root, batch_id)
        assert packet["success"], packet
    assert packet["status"] == "completed"
    assert packet["progress"]["completed"] == 2
    assert packet["knowledge_changes"] == []
    assert sum(item["count"] for item in packet["not_written"]) == 2
    assert {path: path.read_bytes() for path in paths} == before
    jobs = backend.transcript_store.list_distill_jobs(project_name="project")
    assert len(jobs) == 2
    assert all(job.retain_source for job in jobs)
    assert resume(root, batch_id)["progress"]["completed"] == 2


def test_batch_scope_frozen_and_new_revision_not_added(manual_fixture):
    backend, root, write = manual_fixture
    write("a")
    inventory = tool_inspect_sessions(str(root), clients=["cursor"])
    packet = start(root, inventory["sessions"])
    assert packet["success"], packet
    write("b")
    status = tool_inspect_sessions(str(root), batch_id=packet["batch_id"])
    assert status["progress"]["selected"] == 1
    assert status["outside_batch_pending"] == 1
    assert len(backend.transcript_store.list_distill_jobs(project_name="project")) == 1
    rebound = tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(root), batch_id=packet["batch_id"], batch_sessions=inventory["sessions"])
    assert rebound["success"] is False


def test_interrupted_raw_read_resumes_same_job_and_checkpoints(manual_fixture):
    backend, root, write = manual_fixture
    write("a", "hello " * 10000)
    inventory = tool_inspect_sessions(str(root), clients=["cursor"])
    packet = start(root, inventory["sessions"], evidence_mode="raw", chunk_limit=1)
    assert packet["success"], packet
    job_id = packet["distill_job_id"]
    chunk = packet["chunks"][0]
    tool_handlers.tool_submit_distill_chunk(job_id, chunk["chunk_id"], packet["lease_owner"], {"summary": "Read the first full chunk."})
    resumed = resume(root, packet["batch_id"], evidence_mode="raw", chunk_limit=1)
    assert resumed["success"], resumed
    assert resumed["distill_job_id"] == job_id
    assert resumed["chunks"][0]["chunk_id"] != chunk["chunk_id"]
    assert len(backend.transcript_store.list_distill_jobs(project_name="project")) == 1


def test_batch_write_has_readback_and_readable_report(manual_fixture):
    backend, root, write = manual_fixture
    write("decision", "Keep an explicit local cache contract.")
    evidence = root / "policy.txt"
    statement = "The cache retains only verified current entries."
    evidence.write_text(statement, encoding="utf-8")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert packet["success"], packet
    candidate = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": f"distill-job:{packet['distill_job_id']}", "confidence": 0.99,
        "distill_job_id": packet["distill_job_id"], "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "A current verified cache rule is useful for later maintenance.",
        "canonical_title": "Verified current cache", "topic_path": ["cache"],
    })
    assert candidate["success"], candidate
    semantic_review = {key: value for key, value in review(packet).items() if key != "zero_candidate_challenge"}
    semantic_review.update(promotion_decision="promote", final_outcome="Verified the cache rule against current policy.")
    result = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], semantic_review)
    assert result["success"], result
    expected_changes = [{"change": "added", "module": ["cache"],
                         "title": "Verified current cache", "statement": statement}]
    assert result["knowledge_changes"] == expected_changes
    assert result["not_written"] == []
    assert result["unfinished_work"] == []
    assert packet["distill_job_id"] not in json.dumps(result["knowledge_changes"])
    replay = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], {})
    assert replay["success"] and replay["idempotent_replay"]
    assert replay["knowledge_changes"] == expected_changes
    current = tool_handlers.tool_search_memory(query="", project_name="project")
    assert current["memories"] == [{"module": ["cache"], "title": "Verified current cache",
                                    "statement": statement}]
    ordinary = tool_handlers.tool_search_memory(query="verified current cache", project_name="project")
    assert ordinary["memories"] == [{"title": "Verified current cache", "statement": statement}]
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).promotion_summary["readback"]["verified"]
    final = resume(root, packet["batch_id"])
    assert final["status"] == "completed", final
    assert final["knowledge_changes"] == [{"change": "added", "module": ["cache"], "title": "Verified current cache", "statement": statement}]
    assert len(asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))) == 1
    # Starting a new batch over already-completed work does not claim old writes.
    again = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert again["status"] == "completed", again
    assert again["knowledge_changes"] == []


def test_runtime_drift_stops_before_finalization(manual_fixture, monkeypatch):
    backend, root, write = manual_fixture
    write("a")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "changed-runtime")
    assert resume(root, packet["batch_id"])["success"] is False
    final = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], review(packet))
    assert final["success"] is False
    assert final["reason_codes"] == ["runtime_version_changed"]
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).status != "completed"


def test_native_digest_does_not_override_revision_ownership(manual_fixture):
    from types import SimpleNamespace
    backend, root, write = manual_fixture
    write("a")
    reference = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"][0]
    packet = start(root, [reference])
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    foreign = revision.model_copy(update={"project_name": "other"})
    ledger = SimpleNamespace(get_revision=lambda *_: foreign)
    assert not manual_distill._same_job_scope(job, {"project_name": "project", "project_root": str(root)}, reference, ledger)


def test_legacy_completion_without_readback_needs_verification(manual_fixture):
    backend, root, write = manual_fixture
    write("a")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], review(packet))["success"]
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert session_inventory.completion_proven(job, {})
    job.promotion_summary.pop("readback")
    assert not session_inventory.completion_proven(job, {})


def test_explicit_retry_and_stopped_batch_cannot_be_bypassed(manual_fixture):
    from harness_mem.storage.manual_batch_store import ManualBatchStore
    backend, root, write = manual_fixture
    write("a")
    refs = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    packet = start(root, refs)
    store = ManualBatchStore(backend.data_dir)
    store.record_failure(packet["batch_id"], "project", str(root), refs[0]["reference_id"], "selected_source_processing_failed")
    assert resume(root, packet["batch_id"])["progress"]["states"] == {"blocked": 1}
    retried = resume(root, packet["batch_id"], retry_failures=True)
    assert retried["distill_job_id"] == packet["distill_job_id"]
    store.record_failure(packet["batch_id"], "project", str(root), refs[0]["reference_id"], "unsafe", stop_batch=True)
    assert not resume(root, packet["batch_id"], retry_failures=True)["success"]
    new_batch = start(root, refs)
    assert new_batch["status"] == "stopped"
    assert new_batch["error"] == "manual_batch_stopped"


def test_missing_selected_source_does_not_block_other_sessions(manual_fixture):
    backend, root, write = manual_fixture
    write("a")
    missing = write("b")
    write("c")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert backend.transcript_store.get_distill_job(packet["distill_job_id"]).session_id == "a"
    assert tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], review(packet))["success"]
    missing.unlink()  # Isolated fixture simulates a source disappearing externally.
    next_packet = resume(root, packet["batch_id"])
    assert backend.transcript_store.get_distill_job(next_packet["distill_job_id"]).session_id == "c"
    assert tool_handlers.tool_finalize_session_distill("project", next_packet["distill_job_id"], review(next_packet))["success"]
    report = resume(root, packet["batch_id"])
    assert report["status"] == "partial"
    assert report["progress"]["states"] == {"completed": 2, "blocked": 1}
    write("b")
    retried = resume(root, packet["batch_id"], retry_failures=True)
    assert backend.transcript_store.get_distill_job(retried["distill_job_id"]).session_id == "b"


def test_failed_readback_escalates_preexisting_failure(manual_fixture):
    from harness_mem.storage.manual_batch_store import ManualBatchStore
    backend, root, write = manual_fixture
    write("a")
    refs = tool_inspect_sessions(str(root), clients=["cursor"])["sessions"]
    packet = start(root, refs)
    store = ManualBatchStore(backend.data_dir)
    store.record_failure(packet["batch_id"], "project", str(root), refs[0]["reference_id"], "selected_source_processing_failed")
    manual_distill.record_manual_finalize_failure(backend, packet["distill_job_id"], {
        "success": False, "reason_codes": ["promotion_write_unreadable"],
    })
    manifest = store.load(packet["batch_id"], "project", str(root))
    assert manifest["state"] == "stopped"
    assert manifest["failures"][refs[0]["reference_id"]] == "selected_source_processing_failed"


def test_later_verified_replacement_does_not_reopen_earlier_session(manual_fixture):
    backend, root, write = manual_fixture
    write("a", "Review the current cache policy.")
    write("b", "Revise the cache policy.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    batch_id = packet["batch_id"]
    first_id = None
    statements = ["The cache keeps local entries for one day.", "The cache keeps verified entries for seven days."]
    for index, statement in enumerate(statements):
        evidence = root / "policy.txt"
        evidence.write_text(statement, encoding="utf-8")
        suggestion = governance_handlers.tool_govern_memory(action="suggest", arguments={
            "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
            "source": f"distill-job:{packet['distill_job_id']}", "confidence": 0.99,
            "distill_job_id": packet["distill_job_id"], "evidence_basis": "repository", "verification_outcome": "verified",
            "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "assimilation_disposition": "replace" if index else "add", "assimilation_reason": "Verified current cache retention policy.",
            "assimilation_target_ids": [first_id] if first_id else [],
            "canonical_title": "Cache retention", "topic_path": ["cache"],
        })
        assert suggestion["success"], suggestion
        semantic_review = {key: value for key, value in review(packet).items() if key != "zero_candidate_challenge"}
        semantic_review.update(promotion_decision="promote", final_outcome="Verified current policy.")
        finalized = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], semantic_review)
        assert finalized["success"], finalized
        if index == 0:
            first_id = asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))[0].id
        packet = resume(root, batch_id)
        assert packet["success"], packet
    assert packet["status"] == "completed", packet
    assert packet["progress"]["completed"] == 2
    assert packet["knowledge_changes"] == [{"change": "replaced", "module": ["cache"], "title": "Cache retention", "statement": statements[1]}]
    assert packet["removed_count"] == 1
    search = tool_handlers.tool_search_memory(query="cache retention", project_name="project")
    assert statements[1] in json.dumps(search) and statements[0] not in json.dumps(search)
    assert all(row["processing"] == "completed" for row in tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert resume(root, batch_id)["status"] == "completed"
    old_only = [row for row in tool_inspect_sessions(str(root), clients=["cursor"])["sessions"] if row["session_id"] == "a"]
    prior = start(root, old_only)
    assert prior.get("status") == "completed", prior
    assert prior["progress"]["selected"] == 1
    assert prior["knowledge_changes"] == []


def test_interruption_after_sqlite_write_recovers_without_duplicate(manual_fixture, monkeypatch):
    from harness_mem.mcp import distill_handlers
    backend, root, write = manual_fixture
    write("a", "Review the cache rule.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    statement = "The cache retains only verified current entries."
    evidence = root / "policy.txt"
    evidence.write_text(statement, encoding="utf-8")
    suggested = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
        "source": f"distill-job:{packet['distill_job_id']}", "confidence": 0.99,
        "distill_job_id": packet["distill_job_id"], "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        "assimilation_disposition": "add", "assimilation_reason": "Current verified cache policy.",
        "canonical_title": "Verified cache", "topic_path": ["cache"],
    })
    assert suggested["success"], suggested
    semantic_review = {key: value for key, value in review(packet).items() if key != "zero_candidate_challenge"}
    semantic_review.update(promotion_decision="promote", final_outcome="Verified policy.")

    async def interrupted(*args, **kwargs):
        assert len(await backend.structured_store.knowledge_store.list_entries("project")) == 1
        raise RuntimeError("fixture interruption after commit")

    with monkeypatch.context() as interrupted_context:
        interrupted_context.setattr(distill_handlers, "_build_answer_packet", interrupted)
        with pytest.raises(RuntimeError, match="after commit"):
            tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], semantic_review)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.status == "completed" and job.completion_disposition is None
    recovered = resume(root, packet["batch_id"])
    assert recovered.get("status") == "completed", json.dumps(recovered)
    assert len(asyncio.run(backend.structured_store.knowledge_store.list_entries("project"))) == 1
    assert len(backend.transcript_store.list_distill_jobs(project_name="project")) == 1
    assert statement in json.dumps(tool_handlers.tool_search_memory(query="verified cache", project_name="project"))


def test_temporary_backoff_does_not_require_explicit_failed_source_retry(manual_fixture):
    from harness_mem.storage.manual_batch_store import ManualBatchStore
    backend, root, write = manual_fixture
    write("a")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    calls = []

    def temporarily_waiting(**kwargs):
        calls.append(kwargs["distill_job_id"])
        return {"success": False, "distill_status": "retryable", "retry_after": "2099-01-01T00:00:00+00:00",
                "error": "distill_job_id is not currently eligible for Agent processing"}

    waiting = manual_distill.prepare_manual_batch(backend, project_name="project", project_root=root,
        batch_id=packet["batch_id"], sessions=None, prepare=temporarily_waiting, prepare_options={})
    assert not waiting["batch_stopped"]
    manifest = ManualBatchStore(backend.data_dir).load(packet["batch_id"], "project", str(root))
    assert manifest["failures"] == {}
    assert calls == [packet["distill_job_id"]]
    assert resume(root, packet["batch_id"])["distill_job_id"] == packet["distill_job_id"]


def test_batch_preserves_unfinished_handoff_without_calling_it_knowledge(manual_fixture):
    backend, root, write = manual_fixture
    write("a", "Continue the scoped follow-up later.")
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    handoff = governance_handlers.tool_govern_memory(action="handoff", arguments={
        "project_name": "project", "task_id": "follow-up", "summary": "Finish the scoped follow-up.",
        "status": "in_progress", "next_steps": ["Complete the follow-up."], "distill_job_id": packet["distill_job_id"],
    })
    assert handoff["success"], handoff
    semantic = review(packet)
    semantic.update(last_turn_status="unfinished", evidence_status="partial", promotion_decision="partial",
                    unfinished_work=["Complete the follow-up."])
    semantic["zero_candidate_challenge"].update(future_utility="durable", conclusion="candidate_required",
                    rationale="unfinished_handoff is preserved by the job-bound handoff.")
    semantic["zero_candidate_challenge"]["checks"]["unfinished_handoff"] = "candidate_required"
    finalized = tool_handlers.tool_finalize_session_distill("project", packet["distill_job_id"], semantic)
    assert finalized["success"], finalized
    result = resume(root, packet["batch_id"])
    assert result.get("status") == "completed", result
    assert result["knowledge_changes"] == []
    assert result["not_written"] == [{"reason": "保留为未完成事项", "count": 1}]
    stored = asyncio.run(backend.structured_store.get_task_handoff(handoff["handoff_id"]))
    assert stored is not None and stored.context["distill_job_id"] == packet["distill_job_id"]

    repeated = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    assert repeated["status"] == "completed", repeated
    assert repeated["knowledge_changes"] == []
    assert repeated["not_written"] == []
    assert "Complete the follow-up." in repeated["unfinished_work"]


@pytest.mark.parametrize("mode", ["missing_role", "missing_digest", "bad_digest", "mixed", "no_write"])
def test_user_preference_result_matches_runtime_gate_after_reopen(manual_fixture, monkeypatch, mode):
    from pathlib import Path
    from uuid import NAMESPACE_URL, uuid5

    from harness_mem.mcp import distill_handlers
    from harness_mem.mcp.distill_projection import render_distill_exchange_windows

    backend, root, write = manual_fixture
    monkeypatch.setattr(distill_handlers, "_session_notes_dir", lambda _: backend.data_dir / "notes")
    statement = "For future audits, provide a complete itemized list rather than aggregate counts."
    source = write("audit-preference", statement)
    original_source = source.read_bytes()
    packet = start(root, tool_inspect_sessions(str(root), clients=["cursor"])["sessions"])
    job_id = packet["distill_job_id"]
    job = backend.transcript_store.get_distill_job(job_id)
    observation = asyncio.run(backend.verbatim_store.get(str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))))
    digest = render_distill_exchange_windows(observation.raw_content, [1])[0]["content_sha256"]
    suggested = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "rule", "project_name": "project", "distill_job_id": job_id,
        "trigger": "conducting future audits", "pattern": statement,
        "canonical_title": "Audit presentation", "topic_path": ["Collaboration"],
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": 1,
                               "content_sha256": digest if mode in {"missing_role", "no_write"} else "0" * 64 if mode == "bad_digest" else None}],
        "assimilation_disposition": "no_write" if mode == "no_write" else "add",
        "assimilation_reason": "Explicit durable future preference.",
    })
    assert suggested["success"], suggested
    if mode == "mixed":
        evidence = root / "policy.txt"
        evidence.write_text("The cache retains only verified entries.", encoding="utf-8")
        other = governance_handlers.tool_govern_memory(action="suggest", arguments={
            "kind": "memory", "project_name": "project", "distill_job_id": job_id,
            "category": "decision", "content": evidence.read_text(encoding="utf-8"),
            "source": f"distill-job:{job_id}",
            "canonical_title": "Verified cache", "topic_path": ["cache"],
            "evidence_basis": "repository", "verification_outcome": "verified",
            "verification_refs": [{"kind": "repository", "locator": "policy.txt",
                                   "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "assimilation_disposition": "add", "assimilation_reason": "Verified current cache policy.",
        })
        assert other["success"], other
    semantic = {key: value for key, value in review(packet).items() if key != "zero_candidate_challenge"}
    semantic.update(session_summary="Organized the future audit preference.", final_user_request=statement,
                    final_outcome="已验证并记住全部偏好。", evidence_status="answered", promotion_decision="promote")
    final = tool_handlers.tool_finalize_session_distill("project", job_id, semantic)
    assert final["success"], final
    note_path = Path(final["note"]["path"])
    note = note_path.read_text(encoding="utf-8")
    assert hashlib.sha256(note_path.read_bytes()).hexdigest() == final["note"]["sha256"]
    assert Path(final["note"]["latest_path"]).read_bytes() == note_path.read_bytes()
    assert source.read_bytes() == original_source
    if mode == "missing_role":
        assert final["answer_packet"]["answer_status"] == "ANSWERED"
        assert statement in final["knowledge_changes"][0]["statement"]
        assert final["unfinished_work"] == []
    elif mode == "no_write":
        assert final["answer_packet"]["answer_status"] == "ANSWERED"
        assert final["knowledge_changes"] == []
        assert final["unfinished_work"] == []
        assert "已验证并记住全部偏好" not in final["session_summary"]["final_outcome"]
        assert "已验证并记住全部偏好" not in note
        assert "本次未新增或替换长期记忆。" in note
    elif mode == "bad_digest":
        assert final["answer_packet"]["answer_status"] == "STALE"
        assert final["knowledge_changes"] == []
        assert "已验证并记住全部偏好" not in note
        assert "无需长期记忆" not in note
    else:
        assert final["promotion"]["deferred"] + final["promotion"]["conflict"] == 1
        assert final["completion"]["disposition"] != "no_candidate"
        assert any(statement in item for item in final["unfinished_work"])
        assert final["session_summary"]["unfinished_work"] == final["unfinished_work"]
        assert "已验证并记住全部偏好" not in final["session_summary"]["final_outcome"]
        assert "已验证并记住全部偏好" not in note
        assert "无需长期记忆" not in note
        assert "## 未完成工作\n\n- 无。" not in note
        assert len(final["knowledge_changes"]) == (1 if mode == "mixed" else 0)
    asyncio.run(backend.close())
    asyncio.run(backend.init())
    replay = tool_handlers.tool_finalize_session_distill("project", job_id, semantic)
    assert replay["success"], replay
    assert replay["unfinished_work"] == final["unfinished_work"]
    report = tool_inspect_sessions(str(root), batch_id=packet["batch_id"])
    assert report["unfinished_work"] == final["unfinished_work"]
    assert report["knowledge_changes"] == final["knowledge_changes"]
    found = tool_handlers.tool_search_memory(query="Audit presentation", project_name="project")
    assert (statement in json.dumps(found)) == (mode == "missing_role")
