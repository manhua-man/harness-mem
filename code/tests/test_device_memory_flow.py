"""Fictional device sessions use the public memory loop without directory setup."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.snapshot import persist_inspected_session
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.commands.separated_assimilation import target_version
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import distill_handlers, governance_handlers, tool_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def device(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    native = tmp_path / "native" / "sessions"
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: CodexAdapter(None, sessions_dir=native))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "fictional-device-runtime")
    monkeypatch.setattr(distill_handlers, "_session_notes_dir", lambda _: backend.data_dir / "notes")

    def write(name, text, *, roots=()):
        path = native / f"rollout-{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{"type": "session_meta", "payload": {"id": name}}]
        records.extend({"type": "turn_context", "payload": {"cwd": str(root)}} for root in roots)
        for role, value in (("user", text), ("assistant", "Understood.")):
            records.append({"type": "response_item", "payload": {
                "type": "message", "role": role, "content": [{
                    "type": "input_text" if role == "user" else "output_text", "text": value,
                }],
            }})
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
        return path

    yield backend, write
    asyncio.run(backend.close())


def preference_judgment(candidate_id, title, statement, *, target=None,
                        conditions=(), undecided_state=None):
    point = {
        "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
        "source_use": "standing_decision", "reason": "The source explicitly sets a future preference.",
        "scope_segments": [{
            "text": f"{title}\n{statement}", "source_use": "standing_decision",
            "future_scope": "durable", "standalone": True, "content_role": "claim",
            "source_support": "supported",
        }],
    }
    if target:
        point["update_meaning_judgment"] = {
            "relationship": "preserves_applicable_meaning",
            "predecessor_conditions": list(conditions),
            "predecessor_statements": [target["statement"]],
            "predecessor_versions": [target_version({**target, "topic_path": target["module"]})],
            "successor_statements": [statement],
            "undecided_state": undecided_state,
            "basis": "The revised preference retains the applicable requirements and any unsettled state.",
        }
    return {candidate_id: {"points": [point]}}


def remember(backend, packet, statement, *, disposition="add", targets=None,
             conditions=(), undecided_state=None):
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    observation = asyncio.run(backend.verbatim_store.get(str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))))
    digest = render_distill_exchange_windows(observation.raw_content, [1])[0]["content_sha256"]
    title = "Fictional retention preference"
    result = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": job.project_name, "distill_job_id": job.id,
        "category": "preference", "content": statement, "source": f"distill-job:{job.id}",
        "canonical_title": title, "topic_path": ["Preferences"],
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": 1, "content_sha256": digest, "role": "user"}],
        "assimilation_disposition": disposition, "assimilation_reason": "Verified explicit future preference.",
        **({"target_knowledge": targets} if targets else {}),
    })
    assert result["success"], result
    final = tool_handlers.tool_finalize_session_distill(job.project_name, job.id, {
        "session_summary": "Verified an explicit future preference.", "final_user_request": statement,
        "final_outcome": "Saved the verified preference.", "last_turn_status": "answered",
        "contradictions": [], "unfinished_work": [], "evidence_status": "answered", "promotion_decision": "promote",
        "final_scope_judgment": preference_judgment(
            result["entry_id"], title, statement, target=targets[0] if targets else None,
            conditions=conditions, undecided_state=undecided_state),
    })
    assert final["success"], final
    return final


@pytest.mark.parametrize("context", ["rootless", "missing", "mixed"])
def test_directory_is_not_required_to_remember_find_and_correct(device, tmp_path, context):
    backend, write = device
    roots = () if context == "rootless" else (tmp_path / "gone",) if context == "missing" else (tmp_path / "gone", tmp_path / "other")
    first = "For future collaboration, keep independently verifiable facts."
    corrected = "For future collaboration, keep independently verifiable facts for fourteen days."
    paths = [write("a-first", first, roots=roots), write("b-corrected", corrected, roots=roots)]
    originals = {path: path.read_bytes() for path in paths}
    before = tool_inspect_sessions(clients=["codex"])
    assert before["success"], before
    assert len(before["sessions"]) == 2
    assert not list(backend.transcript_store.list_distill_jobs())
    selected = before["sessions"]
    packet = tool_handlers.tool_prepare_session_distill(batch_sessions=selected, scope="all")
    assert packet["success"], packet
    assert packet["session_id"] == "a-first", packet
    assert len(list(backend.transcript_store.list_distill_jobs())) == 1
    added = remember(backend, packet, first)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    source = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    assert source is not None
    assert source.parser_version == "codex-conversation-v3"
    assert b"Assistant: Understood." in backend.transcript_store.reconstruct_raw(job.source_id, source_revision=job.source_revision)
    assert added["knowledge_changes"], json.dumps(added, ensure_ascii=False)
    assert added["knowledge_changes"][0]["change"] == "added", added
    current = tool_handlers.tool_search_memory(query="")
    old = current["memories"][0]
    assert old["statement"] == first
    batch_id = packet["batch_id"]
    packet = tool_handlers.tool_prepare_session_distill(batch_id=batch_id)
    assert packet["success"] and packet["session_id"] == "b-corrected", packet
    replacement = remember(backend, packet, corrected, disposition="replace", targets=[old])
    assert replacement["knowledge_changes"][0]["change"] == "replaced", replacement
    complete = tool_handlers.tool_prepare_session_distill(batch_id=batch_id)
    assert complete["status"] == "completed", complete
    assert complete["progress"]["completed"] == 2
    assert complete["unfinished_work"] == []
    assert tool_handlers.tool_search_memory(query="")["memories"] == [{
        "module": ["Preferences"], "title": "Fictional retention preference", "statement": corrected,
        "project_name": "global",
    }]
    assert all(path.read_bytes() == content for path, content in originals.items())
    for result in (added, replacement):
        note = Path(result["note"]["path"])
        assert hashlib.sha256(note.read_bytes()).hexdigest() == result["note"]["sha256"]
    assert not (backend.data_dir / "profiles").exists()
    assert all(job.manual_only and job.retain_source for job in backend.transcript_store.list_distill_jobs())


def test_batch_prepare_and_resume_read_current_classification(device):
    backend, write = device
    original = "For the Iris archive, retain independent verification of the book titles."
    write("archive-baseline", original)
    before = tool_handlers.tool_prepare_session_distill(
        session_id="archive-baseline", client="codex", scope="all",
    )
    remember(backend, before, original)

    note = "For the Iris archive, record the book title as written and verify it independently."
    write("followup-first", note)
    write("followup-second", "For the Iris archive, show the verified book title in the reading list.")
    inventory = tool_inspect_sessions(clients=["codex"])
    selection = [row for row in inventory["sessions"] if row["session_id"].startswith("followup-")]
    first = tool_handlers.tool_prepare_session_distill(scope="all", batch_sessions=selection)
    assert first["current_module_catalog"] == {
        "project_name": "global", "paths": [["Preferences"]], "truncated": False,
    }
    assert any(row["statement"] == original and row["module"] == ["Preferences"]
               for row in first["current_knowledge"])
    remember(backend, first, note)

    second = tool_handlers.tool_prepare_session_distill(batch_id=first["batch_id"])
    assert second["session_id"] == "followup-second", second
    assert second["current_module_catalog"] == first["current_module_catalog"]
    assert {row["statement"] for row in second["current_knowledge"]
            if row["module"] == ["Preferences"]} >= {original, note}


def test_manual_review_binds_original_message_and_condition_before_write(device):
    backend, write = device
    text = "For future releases, mark approval only after the independent check passes."
    write("source-evidence", text)
    packet = tool_handlers.tool_prepare_session_distill(
        session_id="source-evidence", client="codex", scope="all",
    )
    exchange = packet["semantic_decision_exchanges"][0]
    condition = "only after the independent check passes"
    claim = {"ref": 1, "target": "claim", "message_index": 1, "quote": text}
    prerequisite = {"ref": 1, "target": "condition", "message_index": 1,
                    "condition": condition, "quote": condition}
    point = {
        "content": text, "canonical_title": "Independent approval condition",
        "topic_path": ["Release"], "assimilation_disposition": "add",
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": exchange["exchange_index"],
                               "role": "user", "content_sha256": exchange["content_sha256"]}],
        "review": {"support": "supported", "use": "standing_decision", "reason": "The user set this rule for future releases.",
                   "conditions": [condition], "undecided_state": None},
    }
    review = {
        "session_summary": "The user specified the release approval condition.",
        "final_user_request": text, "final_outcome": "Recorded the explicit condition.",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "promote",
    }

    def finalize(evidence):
        return tool_handlers.tool_finalize_session_distill(
            "global", packet["distill_job_id"], review,
            memory_points=[{**point, "review": {**point["review"], "evidence": evidence}}],
        )

    for wrong, reason in (([claim], "every retained condition"),
                          ([{**claim, "quote": "Understood."}, prerequisite], "exact, uniquely located")):
        refused = finalize(wrong)
        assert not refused["success"] and reason in refused["error"], refused
        assert tool_handlers.tool_search_memory(query="")["memories"] == []
    result = finalize([claim, prerequisite])
    assert result["success"] and result["readback_verified"], result
    store = backend.structured_store.knowledge_store
    entry, = asyncio.run(store.list_entries(project_name="global"))
    source, = asyncio.run(store.list_sources(entry.id))
    assert source.content_sha256 == exchange["content_sha256"]
    assert [binding.target for binding in source.bindings] == ["claim", "condition"]
    bound = source.bindings[1]
    assert text[bound.start:bound.end] == condition
    assert bound.target_sha256 == bound.quote_sha256 == hashlib.sha256(condition.encode()).hexdigest()
    assert "bindings" not in tool_handlers.tool_search_memory(query="")["memories"][0]


def test_cited_workflow_reports_missing_later_step_before_staging(device):
    _, write = device
    exact = "First verify the native backup checksum and then reopen the retained notes."
    write("source-workflow", exact)
    packet = tool_handlers.tool_prepare_session_distill(
        session_id="source-workflow", client="codex", scope="all",
    )
    exchange = packet["semantic_decision_exchanges"][0]
    point = {
        "content": "Verify the native backup checksum.", "canonical_title": "Backup verification",
        "topic_path": ["Maintenance"], "assimilation_disposition": "add",
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": exchange["exchange_index"],
                               "role": "user", "content_sha256": exchange["content_sha256"]}],
        "review": {"support": "supported", "use": "standing_decision",
                   "reason": "The user gave the repeatable backup workflow.",
                   "conditions": [], "undecided_state": None, "evidence": [
                       {"target": "claim", "ref": 1, "message_index": 1, "quote": exact},
                   ]},
    }
    review = {"session_summary": "Read the maintenance workflow in the source.",
              "final_user_request": exact, "final_outcome": "Collected the workflow.",
              "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
              "evidence_status": "answered", "promotion_decision": "promote"}
    refused = tool_handlers.tool_finalize_session_distill(
        "global", packet["distill_job_id"], review, memory_points=[point],
    )
    assert refused["error"] == "source_conditions_need_review", refused
    assert refused["condition_checks"][0]["kind"] == "operational_detail"
    assert "reopen the retained notes" in refused["condition_checks"][0]["condition"]
    assert tool_handlers.tool_search_memory(query="")["memories"] == []
    point["content"] = exact
    accepted = tool_handlers.tool_finalize_session_distill(
        "global", packet["distill_job_id"], review, memory_points=[point],
    )
    assert accepted["success"] and accepted["readback_verified"], accepted


@pytest.mark.parametrize("verify_preview", [False, True])
def test_device_batch_writes_each_session_to_its_bound_project(device, tmp_path, verify_preview):
    backend, write = device
    roots = [tmp_path / "one", tmp_path / "two"]
    projects = ["original-publisher", "original-editor"]
    statements = ["For the archive, verify the title before keeping it.",
                  "For the reading list, include the verified publication year."]
    profiles = backend.data_dir / "profiles"
    profiles.mkdir()
    for index, (root, project, statement) in enumerate(zip(roots, projects, statements)):
        root.mkdir()
        (profiles / f"{project}.json").write_text(json.dumps({
            "project_root": str(root), "project_name": project,
        }), encoding="utf-8")
        write(f"project-session-{index}", statement, roots=[root])

    selected = tool_inspect_sessions(scope="all", clients=["codex"])["sessions"]
    if verify_preview:
        selected = [tool_inspect_sessions(action="source", session=row)["verified_session"] for row in selected]
    # Display labels from the caller do not select a write owner.
    for row in selected:
        row["project_name"] = "unrelated"
    first = tool_handlers.tool_prepare_session_distill(scope="all", batch_sessions=selected)
    assert first["success"] and first["project_name"] == projects[0], first
    assert first["current_module_catalog"]["project_name"] == projects[0]
    # Another capture can see the second exact source before the batch binds
    # its job. It must recognize the selected revision and preserve manual ownership.
    inventory = session_inventory.collect_session_inventory(
        backend.data_dir, clients=["codex"], selected_sessions=[selected[1]],
    )
    native, = inventory.native.values()
    captured = asyncio.run(persist_inspected_session(
        backend, native, project_name=projects[1], project_root=session_inventory.normalized_root(roots[1]),
        capture_config=native.capture_config,
    ))
    pending = backend.transcript_store.get_distill_job(captured.distill_job_id)
    assert pending is not None and manual_distill.is_manual_distill_job(backend, pending)
    assert not backend.transcript_store.claim_distill_chunks(
        pending.id, lease_owner="background", execution_source="autonomous_worker",
    )
    remember(backend, first, statements[0])

    second = tool_handlers.tool_prepare_session_distill(batch_id=first["batch_id"])
    assert second["success"] and second["project_name"] == projects[1], second
    assert second["current_module_catalog"]["project_name"] == projects[1]
    assert second["current_knowledge"] == []
    remember(backend, second, statements[1])
    completed = tool_handlers.tool_prepare_session_distill(batch_id=first["batch_id"])
    assert completed["progress"]["completed"] == 2, completed

    for project, statement in zip(projects, statements):
        result = tool_handlers.tool_search_memory(scope="project", project_name=project, query="")
        assert [row["statement"] for row in result["memories"]] == [statement]
    assert not tool_handlers.tool_search_memory(scope="project", project_name="global", query="")["memories"]


@pytest.mark.parametrize("uri_root", [False, True])
def test_local_policy_changes_invalidate_cached_device_pages(device, tmp_path, monkeypatch, uri_root):
    backend, write = device
    root = tmp_path / "private-workspace"
    root.mkdir()
    policy = root / ".harness-mem.toml"
    policy.write_text("allow", encoding="utf-8")
    write("policy", "fictional-secret " * 20, roots=[root.as_uri() if uri_root else root])
    loaded = []
    def config(path):
        loaded.append(path)
        return MergedConfig(capture_enabled=path is None or policy.read_text() == "allow")
    monkeypatch.setattr(session_inventory, "load_merged_config", config)
    row, = tool_inspect_sessions(clients=["codex"])["sessions"]
    session_inventory.read_session_page(backend.data_dir, session=row, page_chars=30)
    policy.write_text("deny", encoding="utf-8")
    for cached in (True, False):
        if not cached:
            session_inventory._PAGE_CACHE.clear()
        with pytest.raises(ValueError):
            session_inventory.read_session_page(backend.data_dir, session=row, offset=30, page_chars=30)
    assert root.resolve() in loaded
    assert not list(backend.transcript_store.list_distill_jobs())


def test_ledger_device_batch_and_bound_resume_cannot_bypass_local_exclusion(device, tmp_path, monkeypatch):
    backend, write = device
    root = tmp_path / "private-workspace"
    root.mkdir()
    write("ledger-policy", "fictional-ledger-secret", roots=[root])
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    original = tool_handlers.tool_prepare_session_distill(batch_sessions=rows, scope="all")
    assert original["success"], original
    job_before = backend.transcript_store.get_distill_job(original["distill_job_id"]).to_dict()
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: CodexAdapter(None, sessions_dir=tmp_path / "empty"))
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda path: MergedConfig(capture_enabled=path is None))
    row, = tool_inspect_sessions(clients=["codex"])["sessions"]
    assert row["origin"] == "ledger" and row["readability"] == "excluded" and row["processing"] == "skipped"
    assert not tool_inspect_sessions(action="source", session=row)["success"]
    result = tool_handlers.tool_prepare_session_distill(batch_sessions=[row], scope="all")
    assert not result.get("semantic_decision_exchanges"), result
    assert result["progress"]["states"]["skipped"] == 1
    resumed = tool_handlers.tool_prepare_session_distill(batch_id=original["batch_id"])
    assert not resumed["success"] and resumed["status"] == "stopped", resumed
    assert "fictional-ledger-secret" not in json.dumps(resumed)
    assert backend.transcript_store.get_distill_job(original["distill_job_id"]).to_dict() == job_before
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("global")) == []
