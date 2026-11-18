"""Verified selected claims can commit while other source spans stay unresolved."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, _cover, run
from test_source_coverage_inventory_worker import InventoryProvider, checkpoint_slice, state
from test_source_coverage_inventory_transport import fixture, verification
from harness_mem.autonomous.models import NativeSourceCoverageVerificationDecision, SourceCoverageVerificationPoint
from harness_mem.autonomous.provider import (
    expand_source_coverage_verification_decision,
    get_source_coverage_audit_binding,
    source_coverage_audit_binding_block,
    source_coverage_audit_block,
    source_coverage_audit_has_unresolved,
    ProviderError,
)


class PointAdmissionProvider(InventoryProvider):
    def __init__(self, *, extract_verdict=None, nonextract_verdict="unclear", candidate_unverified=False, **kwargs):
        super().__init__(**kwargs)
        self.extract_verdict = extract_verdict
        self.nonextract_verdict = nonextract_verdict
        self.candidate_unverified = candidate_unverified

    def verify(self, manifest, **kwargs):
        result = super().verify(manifest, **kwargs)
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            return result
        inventory = manifest["source_coverage"]["inventory"]
        spans = {(window["w"], index): span for window in inventory["windows"]
                 for index, span in enumerate(window["spans"])}
        audit = copy.deepcopy(result.decision._source_coverage_audit["audit"])
        for row in audit:
            selected = spans[(row["w"], row["span_index"])]["d"] == "extract"
            if selected and self.extract_verdict:
                row["verdict"] = self.extract_verdict
            elif not selected:
                row["verdict"] = self.nonextract_verdict
        points = [{key: value for key, value in point.model_dump(mode="json").items()
                   if key in SourceCoverageVerificationPoint.model_fields} for point in result.decision.points]
        if self.candidate_unverified:
            points[0].update(semantic_support="partial", future_scope="unclear", source_use="unclear")
            for segment in points[0]["scope_segments"]:
                segment.update(source_support="unsupported", future_scope="unclear", source_use="unclear")
        native = NativeSourceCoverageVerificationDecision.model_validate({
            "points": points, "audit": audit})
        return replace(result, decision=expand_source_coverage_verification_decision(native, manifest=manifest))


@pytest.mark.parametrize("nonextract_verdict", ["unclear", "contradicted"])
def test_selected_supported_point_uses_common_final_and_canonical_commit_but_source_remains_unresolved(coverage, nonextract_verdict):
    backend, root, _job, original, _item, _checkpoint, _notes = coverage
    provider = PointAdmissionProvider(nonextract_verdict=nonextract_verdict)
    assert run(_cover(coverage, provider))
    saved = state(coverage)
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"], saved.get("reason_code")
    assert saved["status"] == "unresolved"
    assert saved["reason_code"] == "source_coverage_inventory_audit_unresolved"
    assert saved["result_status_counts"]["promoted"] == 1
    assert len(saved["inventory_verification"]["windows"]) == 78
    assert any(row["verdict"] == nonextract_verdict for row in saved["inventory_verification"]["audit"])
    assert source_coverage_audit_has_unresolved(saved["inventory_verification"])
    assert saved["inventory_verification"]["admission_mode"] == "selected_points"
    entries = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert original.id in {entry.id for entry in entries} and len(entries) == 2
    for proof in saved["commit_bindings"]:
        assert proof["status"] == "applied"
        assert run(backend.structured_store.knowledge_store.current_change_committed(proof["decision_id"]))


@pytest.mark.parametrize("verdict", ["unclear", "contradicted"])
def test_selected_extract_negative_prevents_assimilation_and_writes(coverage, verdict):
    provider = PointAdmissionProvider(extract_verdict=verdict)
    run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed"
    assert provider.calls == ["decide", "candidate_verify"]
    assert not state(coverage).get("commit_bindings")
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 1


def test_zero_candidate_with_unclear_audit_keeps_global_no_write_gate(coverage):
    provider = PointAdmissionProvider(no_candidate=True)
    run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed"
    assert "audit_unresolved" in state(coverage)["reason_code"]
    assert not state(coverage).get("candidate_ids")
    assert provider.calls == ["decide", "candidate_verify"]


def test_selected_mode_keeps_ordinary_point_verification_gate(coverage):
    provider = PointAdmissionProvider(candidate_unverified=True)
    run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed"
    assert provider.calls == ["decide", "candidate_verify"]
    assert not state(coverage).get("candidate_ids")


def test_selected_verified_workspace_resumes_without_changing_any_negative_audit(coverage):
    provider = PointAdmissionProvider()
    checkpoint_slice(coverage, provider)
    proof = copy.deepcopy(state(coverage)["inventory_verification"])
    assert run(_cover(coverage, provider))
    assert provider.calls == ["decide", "candidate_verify", "assimilate", "final_verify"]
    assert state(coverage)["inventory_verification"] == proof
    assert state(coverage)["status"] == "unresolved"
    assert state(coverage)["result_status_counts"]["promoted"] == 1


def test_verified_point_does_not_bypass_independent_final_output_rejection(coverage):
    provider = PointAdmissionProvider(final_failure=True)
    run(_cover(coverage, provider))
    assert "final_verify" in provider.calls
    assert state(coverage)["status"] == "failed"
    assert not any(row.get("status") == "applied" for row in state(coverage).get("commit_bindings") or [])
    assert len(run(coverage[0].structured_store.knowledge_store.list_entries("demo"))) == 1


def test_selected_point_does_not_bypass_original_context_cas(coverage, monkeypatch):
    backend, root, _job, entry, _item, _checkpoint, _notes = coverage
    provider = PointAdmissionProvider()
    original_verify = provider.verify
    def race(manifest, **kwargs):
        result = original_verify(manifest, **kwargs)
        if manifest["contract_version"] == "final-knowledge-scope-v1":
            current = run(backend.structured_store.knowledge_store.get_entry(entry.id,
                project_name="demo", project_root=root))
            current.statement += " Concurrent owner change."
            canonical = backend.structured_store._canonical
            canonical.apply_payload_transaction(idempotency_key="point-admission-context-race", mutations=[{
                "operation": "upsert", "collection": "knowledge_entries", "entity_id": entry.id,
                "payload": current.to_dict()}])
        return result
    monkeypatch.setattr(provider, "verify", race)
    with pytest.raises(ProviderError, match="successor changed"):
        run(_cover(coverage, provider))
    entries = run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(entries) == 1 and entries[0].statement.endswith("Concurrent owner change.")
    assert not any(row.get("status") == "applied" for row in state(coverage).get("commit_bindings") or [])


@pytest.mark.parametrize("fault", ["summary", "audit", "mode", "missing", "duplicate", "extract_link"])
def test_selected_workspace_resume_rejects_any_checkpoint_binding_drift(coverage, fault):
    provider = PointAdmissionProvider()
    checkpoint_slice(coverage, provider)
    saved = state(coverage)
    audit = saved["inventory_verification"]
    if fault == "summary":
        audit["summary_sha256"] = "f" * 64
    elif fault == "audit":
        audit["audit_binding_sha256"] = "f" * 64
    elif fault == "mode":
        audit["admission_mode"] = "full_inventory"
    elif fault == "missing":
        audit["audit"].pop()
    elif fault == "duplicate":
        audit["audit"].append(copy.deepcopy(audit["audit"][0]))
    else:
        next(span for window in audit["windows"] for span in window["spans"] if span["d"] == "extract")["p"] = []
    run(_cover(coverage, provider))
    assert state(coverage)["status"] == "failed"
    assert provider.calls == ["decide", "candidate_verify"]
    with pytest.raises(ValueError):
        source_coverage_audit_has_unresolved(audit)


def test_default_strict_audit_and_old_positive_checkpoint_binding_are_preserved():
    manifest, extracted = fixture()
    _runtime, verify_manifest, native = verification(manifest, extracted)
    positive = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify_manifest)
    legacy = get_source_coverage_audit_binding(positive, verify_manifest)
    assert "admission_mode" not in legacy
    assert not source_coverage_audit_has_unresolved(legacy)
    assert source_coverage_audit_binding_block(legacy, manifest) is None
    assert source_coverage_audit_binding_block(legacy, manifest, admission_mode="selected_points") is None
    native["audit"][-1]["verdict"] = "unclear"
    selected = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify_manifest)
    assert source_coverage_audit_block(selected, verify_manifest) == "source_coverage_inventory_audit_unresolved"
    assert source_coverage_audit_block(selected, verify_manifest, admission_mode="selected_points") is None
    binding = get_source_coverage_audit_binding(selected, verify_manifest, admission_mode="selected_points")
    assert source_coverage_audit_has_unresolved(binding)
    assert source_coverage_audit_binding_block(binding, manifest) is not None
    assert source_coverage_audit_binding_block(binding, manifest, admission_mode="selected_points") is None
