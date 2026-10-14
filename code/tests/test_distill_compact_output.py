"""Compact MCP output keeps complete evidence and the existing persistence loop."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.mcp import distill_handlers, governance_handlers, tool_handlers
from harness_mem.mcp.executor import execute_tool_call
from harness_mem.mcp.response_budget import serialize_mcp_result
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.mcp.tool_specs import build_tools
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from test_device_memory_flow import device as device


CHECKS = (
    "user_correction", "explicit_decision", "successful_solution", "repeated_failure",
    "rule_or_preference", "reusable_workflow_or_fact", "version_or_migration", "unfinished_handoff",
)


def _rpc(backend, tool, arguments):
    response = execute_tool_call(
        tools=build_tools(tool_handlers.build_tool_handlers()),
        params={"name": tool, "arguments": arguments}, req_id=1,
        data_dir=lambda: backend.data_dir, cost_budgets=lambda _: None,
        project_name_for_cost=lambda *_: None, logger=logging.getLogger(__name__),
    )
    assert "error" not in response, response
    rendered = response["result"]["content"][0]["text"]
    return json.loads(rendered), len(rendered.encode("utf-8"))


def _review(statement="Read the complete fictional conversation.", **updates):
    return {
        "session_summary": "Reviewed the complete fictional conversation.",
        "final_user_request": statement, "final_outcome": "Reviewed the source.",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "promote", **updates,
    }


def _suggest(backend, packet, statement, title, *, disposition="add", targets=None):
    window, = packet["semantic_decision_exchanges"]
    result = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": packet["project_name"],
        "distill_job_id": packet["distill_job_id"], "category": "preference",
        "content": statement, "source": f"distill-job:{packet['distill_job_id']}",
        "canonical_title": title, "topic_path": ["Preferences"],
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": window["exchange_index"],
                               "content_sha256": window["content_sha256"]}],
        "assimilation_disposition": disposition, "assimilation_reason": "Verified future preference.",
        **({"target_knowledge": targets} if targets else {}),
    })
    assert result["success"], result


def test_two_original_short_sessions_through_executor_and_reopened_storage(device, tmp_path, monkeypatch):
    backend, write = device
    first = "For future collaboration, retain independently verifiable facts for thirteen days."
    second = (
        "Correction to my earlier retention preference: from now on retain independently verifiable "
        "facts for fourteen days, not thirteen days. Also, for future collaboration, answer in concise Chinese."
    )
    paths = [write("a-first", first), write("b-corrected", second, roots=[tmp_path / "former-workspace"])]
    originals = [path.read_bytes() for path in paths]
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, prepare1 = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows})
    assert packet["next_step"] == "finalize_session_distill"
    batch_id = packet["batch_id"]
    window, = packet["semantic_decision_exchanges"]
    body = window["content"]
    assert first in body and "Understood." in body
    assert hashlib.sha256(body.encode()).hexdigest() == window["content_sha256"]
    _suggest(backend, packet, first, "Retention preference")
    final1, finish1 = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"], "semantic_review": _review(first),
    })
    assert final1["organization_status"] == "completed"
    old = tool_handlers.tool_search_memory(query="")["memories"][0]
    # Explicit completed-job recovery keeps saved results, without diagnostic packets.
    recovered, _ = _rpc(backend, "prepare_session_distill", {"distill_job_id": packet["distill_job_id"]})
    assert recovered["knowledge_changes"] == final1["knowledge_changes"]
    packet, prepare2 = _rpc(backend, "prepare_session_distill", {"batch_id": batch_id})
    resumed, _ = _rpc(backend, "prepare_session_distill", {"batch_id": batch_id})
    assert resumed == packet
    corrected = "For future collaboration, retain independently verifiable facts for fourteen days."
    language = "For future collaboration, answer in concise Chinese."
    assert second in packet["semantic_decision_exchanges"][0]["content"]
    _suggest(backend, packet, corrected, "Retention preference", disposition="replace", targets=[old])
    _suggest(backend, packet, language, "Reply preference")
    final2, finish2 = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"], "semantic_review": _review(second),
    })
    assert {row["change"] for row in final2["knowledge_changes"]} == {"added", "replaced"}
    replay, _ = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"], "semantic_review": {},
    })
    assert replay["idempotent_replay"] and replay["knowledge_changes"] == final2["knowledge_changes"]
    internal = tool_handlers.tool_finalize_session_distill(
        packet["project_name"], packet["distill_job_id"], {}, _review_lease_owner="fixture-worker",
    )
    assert internal["success"] and internal["answer_packet"]
    assert internal["promotion"] and internal["structural_audit"]
    complete, _ = _rpc(backend, "prepare_session_distill", {"batch_id": batch_id})
    assert complete["status"] == "completed" and complete["progress"]["completed"] == 2
    assert complete["unfinished_work"] == []
    for final in (final1, final2):
        note = Path(final["note"]["path"])
        assert hashlib.sha256(note.read_bytes()).hexdigest() == final["note"]["sha256"]
        assert Path(final["note"]["latest_path"]).read_bytes() == note.read_bytes()
        assert not {"promotion", "answer_packet", "semantic_review", "structural_audit"} & final.keys()
    assert [path.read_bytes() for path in paths] == originals
    reopened = LocalMemoryBackend(backend.data_dir)
    asyncio.run(reopened.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
        current, _ = _rpc(reopened, "search_memory", {"query": ""})
        assert {row["statement"] for row in current["memories"]} == {corrected, language}
        entries = asyncio.run(reopened.structured_store.knowledge_store.list_entries("global"))
        assert {entry.statement for entry in entries} == {corrected, language}
        jobs = list(reopened.transcript_store.list_distill_jobs())
        assert len(jobs) == 2 and all(job.status == "completed" for job in jobs)
        assert all(job.promotion_summary["answer_packet"] for job in jobs)
    finally:
        asyncio.run(reopened.close())
    print(f"Fresh compact MCP bytes: prepare={prepare1},{prepare2}; finalize={finish1},{finish2}; total={prepare1+prepare2+finish1+finish2}")


def test_tiny_budget_keeps_all_full_exchanges_and_digests(device):
    backend, write = device
    long_user = "future preference 完整正文 " * 350 + "USER-TAIL"
    path = write("long", long_user)
    with path.open("a", encoding="utf-8") as stream:
        for role, text in (("user", "ordinary middle exchange " * 300 + "MIDDLE-TAIL"),
                           ("assistant", "Earlier assistant response must survive. EARLIER-TAIL"),
                           ("assistant", "complete assistant reply " * 300 + "ASSISTANT-TAIL"),
                           ("user", "Final question"), ("assistant", "Final answer")):
            stream.write(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
            }}) + "\n")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows, "budget_tokens": 256})
    windows = packet["semantic_decision_exchanges"]
    assert [row["exchange_index"] for row in windows] == [1, 2, 3]
    assert long_user in windows[0]["content"]
    assert "MIDDLE-TAIL" in windows[1]["content"] and "ASSISTANT-TAIL" in windows[1]["content"]
    assert windows[1]["preceding_assistant_messages"] == ["Earlier assistant response must survive. EARLIER-TAIL"]
    rendered = serialize_mcp_result(packet)
    assert rendered.count("USER-TAIL") == rendered.count("EARLIER-TAIL") == 1
    assert all(hashlib.sha256(row["content"].encode()).hexdigest() == row["content_sha256"] for row in windows)
    assert "chunks" not in packet["semantic_evidence"]
    assert not {"response_budget", "distill_instructions", "agent_execution", "zero_candidate_challenge_template"} & packet.keys()
    full, _ = _rpc(backend, "prepare_session_distill", {"batch_id": packet["batch_id"], "detail_level": "full"})
    assert full["response_budget"] and full["zero_candidate_challenge_template"]
    assert "chunks" in full["semantic_evidence"] and "distill_instructions" in full


def test_failure_retains_reason_job_and_batch_resume(device):
    backend, write = device
    write("invalid", "For future collaboration, use concise replies.")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows})
    invalid, _ = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"], "semantic_review": {},
    })
    assert invalid["success"] is False and invalid["reason_codes"] == ["semantic_review_invalid"]
    assert invalid["distill_job_id"] == packet["distill_job_id"] and invalid["distill_status"] == "reviewing"
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("global")) == []
    resumed, _ = _rpc(backend, "prepare_session_distill", {"batch_id": packet["batch_id"], "retry_failures": True})
    assert resumed["success"] and resumed["distill_job_id"] == packet["distill_job_id"]


def test_zero_candidate_without_embedded_template(device):
    backend, write = device
    write("no-memory", "What is 2 plus 2?")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows})
    required = packet["semantic_evidence"]["zero_candidate_required_exchange_indexes"]
    final, _ = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"],
        "semantic_review": _review(promotion_decision="no_promotion", zero_candidate_challenge={
            "version": "v1", "source_revision": packet["source_revision"], "evidence_fidelity": "complete",
            "future_utility": "session_only", "checks": {key: "absent" for key in CHECKS},
            "inspected_exchange_refs": [{key: row[key] for key in ("exchange_index", "content_sha256")}
                                        for row in packet["semantic_decision_exchanges"] if row["exchange_index"] in required],
            "conclusion": "no_durable_candidate", "rationale": "This arithmetic question has no durable knowledge.",
        }),
    })
    assert final["success"] and final["knowledge_changes"] == []
    assert final["not_written"] and final["organization_status"] == "completed"


def test_explicit_no_write_finishes_without_extra_questionnaire(device):
    backend, write = device
    write("ordinary-no-write", "What is 2 plus 2?")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows})
    result, _ = _rpc(backend, "finalize_session_distill", {
        "project_name": packet["project_name"], "job_id": packet["distill_job_id"],
        "semantic_review": _review(promotion_decision="no_promotion"),
    })
    assert result["success"] and result["knowledge_changes"] == []
    assert result["not_written"] and result["organization_status"] == "completed"
    finished = tool_handlers.tool_prepare_session_distill(batch_id=packet["batch_id"])
    assert finished["status"] == "completed" and finished["progress"]["completed"] == 1, finished


def test_raw_leases_and_drilldown_are_still_usable(device):
    backend, write = device
    write("raw", "For future collaboration, use concise replies.")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    packet, _ = _rpc(backend, "prepare_session_distill", {"scope": "all", "batch_sessions": rows, "evidence_mode": "raw"})
    assert packet["lease_owner"] and packet["chunks"]
    assert packet["next_step"] == "submit_distill_chunk"
    for chunk in packet["chunks"]:
        assert "raw_content" in chunk and "content_sha256" in chunk and "chunk_id" in chunk
        submitted, _ = _rpc(backend, "submit_distill_chunk", {
            "job_id": packet["distill_job_id"], "chunk_id": chunk["chunk_id"],
            "lease_owner": packet["lease_owner"], "result": {"summary": "Read the complete fictional source."},
        })
        assert submitted["success"], submitted
    drilldown, _ = _rpc(backend, "prepare_session_distill", {
        "batch_id": packet["batch_id"], "drilldown_exchange_indexes": [1],
        "drilldown_query": "concise replies",
    })
    assert drilldown["semantic_drilldown_exchanges"][0]["content"]
    assert drilldown["raw_drilldown_chunks"][0]["raw_content"]
    assert drilldown["next_step"] == "finalize_session_distill"


@pytest.mark.parametrize("source", ["ide_hook", "autonomous_worker"])
def test_internal_prepare_keeps_existing_diagnostic_consumer_shape(source):
    @distill_handlers._with_complete_response_budget
    def prepare(detail_level="compact", _distill_source="agent", budget_tokens=3000):
        return {"success": True, "semantic_evidence": {"chunks": ["existing outline"]},
                "zero_candidate_challenge_template": {"existing": True},
                "agent_execution": {"next_tool": "finalize_session_distill"}}

    result = prepare(_distill_source=source)
    assert result["zero_candidate_challenge_template"] == {"existing": True}
    assert result["semantic_evidence"]["chunks"] == ["existing outline"]
    assert result["response_budget"] and result["agent_execution"]


@pytest.mark.parametrize("missing", ["observation", "refs"])
def test_compact_source_read_failure_keeps_batch_continuation(device, monkeypatch, missing):
    backend, write = device
    write("changed", "For future collaboration, use concise replies.")
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    full = tool_handlers.tool_prepare_session_distill(scope="all", batch_sessions=rows, detail_level="full")
    if missing == "observation":
        monkeypatch.setattr(backend.verbatim_store, "get", AsyncMock(return_value=None))
    else:
        monkeypatch.setattr(distill_handlers, "_load_distill_exchange_windows", lambda *_, **__: [])
    failure = distill_handlers._compact_prepare_result(full)
    assert failure["success"] is False and failure["reason_codes"]
    assert failure["distill_job_id"] == full["distill_job_id"]
    assert failure["distill_status"] == "reviewing"
    assert failure["batch_id"] == full["batch_id"]
    assert failure["batch_progress"] == full["batch_progress"]


def test_parser_body_without_exchange_boundaries_is_not_lost(monkeypatch):
    body = "Complete unstructured parser rendering\n" + "原文 " * 400 + "LAST-LINE"
    backend = SimpleNamespace(verbatim_store=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
        raw_content=body, metadata={"source_revision": "revision"},
    ))))
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: backend)
    monkeypatch.setattr(distill_handlers, "_load_distill_exchange_windows", lambda *_, **__: [])
    result = distill_handlers._compact_prepare_result({
        "success": True, "distill_mode": "lossless_chunks", "distill_status": "reviewing",
        "distill_job_id": "job", "source_id": "source", "source_revision": "revision",
        "semantic_evidence": {"output_exchange_count": 0, "chunks": [{"content": "old outline"}]},
    })
    assert result["semantic_evidence"]["content"] == body
    assert result["semantic_evidence"]["content_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert "chunks" not in result["semantic_evidence"]
