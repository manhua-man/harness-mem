"""Writing guidance is projected from canonical input data only after full preparation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.core.schemas import EvidenceRef
from harness_mem.core.schemas.session_distill import SessionSemanticReview
from harness_mem.mcp import distill_handlers, tool_handlers
from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, _SCHEMAS, build_tools
from test_device_memory_flow import device as device


def test_contract_uses_canonical_required_fields_and_six_enum_sets():
    schema = _SCHEMAS["finalize_session_distill"]["input_schema"]
    point = schema["properties"]["memory_points"]["items"]
    review = schema["properties"]["semantic_review"]
    contract = distill_handlers._finalize_call_contract("selected-project", "selected-job")
    assert contract["tool"] == "finalize_session_distill"
    assert contract["required_fields"] == {
        "arguments": schema["required"],
        "memory_point": point["required"],
        "semantic_review": review["required"],
    }
    assert contract["allowed_values"] == {
        **{name: point["properties"][name]["enum"] for name in (
            "evidence_basis", "verification_outcome", "assimilation_disposition",
        )},
        **{name: review["properties"][name]["enum"] for name in (
            "last_turn_status", "evidence_status", "promotion_decision",
        )},
    }
    assert "full canonical finalize_session_distill input schema" in contract["optional_contracts"]


def test_contract_follows_canonical_changes_without_mutating_schema(monkeypatch):
    schema = deepcopy(_SCHEMAS["finalize_session_distill"])
    schema["input_schema"]["properties"]["memory_points"]["items"]["properties"]["verification_outcome"]["enum"].append("future-test-choice")
    schema["input_schema"]["required"].append("future-test-required")
    monkeypatch.setitem(_SCHEMAS, "finalize_session_distill", schema)
    before = deepcopy(schema)
    first = distill_handlers._finalize_call_contract("p", "job")
    assert first["allowed_values"]["verification_outcome"][-1] == "future-test-choice"
    assert first["required_fields"]["arguments"][-1] == "future-test-required"
    second = distill_handlers._finalize_call_contract("p", "job")
    first["allowed_values"]["verification_outcome"].clear()
    first["required_fields"]["arguments"].clear()
    first["args_template"]["memory_points"][0]["verification_refs"][0]["role"] = "tool"
    first["target_knowledge_example"][0]["statement"] = "changed"
    assert first["targeted_point_fragment"]["memory_points"][0]["target_knowledge"][0]["statement"] != "changed"
    first["targeted_point_fragment"]["memory_points"][0]["target_knowledge"][0]["title"] = "changed fragment"
    assert schema == before
    assert second == distill_handlers._finalize_call_contract("p", "job")


def test_strict_json_template_keeps_two_optional_independent_typed_points():
    project, job = "完整项目", "source-bound-job"
    contract = distill_handlers._finalize_call_contract(project, job)
    template = json.loads(json.dumps(contract["args_template"], allow_nan=False))
    assert template["project_name"] == project and template["job_id"] == job
    assert set(contract["required_fields"]["arguments"]) <= template.keys()
    assert len(template["memory_points"]) == 2
    assert contract["template_only"] is True
    assert "Neither is required to exist" in " ".join(contract["instructions"])
    assert "keep only relevant durable points" in " ".join(contract["instructions"])
    for point, basis, role in zip(
        template["memory_points"], ("user_statement", "source_report"), ("user", "assistant"),
    ):
        assert set(contract["required_fields"]["memory_point"]) <= point.keys()
        assert point["evidence_basis"] == basis
        assert point["verification_outcome"] == "verified"
        assert point["assimilation_disposition"] == "add"
        assert point["content"].startswith("<") and point["content"].endswith(">")
        assert isinstance(point["topic_path"], list)
        ref, = point["verification_refs"]
        assert set(ref) == {"kind", "exchange_index", "content_sha256", "role"}
        assert ref["kind"] == basis and ref["role"] == role
        assert ref["exchange_index"].startswith("<Integer exchange_index")
        assert ref["content_sha256"].startswith("<Exact content_sha256")
        # The placeholders are not fabricated source identities. Once replaced
        # with checked window metadata, their four-field shape is canonical.
        checked = {**ref, "exchange_index": 7, "content_sha256": hashlib.sha256(b"source window").hexdigest()}
        assert EvidenceRef.model_validate(checked).role == role
    review = template["semantic_review"]
    assert set(contract["required_fields"]["semantic_review"]) <= review.keys()
    assert "session_summary" in review
    for name in ("last_turn_status", "evidence_status", "promotion_decision"):
        assert review[name] == f"<Choose from allowed_values.{name}>"
        review[name] = contract["allowed_values"][name][0]
    SessionSemanticReview.model_validate(review)
    target, = contract["target_knowledge_example"]
    assert set(target) == {"title", "statement", "project_name"}
    assert all(value.startswith("<") for value in target.values())
    assert "module only when present on the selected row" in " ".join(contract["instructions"])


@pytest.mark.parametrize("disposition", ["confirm", "refine", "replace"])
def test_target_fragment_places_selected_rows_inside_each_affected_point(disposition):
    contract = distill_handlers._finalize_call_contract("prepared-owner", "prepared-job")
    final_schema = _SCHEMAS["finalize_session_distill"]["input_schema"]["properties"]
    prepare_schema = _SCHEMAS["prepare_session_distill"]["input_schema"]["properties"]
    assert "target_knowledge" in prepare_schema
    assert "target_knowledge" not in final_schema
    assert "target_knowledge" in final_schema["memory_points"]["items"]["properties"]
    assert contract["target_knowledge_path"] == "memory_points[i].target_knowledge"
    fragment = json.loads(json.dumps(contract["targeted_point_fragment"], allow_nan=False))
    assert set(fragment) == {"memory_points"}
    point_fragment, = fragment["memory_points"]
    assert set(point_fragment) == {"assimilation_disposition", "target_knowledge"}
    assert point_fragment["target_knowledge"] == contract["target_knowledge_example"]
    assert disposition in contract["allowed_values"]["assimilation_disposition"]
    selected_old_row = {
        "title": "Complete selected old title", "statement": "Entire selected old statement.",
        "project_name": "prepared-owner", "module": ["Returned original module"],
    }
    point = {**deepcopy(contract["args_template"]["memory_points"][0]),
             **point_fragment, "assimilation_disposition": disposition,
             "target_knowledge": [deepcopy(selected_old_row)]}
    arguments = {**deepcopy(contract["args_template"]), "memory_points": [point]}
    assert "target_knowledge" not in arguments
    assert arguments["memory_points"][0]["target_knowledge"] == [selected_old_row]
    assert "project_name" not in point  # Point ownership still comes from its prepared job.
    assert all("target_knowledge" not in sample for sample in contract["args_template"]["memory_points"])
    instructions = " ".join(contract["instructions"])
    assert "Add points omit target_knowledge" in instructions
    assert "never at the top level of finalize_session_distill" in instructions
    assert "does not supply a finalization point's targets" in instructions


@pytest.fixture
def compact_source(monkeypatch):
    body = "Complete parser body without exchange boundaries. SOURCE-TAIL"
    backend = SimpleNamespace(verbatim_store=SimpleNamespace(get=AsyncMock(
        return_value=SimpleNamespace(raw_content=body, metadata={"source_revision": "revision"}),
    )))
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: backend)
    monkeypatch.setattr(distill_handlers, "_load_distill_exchange_windows", lambda *_, **__: [])
    return {
        "success": True, "project_name": "p", "distill_mode": "lossless_chunks",
        "distill_status": "reviewing", "distill_job_id": "job", "source_id": "source",
        "source_revision": "revision", "evidence_mode": "semantic",
        "expected_chunk_count": 1, "completed_chunk_count": 1,
        "semantic_evidence": {"output_exchange_count": 0},
    }


def test_only_full_source_ready_prepare_attaches_contract(compact_source):
    original = deepcopy(compact_source)
    result = distill_handlers._compact_prepare_result(compact_source)
    assert result["finalize_contract"]["args_template"]["project_name"] == "p"
    assert result["finalize_contract"]["args_template"]["job_id"] == "job"
    assert result["semantic_evidence"]["content"].endswith("SOURCE-TAIL")
    assert result["semantic_evidence"]["content_sha256"] == hashlib.sha256(
        result["semantic_evidence"]["content"].encode(),
    ).hexdigest()
    assert compact_source == original


@pytest.mark.parametrize("changes", [
    {"success": False},
    {"distill_status": "processing"},
    {"distill_status": "not_queued"},
    {"evidence_mode": "raw"},
    {"completed_chunk_count": 0},
    {"chunks": [{"chunk_id": "unfinished"}]},
    {"project_name": ""},
    {"distill_job_id": ""},
    {"semantic_evidence": None},
])
def test_not_ready_results_never_retain_a_stale_contract(compact_source, changes):
    result = distill_handlers._compact_prepare_result({
        **compact_source, "finalize_contract": {"stale": True}, **changes,
    })
    assert "finalize_contract" not in result


def test_discovery_and_outer_context_failure_have_no_contract():
    discovery = {"success": True, "prepared": False, "sessions": []}
    assert distill_handlers._compact_prepare_result(discovery) == discovery

    @distill_handlers._with_complete_response_budget
    def failed_prepare():
        return {"success": False, "error": "current context unavailable", "finalize_contract": {"stale": True}}

    assert failed_prepare() == {"success": False, "error": "current context unavailable"}


def test_completed_readback_has_no_call_template(monkeypatch):
    import harness_mem.commands.distill_result as results

    backend = SimpleNamespace(transcript_store=SimpleNamespace(get_distill_job=lambda _: object()))
    monkeypatch.setattr(distill_handlers, "_get_backend", lambda: backend)
    monkeypatch.setattr(results, "current_distill_result", AsyncMock(return_value={
        "success": True, "distill_status": "completed", "knowledge_changes": [], "not_written": True,
    }))
    result = distill_handlers._compact_prepare_result({
        "success": True, "distill_status": "completed", "distill_job_id": "job",
        "finalize_contract": {"stale": True},
    })
    assert result["distill_status"] == "completed" and "finalize_contract" not in result


def test_prepare_contract_preserves_sources_context_and_leaves_knowledge_candidates_empty(device):
    backend, write = device
    user = "For future work, retain the complete source evidence. USER-TAIL"
    path = write("contract-only", user)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [{
                "type": "output_text", "text": "I propose a rotating review schedule for future work. ASSISTANT-TAIL",
            }],
        }}) + "\n")
    original = path.read_bytes()
    store = backend.structured_store.knowledge_store
    assert asyncio.run(store.list_entries("global")) == []
    assert asyncio.run(store.list_candidates("global")) == []
    full = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="contract-only", detail_level="full",
    )
    context = [{"title": "Entire old title", "statement": "Whole old statement. " * 100,
                "project_name": "context-owner", "module": ["Unchanged module"]}]
    full.update(current_knowledge=context, continuation={"cursor": "unchanged"})
    before = deepcopy(full)
    packet = distill_handlers._compact_prepare_result(full)
    template = packet["finalize_contract"]["args_template"]
    assert template["project_name"] == packet["project_name"] == "global"
    assert template["job_id"] == packet["distill_job_id"]
    assert packet["current_knowledge"] == context
    target_example = packet["finalize_contract"]["targeted_point_fragment"]["memory_points"][0]["target_knowledge"]
    assert all(value.startswith("<") for value in target_example[0].values())
    assert target_example != context  # Context never selects an old row automatically.
    assert packet["continuation"] == full["continuation"]
    for window in packet["semantic_decision_exchanges"]:
        assert hashlib.sha256(window["content"].encode()).hexdigest() == window["content_sha256"]
        old = next(item for item in full["semantic_decision_exchanges"] if item["exchange_index"] == window["exchange_index"])
        assert {key: window[key] for key in ("content", "content_sha256", "exchange_index")} == {
            key: old[key] for key in ("content", "content_sha256", "exchange_index")
        }
    assert user in packet["semantic_decision_exchanges"][0]["content"]
    assert "ASSISTANT-TAIL" in packet["semantic_decision_exchanges"][0]["content"]
    assert packet["semantic_decision_exchanges"][0]["preceding_assistant_messages"] == ["Understood."]
    assert full == before and path.read_bytes() == original
    assert asyncio.run(store.list_entries("global")) == []
    assert asyncio.run(store.list_candidates("global")) == []
    assert len(list(backend.transcript_store.list_distill_jobs())) == 1


def test_contract_projection_does_not_change_public_tools_or_input_schemas():
    schemas = deepcopy(_SCHEMAS)
    handlers = tool_handlers.build_tool_handlers()
    before = build_tools(handlers)
    distill_handlers._finalize_call_contract("p", "job")
    after = build_tools(handlers)
    assert _SCHEMAS == schemas
    assert before == after
    assert set(after) == PUBLIC_MCP_TOOL_NAMES and len(after) == 20
