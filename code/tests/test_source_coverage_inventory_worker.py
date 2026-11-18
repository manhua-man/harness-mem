"""V5 whole-source inventory runs through the actual isolated worker owner."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider, _cover, run
from harness_mem.autonomous.models import NativeSourceCoverageVerificationDecision, SourceCoverageVerificationPoint
from harness_mem.autonomous.provider import expand_source_coverage_verification_decision
from harness_mem.commands import dream_source_coverage as owner


class InventoryProvider(CoverageProvider):
    def __init__(self, *, fault=None, multiple=False, **kwargs):
        super().__init__(**kwargs)
        self.fault, self.multiple = fault, multiple
        self.extraction_manifests, self.verification_manifests = [], []

    def decide(self, manifest, **kwargs):
        self.extraction_manifests.append(copy.deepcopy(manifest))
        return super().decide(manifest, **kwargs)

    def extraction_decision(self, manifest, review, points):
        points = copy.deepcopy(points)
        if self.multiple and points:
            points.append({**points[0], "content": "During this daily-entry repair, preserve explicit corrections."})
        decision = super().extraction_decision(manifest, review, points)
        if self.fault == "initial_shape":
            decision.candidates[-1].verification_refs[0].content_sha256 = "d" * 64
        return decision

    def source_inventory(self, windows, points):
        inventory = super().source_inventory(windows, points)
        if self.fault == "gap":
            inventory[-1]["spans"][0]["s"] = 1
        elif self.fault == "unclear":
            inventory[0]["spans"][0]["d"] = "unclear"
        return inventory

    def verify(self, manifest, **kwargs):
        result = super().verify(manifest, **kwargs)
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            return result
        self.verification_manifests.append(copy.deepcopy(manifest))
        if self.fault == "missing_audit":
            result.decision._source_coverage_audit = None
        elif self.fault in {"negative_audit", "partial_candidate"}:
            points = [{key: value for key, value in point.model_dump(mode="json").items()
                       if key in SourceCoverageVerificationPoint.model_fields} for point in result.decision.points]
            if self.fault == "partial_candidate":
                points[-1].update(semantic_support="partial", future_scope="unclear", source_use="unclear")
                points[-1]["scope_segments"][0].update(source_support="unsupported", future_scope="unclear", source_use="unclear")
            audit = copy.deepcopy(result.decision._source_coverage_audit["audit"])
            if self.fault == "negative_audit":
                selected = {(window["w"], index) for window in manifest["source_coverage"]["inventory"]["windows"]
                            for index, span in enumerate(window["spans"]) if span["d"] == "extract"}
                next(row for row in audit if (row["w"], row["span_index"]) in selected)["verdict"] = "contradicted"
            native = NativeSourceCoverageVerificationDecision.model_validate({"points": points, "audit": audit})
            result = replace(result, decision=expand_source_coverage_verification_decision(native, manifest=manifest))
        return result


def state(coverage):
    return coverage[-2]["source_coverage"][coverage[4].source_id]


class Slice(Exception):
    pass


def checkpoint_slice(coverage, provider):
    calls = [0]
    async def boundary():
        calls[0] += 1
        if calls[0] == 2:
            raise Slice()
    with pytest.raises(Slice):
        run(_cover(coverage, provider, boundary=boundary))
    assert state(coverage)["status"] == "candidates_verified"


def test_v5_binds_all_authored_windows_and_extracted_points_before_any_write(coverage):
    provider = InventoryProvider()
    assert run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    source = provider.extraction_manifests[0]["source_coverage"]["inventory_input"]
    verification = provider.verification_manifests[0]["source_coverage"]
    assert len(source["windows"]) == 78
    assert [row["w"] for row in verification["inventory"]["windows"]] == list(range(78))
    assert all(row["role"] == "user" and row["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        for row in source["windows"])
    assert verification["inventory"]["extracted_points"][0]["content"] == "During this daily-entry repair, do not add acceptance rituals."
    assert len(provider.verification_manifests[0]["candidates"]) == 1
    audit = state(coverage)["inventory_verification"]
    assert audit["input_sha256"] == owner._digest(source)
    assert all(len(audit[key]) == 64 for key in (
        "inventory_sha256", "candidate_output_sha256", "verification_rows_sha256", "audit_binding_sha256"))
    assert "acceptance rituals" not in json.dumps(state(coverage))
    assert state(coverage)["status"] == "applied"


def test_v5_zero_candidate_still_requires_the_same_independent_verification_call(coverage):
    provider = InventoryProvider(no_candidate=True)
    assert run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify"]
    assert provider.verification_manifests[0]["candidates"] == []
    assert len(provider.verification_manifests[0]["source_coverage"]["inventory"]["windows"]) == 78
    assert state(coverage)["status"] == "no_write" and state(coverage)["inventory_verification"]
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 1


@pytest.mark.parametrize("fault", ["missing_audit", "negative_audit", "unclear", "gap", "partial_candidate", "initial_shape"])
def test_v5_incomplete_or_negative_inventory_cannot_write_a_selected_subset(coverage, fault):
    provider = InventoryProvider(fault=fault, multiple=fault in {"partial_candidate", "initial_shape"}, no_candidate=fault == "unclear")
    before = run(coverage[0].structured_store.knowledge_store.list_entries("demo"))
    run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed", state(coverage)
    if fault == "negative_audit":
        assert state(coverage)["reason_code"] == "source_coverage_inventory_audit_unresolved"
    elif fault == "partial_candidate":
        assert state(coverage)["reason_code"] == "source_coverage_inventory_selected_point_unverified"
    assert "assimilate" not in provider.calls and "final_verify" not in provider.calls
    assert [row.to_dict() for row in run(coverage[0].structured_store.knowledge_store.list_entries("demo"))] == [row.to_dict() for row in before]
    assert not state(coverage).get("candidate_ids") and not state(coverage).get("commit_bindings")


def test_v5_verified_slice_resumes_without_extraction_or_inventory_reaudit_and_no_prose(coverage):
    provider = InventoryProvider()
    checkpoint_slice(coverage, provider)
    assert provider.calls == ["decide", "candidate_verify"]
    frozen = copy.deepcopy(state(coverage)["inventory_verification"])
    assert "acceptance rituals" not in json.dumps(coverage[-2])
    assert run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    assert state(coverage)["inventory_verification"] == frozen
    assert len(provider.extraction_manifests) == len(provider.verification_manifests) == 1


@pytest.mark.parametrize("fault", ["input", "candidate", "evidence", "audit"])
def test_v5_resumed_slice_rejects_input_workspace_or_audit_hash_drift(coverage, monkeypatch, fault):
    provider = InventoryProvider()
    checkpoint_slice(coverage, provider)
    backend, root, _job, entry, item, checkpoint, _notes = coverage
    identity = state(coverage)["candidate_ids"][0]
    if fault == "input":
        original = owner._prepare
        async def changed(*args, **kwargs):
            prepared = await original(*args, **kwargs)
            prepared["authored_user_exchanges"][0]["text"] += " Changed runtime input."
            return prepared
        monkeypatch.setattr(owner, "_prepare", changed)
    elif fault == "candidate":
        candidate = run(backend.structured_store.knowledge_store.get_candidate(identity))
        candidate.statement += " Changed candidate workspace."
        run(backend.structured_store.knowledge_store.save_candidate(candidate))
    elif fault == "evidence":
        evidence = run(backend.structured_store.knowledge_store.list_evidence(identity))[0]
        evidence.verification_reason_codes.append("changed-evidence-workspace")
        run(backend.structured_store.knowledge_store.save_evidence(evidence))
    else:
        state(coverage)["inventory_verification"]["audit_binding_sha256"] = "f" * 64
    assert run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed" and "inventory" in state(coverage)["reason_code"]
    assert provider.calls == ["decide", "candidate_verify"]
    assert [(row.id, row.statement) for row in run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))] == [(entry.id, entry.statement)]
    assert checkpoint["max_slices"] == 24 and item.source_id == "retired-predecessor"
