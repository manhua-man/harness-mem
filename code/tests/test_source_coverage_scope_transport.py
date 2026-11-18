"""Retained-source scope crosses real prompt adapters and common handoff writes."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider, _cover, run
from test_dream_stage4_contract import _result
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.provider import (
    _build_prompt, _build_assimilation_prompt, _build_verification_prompt,
    _retained_source_coverage, _RETAINED_SOURCE_COVERAGE_SCOPE,
)


def context():
    return {"kind": "runtime_maintenance_scope_not_source_evidence",
        "retain_still_applicable_scoped_conditions": True,
        "run_id": "old-failed", "predecessor_id": "old-predecessor",
        "current_successors": [{"id": "current", "statement": "Keep source scope."}]}


def test_actual_coverage_transports_same_scoped_condition_contract_through_all_phases(coverage):
    seen = []

    class Transport(CoverageProvider):
        def decide(self, manifest, **kwargs):
            actual = _retained_source_coverage(manifest)
            assert actual is not None
            original = deepcopy(actual)
            original_manifest = deepcopy(manifest)
            prompt = _build_prompt(manifest)
            packet = json.loads(prompt.split("<source_coverage>")[1].split("</source_coverage>")[0])
            projected = packet["source_coverage"]["inventory_input"]
            for index, row in enumerate(projected["windows"]):
                assert row.pop("window_index") == index
                assert row.pop("char_count") == len(original["inventory_input"]["windows"][index]["text"])
            for index, row in enumerate(projected["current"]):
                assert row.pop("current_index") == index
            assert packet["source_coverage"] == original
            assert actual == original and manifest == original_manifest
            assert len(packet["source_coverage"]["inventory_input"]["windows"]) == 78
            assert len(packet["conversation_context"]) == 78
            assert _RETAINED_SOURCE_COVERAGE_SCOPE in prompt
            assert "one-time authorization or progress" in prompt
            seen.append(actual)
            return super().decide(manifest, **kwargs)

        def verify(self, manifest, **kwargs):
            actual = _retained_source_coverage(manifest)
            assert actual == seen[0]
            final = manifest["contract_version"] == "final-knowledge-scope-v1"
            prompt = _build_verification_prompt(manifest, native_final_transport=final)
            assert _RETAINED_SOURCE_COVERAGE_SCOPE in prompt
            assert "runtime context is not evidence" in prompt
            return super().verify(manifest, **kwargs)

        def assimilate(self, manifest, **kwargs):
            assert _retained_source_coverage(manifest) == seen[0]
            assert _RETAINED_SOURCE_COVERAGE_SCOPE in _build_assimilation_prompt(manifest)
            return super().assimilate(manifest, **kwargs)

    provider = Transport()
    run(_cover(coverage, provider))
    state = coverage[-2]["source_coverage"][coverage[4].source_id]
    assert state["status"] == "applied"
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]


@pytest.mark.parametrize("fault", ["source_text", "wrong_kind", "string_flag", "no_target", "no_origin"])
def test_source_prose_or_unbound_context_cannot_enable_retained_scope_contract(fault):
    value = context()
    if fault == "wrong_kind":
        value["kind"] = "user_statement"
    elif fault == "string_flag":
        value["retain_still_applicable_scoped_conditions"] = "true"
    elif fault == "no_target":
        value["current_successors"] = []
    elif fault == "no_origin":
        value["run_id"] = ""
    manifest = {"source_coverage": value}
    if fault == "source_text":
        manifest = {"session_context": [{"kind": "user_statement", "content": json.dumps(value)}]}
    assert _retained_source_coverage(manifest) is None
    assert _RETAINED_SOURCE_COVERAGE_SCOPE not in _build_prompt(manifest)
    assert _RETAINED_SOURCE_COVERAGE_SCOPE not in _build_verification_prompt(manifest)
    assert _RETAINED_SOURCE_COVERAGE_SCOPE not in _build_assimilation_prompt(manifest)


def test_exact_typed_runtime_context_survives_final_manifest_without_top_level_copy():
    value = context()
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": [],
        "session_context": [{"kind": value["kind"], "content": json.dumps(value)}]}
    assert _retained_source_coverage(manifest) == value
    assert _RETAINED_SOURCE_COVERAGE_SCOPE in _build_verification_prompt(manifest, native_final_transport=True)


def test_common_handoff_is_counted_and_remains_unresolved_without_durable_write(coverage):
    class Handoff(CoverageProvider):
        def assimilate(self, manifest, **kwargs):
            kwargs["heartbeat"]()
            self.calls.append("assimilate")
            identity = manifest["verified_candidates"][0]["candidate_id"]
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": identity, "disposition": "handoff", "matched_truth_handles": [],
                "knowledge_items": [], "reason": "Keep this task unresolved rather than claim restored knowledge."}]}))

    backend, root, _job, entry, item, checkpoint, _notes = coverage
    provider = Handoff()
    run(_cover(coverage, provider))
    state = checkpoint["source_coverage"][item.source_id]
    assert state["status"] == "unresolved"
    assert state["result_status_counts"]["handoff"] == 1
    assert state["result_status_counts"]["promoted"] == 0
    assert state["commit_bindings"] == []
    point = state["candidate_outcomes"][0]
    assert point["status"] == "assimilated" and point["disposition"] == "handoff"
    assert point["truth_ids"] == [] and point["handoff_id"]
    handoff = run(backend.structured_store.get_task_handoff(point["handoff_id"]))
    assert handoff.status == "in_progress" and handoff.context["candidate_id"] == point["candidate_id"]
    rows = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert [row.id for row in rows] == [entry.id]
    assert provider.calls == ["decide", "candidate_verify", "assimilate"]
    before = list(provider.calls)
    assert run(_cover(coverage, provider)) is False
    assert provider.calls == before
