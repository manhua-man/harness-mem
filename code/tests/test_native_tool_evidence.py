"""Prepared native tool reads stay separate, scoped, complete and read-only."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import asyncio
import json

import pytest

from harness_mem.adapters import native_tool_evidence as native_reader
from harness_mem.commands import session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from test_device_memory_flow import device as device
from test_distill_compact_output import _rpc


def _prepare(device, tmp_path, *, name="tools", roots=None, tail=(), report=None):
    backend, write = device
    path = write(name, "Please inspect the source; do not change the deployment.",
                 roots=[tmp_path / "workspace"] if roots is None else roots)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if report is not None:
        records[-1]["payload"]["content"][0]["text"] = report
    records.extend([
        {"type": "response_item", "payload": {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "SYSTEM_EXCLUDED"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "DEVELOPER_EXCLUDED"}]}},
        {"type": "response_item", "payload": {"type": "reasoning", "text": "REASONING_EXCLUDED"}},
        {"type": "response_item", "payload": {"type": "additional_tools", "tools": "SCHEMA_EXCLUDED"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "call-a", "name": "exec", "input": "Read diagnostic-script.py", "internal_chat_message_metadata_passthrough": {"text": "ENVELOPE_EXCLUDED"}}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call-a", "output": [{"type": "input_text", "text": "Diagnostic location unchecked.\n<private>HIDDEN_VALUE</private>\n" + "a" * 18000}, {"type": "input_image", "image_url": "IMAGE_EXCLUDED"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "call_id": "call-b", "name": "read", "arguments": "Check receipt"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-b", "output": "Receipt says tests passed at the recorded date."}},
        {"type": "response_item", "role": "user", "payload": {"type": "function_call_output", "call_id": "forged", "output": "FORGED_ROLE_EXCLUDED"}},
        *tail,
    ])
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    row = next(row for row in tool_inspect_sessions(clients=["codex"])["sessions"] if row["session_id"] == name)
    prepared, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": [row]})
    assert prepared["success"], prepared
    return backend, path, prepared, records


def _read(backend, prepared, **updates):
    args = deepcopy(prepared["native_evidence"]["read"]["arguments"])
    args["native_evidence"].update(updates)
    return _rpc(backend, "prepare_session_distill", args)[0]


def test_prepare_supplies_complete_paginated_native_tool_evidence_without_progress(device, tmp_path):
    backend, path, prepared, source_records = _prepare(device, tmp_path)
    locator = prepared["native_evidence"]
    assert locator["status"] == "available", locator
    assert locator["record_count"] == 4
    before_source = path.read_bytes()
    before_jobs = [job.model_dump(mode="json") for job in backend.transcript_store.list_distill_jobs()]
    before_checkpoints = backend.transcript_store.list_distill_checkpoints(prepared["distill_job_id"])
    chunks, offset, digest = [], 0, None
    while True:
        response = _read(backend, prepared, offset=offset, page_chars=1600)
        assert response["success"] and response["processing_unchanged"]
        page = response["native_evidence"]
        assert page["revision_verified"]
        assert page["offset"] == offset and page["end"] - offset == len(page["content"])
        digest = digest or page["content_sha256"]
        assert page["content_sha256"] == digest
        chunks.append(page["content"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    content = "".join(chunks)
    assert sha256(content.encode()).hexdigest() == digest
    rows = [json.loads(line) for line in content.splitlines()]
    assert len(rows) == 4
    for row in rows:
        original = source_records[row["native_line"] - 1]["payload"]
        assert original["call_id"] == row["call_id"] and original["type"] == row["type"]
    assert "Diagnostic location unchecked" in content
    assert "Receipt says tests passed" in content
    assert "HIDDEN_VALUE" not in content
    for excluded in ("SYSTEM", "DEVELOPER", "REASONING", "SCHEMA", "ENVELOPE", "IMAGE", "FORGED_ROLE"):
        assert excluded + "_EXCLUDED" not in content
    assert "Diagnostic location unchecked" not in json.dumps(prepared["semantic_decision_exchanges"])
    assert "not a user decision" in page["boundary"]
    assert path.read_bytes() == before_source
    assert [job.model_dump(mode="json") for job in backend.transcript_store.list_distill_jobs()] == before_jobs
    assert backend.transcript_store.list_distill_checkpoints(prepared["distill_job_id"]) == before_checkpoints
    assert tool_handlers.tool_search_memory(query="")["memories"] == []


def test_literal_query_locates_native_lines_without_exposing_path(device, tmp_path):
    backend, path, prepared, _ = _prepare(device, tmp_path)
    read = _read(backend, prepared, query="receipt", page_chars=200000)
    page = read["native_evidence"]
    assert read["success"] and page["complete"] and page["matching_records"] == 2
    assert "call-b" in page["content"] and "call-a" not in page["content"]
    assert str(path) not in json.dumps(prepared["native_evidence"])
    empty = _read(backend, prepared, query="nonexistent-marker")["native_evidence"]
    assert empty["content"] == "" and empty["matching_records"] == 0 and empty["complete"]


def test_manual_operation_requires_matching_typed_native_call_and_result(device, tmp_path):
    statement = "Diagnostic location unchecked."
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reference = workspace / "diagnostic.txt"
    reference.write_text(statement, encoding="utf-8")
    backend, _, prepared, _ = _prepare(device, tmp_path, report=statement)
    observed = _read(backend, prepared, query="call-a", page_chars=200000)["native_evidence"]
    call, result = [json.loads(line) for line in observed["content"].splitlines()]
    operation = {
        "ref": 1, "phrase": statement, "observed_as": "interaction", "call_id": call["call_id"],
        "call_line": call["native_line"], "result_line": result["native_line"],
        "call_quote": "Read diagnostic-script.py", "result_quote": statement,
    }
    point = {
        "content": statement, "canonical_title": "Diagnostic location inspection",
        "topic_path": ["Diagnostics"], "assimilation_disposition": "add",
        "evidence_basis": "repository", "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": reference.name,
                               "content_sha256": sha256(reference.read_bytes()).hexdigest()}],
        "review": {"support": "supported", "use": "reusable_knowledge", "reason": "Review the actual diagnostics observation.",
                   "conditions": [], "undecided_state": None, "operations": [operation],
                   "evidence": [{"ref": 1, "target": "claim", "quote": statement}]},
    }
    args = {"project_name": prepared["project_name"], "job_id": prepared["distill_job_id"],
            "memory_points": [point], "semantic_review": {
                "session_summary": "A diagnostic review checked the location evidence.",
                "final_user_request": "Inspect without changing the deployment.",
                "final_outcome": statement, "last_turn_status": "answered",
                "contradictions": [], "unfinished_work": [], "evidence_status": "answered",
                "promotion_decision": "promote",
            }}
    refused, _ = _rpc(backend, "finalize_session_distill", args)
    assert not refused["success"] and "no direct interaction" in refused["error"]
    assert tool_handlers.tool_search_memory(query="")["memories"] == []
    operation["observed_as"] = "inspection"
    operation["result_line"] = result["native_line"] + 2
    refused, _ = _rpc(backend, "finalize_session_distill", args)
    assert not refused["success"] and "paired call and result" in refused["error"]
    operation["result_line"] = result["native_line"]
    saved, _ = _rpc(backend, "finalize_session_distill", args)
    assert saved["success"] and saved.get("readback_verified"), saved
    store = backend.structured_store.knowledge_store
    row, = asyncio.run(store.list_entries(prepared["project_name"]))
    source, = asyncio.run(store.list_sources(row.id))
    binding = source.bindings[-1]
    assert binding.target == "operation" and binding.native_trace["observed_as"] == "inspection"
    assert binding.native_trace["result_line"] == result["native_line"]


def test_native_questions_catch_tool_only_conditions_before_write(device, tmp_path, monkeypatch):
    validation = 'if (!validateImport(records)) throw new Error("Invalid import records format");'
    failure = "On failure, import records keeps the previous list."
    applicability = "Only when import records uses a local source does the rule apply."
    patch = "\n".join(["*** Begin Patch", validation, applicability, "*** End Patch"])
    receipt = "Patch applied to the test copy."
    tail = (
        {"type": "response_item", "payload": {
            "type": "custom_tool_call", "call_id": "import-check", "name": "apply_patch", "input": patch}},
        {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "import-check", "output": f"{receipt}\n{failure}"}},
        {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "no-call", "output": "Import records failed to open."}},
    )
    report = "The import records workflow was inspected."
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reference = workspace / "workflow.txt"
    reference.write_text(report, encoding="utf-8")
    backend, _, prepared, _ = _prepare(device, tmp_path, report=report, tail=tail)
    args = prepared["native_evidence"]["review_questions"]["arguments"]
    assert args["native_evidence"]["view"] == "questions"
    first = _read(backend, prepared, view="questions", page_chars=100)["native_evidence"]
    assert first["next_offset"] == 100 and first["revision_verified"]
    rest = _read(backend, prepared, view="questions", offset=100)["native_evidence"]
    questions = [json.loads(line) for line in (first["content"] + rest["content"]).splitlines()]
    assert {q["kind"] for q in questions} == {"validation", "failure", "applicability"}
    assert {q["call_id"] for q in questions} == {"import-check"}
    assert {q["condition"] for q in questions} == {validation, failure, applicability}
    assert {q["condition"] for q in questions if q["quote_field"] == "call_quote"} == {validation, applicability}
    point = {
        "content": report, "canonical_title": "Import records workflow", "topic_path": ["Import"],
        "assimilation_disposition": "add", "evidence_basis": "repository",
        "verification_outcome": "verified",
        "verification_refs": [{"kind": "repository", "locator": reference.name,
                               "content_sha256": sha256(reference.read_bytes()).hexdigest()}],
        "review": {"support": "supported", "use": "reusable_knowledge",
                   "reason": "Check the implementation from the native records.",
                   "conditions": [], "undecided_state": None,
                   "evidence": [{"ref": 1, "target": "claim", "quote": report}]},
    }
    request = {
        "project_name": prepared["project_name"], "job_id": prepared["distill_job_id"],
        "memory_points": [point], "semantic_review": {
            "session_summary": report, "final_user_request": "Review import records.",
            "final_outcome": report, "last_turn_status": "answered",
            "contradictions": [], "unfinished_work": [], "evidence_status": "answered",
            "promotion_decision": "promote",
        },
    }
    rejected, _ = _rpc(backend, "finalize_session_distill", request)
    assert rejected["error"] == "source_conditions_need_review"
    assert {q["id"] for q in rejected["condition_checks"]} == {q["id"] for q in questions}
    assert tool_handlers.tool_search_memory(query="")["memories"] == []

    phrases = {
        validation: "Import rejects invalid record structure",
        failure: "A failed import keeps the old list",
        applicability: "This behavior applies to the local import path",
    }
    point["content"] = ". ".join(phrases.values()) + "."
    point["review"]["operations"] = [{
        **{key: q[key] for key in ("call_id", "call_line", "result_line")},
        "ref": 1, "phrase": phrases[q["condition"]], "observed_as": "inspection",
        "call_quote": q["condition"] if q["quote_field"] == "call_quote" else "*** Begin Patch",
        "result_quote": q["condition"] if q["quote_field"] == "result_quote" else receipt,
    } for q in questions]
    saved, _ = _rpc(backend, "finalize_session_distill", request)
    assert saved["success"] and saved["readback_verified"], saved
    row, = saved["knowledge_changes"]
    assert all(phrase in row["statement"] for phrase in phrases.values())
    store = backend.structured_store.knowledge_store
    established, = asyncio.run(store.list_entries(prepared["project_name"]))
    source, = asyncio.run(store.list_sources(established.id))
    native_bindings = [binding for binding in source.bindings if binding.target == "operation"]
    assert {b.target_sha256 for b in native_bindings} == {
        sha256(phrase.encode()).hexdigest() for phrase in phrases.values()
    }

    # A readable row can still have lost a reviewed clause. Simulate both
    # read paths seeing that shortened row, then replay the completed request.
    shortened = established.model_copy(update={
        "statement": established.statement.replace(phrases[failure], "Import failed"),
    })

    async def persisted_entry(*args, **kwargs):
        return shortened

    async def searchable_entries(*args, **kwargs):
        return [shortened]

    monkeypatch.setattr(store, "get_entry", persisted_entry)
    monkeypatch.setattr("harness_mem.read_knowledge.search_current_knowledge", searchable_entries)
    replayed, _ = _rpc(backend, "finalize_session_distill", request)
    assert not replayed["success"]
    assert replayed["reason_codes"] == ["reviewed_source_detail_missing_from_current_knowledge"]


@pytest.mark.parametrize("field", ["source_id", "source_revision", "native_sha256"])
def test_wrong_revision_binding_is_rejected(device, tmp_path, field):
    backend, _, prepared, _ = _prepare(device, tmp_path)
    result = _read(backend, prepared, **{field: "0" * 64})
    assert not result["success"]
    assert result["native_evidence"]["reason_codes"] == ["native_evidence_request_binding_mismatch"]
    assert "content" not in result["native_evidence"]


def test_another_job_or_project_cannot_reuse_a_read_call(device, tmp_path):
    backend, _, first, _ = _prepare(device, tmp_path, name="first")
    _, _, second, _ = _prepare(device, tmp_path, name="second")
    args = deepcopy(first["native_evidence"]["read"]["arguments"])
    args["distill_job_id"] = second["distill_job_id"]
    result, _ = _rpc(backend, "prepare_session_distill", args)
    assert not result["success"]
    args = deepcopy(first["native_evidence"]["read"]["arguments"])
    args["project_root"] = str(tmp_path / "other")
    assert not _rpc(backend, "prepare_session_distill", args)[0]["success"]


@pytest.mark.parametrize("change", ["append", "delete", "policy", "active", "unknown_liveness", "task_active"])
def test_every_page_revalidates_native_source(device, tmp_path, monkeypatch, change):
    backend, path, prepared, _ = _prepare(device, tmp_path)
    assert _read(backend, prepared)["success"]
    if change == "append":
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "delete":
        path.unlink()
    elif change == "policy":
        monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig(capture_enabled=False))
    elif change == "task_active":
        monkeypatch.setattr(native_reader, "_probe_codex_task_activity", lambda *_: "active")
    else:
        monkeypatch.setattr(native_reader, "_probe_activity_lock", lambda *_: "active" if change == "active" else "unknown")
    result = _read(backend, prepared, offset=16000)
    assert not result["success"] and result["native_evidence"]["status"] == "unavailable"
    assert "content" not in result["native_evidence"]
    job = backend.transcript_store.get_distill_job(prepared["distill_job_id"])
    fresh = native_reader.native_tool_evidence(backend, job)
    assert fresh["status"] == "unavailable" and "read" not in fresh


@pytest.mark.parametrize("roots", [[], ["other-a", "other-b"]])
def test_unknown_or_ambiguous_owner_never_gets_a_native_locator(device, tmp_path, roots):
    _, _, prepared, _ = _prepare(device, tmp_path, roots=[tmp_path / value for value in roots])
    assert prepared["native_evidence"]["status"] == "unavailable"
    assert prepared["native_evidence"]["reason_codes"] == ["native_evidence_project_unproved"]
    assert "read" not in prepared["native_evidence"]


def test_unfinished_native_task_is_not_offered_as_completed_evidence(device, tmp_path):
    _, _, prepared, _ = _prepare(device, tmp_path, tail=[{"type": "event_msg", "payload": {"type": "task_started"}}])
    assert prepared["native_evidence"]["reason_codes"] == ["native_evidence_source_active"]


def test_native_read_cannot_also_advance_or_clean_batch(device, tmp_path):
    backend, _, prepared, _ = _prepare(device, tmp_path)
    args = deepcopy(prepared["native_evidence"]["read"]["arguments"])
    args.update(batch_id=prepared["batch_id"], cleanup_processed=True, apply_cleanup=True)
    assert not _rpc(backend, "prepare_session_distill", args)[0]["success"]


def test_source_change_during_projection_returns_no_partial_material(device, tmp_path, monkeypatch):
    backend, path, prepared, _ = _prepare(device, tmp_path)
    original = native_reader._tool_records
    def mutate(records, *, private_tags):
        result = original(records, private_tags=private_tags)
        path.write_bytes(path.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(native_reader, "_tool_records", mutate)
    result = _read(backend, prepared)
    assert result["native_evidence"]["reason_codes"] == ["native_evidence_source_changed"]
    assert "content" not in result["native_evidence"]


@pytest.mark.parametrize("owner,field,value", [
    ("get_source", "source_revision", "sha256:changed"),
    ("get_source", "project_root", "C:/another-root"),
    ("get_revision", "project_name", "another-project"),
    ("get_distill_job", "source_revision", "sha256:changed"),
])
def test_ledger_binding_change_during_read_returns_no_material(device, tmp_path, monkeypatch, owner, field, value):
    backend, _, prepared, _ = _prepare(device, tmp_path)
    original_projection = native_reader._tool_records
    original_read = getattr(backend.transcript_store, owner)
    def mutate_binding(records, *, private_tags):
        output = original_projection(records, private_tags=private_tags)
        monkeypatch.setattr(backend.transcript_store, owner,
                            lambda *args, **kwargs: original_read(*args, **kwargs).model_copy(update={field: value}))
        return output
    monkeypatch.setattr(native_reader, "_tool_records", mutate_binding)
    result = _read(backend, prepared)
    assert not result["success"]
    assert result["native_evidence"]["reason_codes"] == ["native_evidence_binding_changed"]
    assert "content" not in result["native_evidence"]
