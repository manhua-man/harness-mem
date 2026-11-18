"""The original inventory survives real isolated manual and Dream consumers."""
import copy
from pathlib import Path

import pytest

from test_dream_stage4_contract import backend as backend, _capture_report, _output, _run, _result
from test_report_single_commit import _verdict
from test_report_original_inventory import native_vote, expand
from test_shared_maintenance_proposals import _decision
from test_native_final_scope_transport import segment
from test_dream_rendered_report_proposals import report_case as report_case, RenderedProvider, RETAINED, TEMPORARY
from harness_mem.autonomous.models import SourceClassificationPoint, CandidateVerificationDecision, AssimilationDecision
from harness_mem.commands.knowledge_assimilation import record_assimilation_result, commit_shared_knowledge_change
from harness_mem.commands.separated_assimilation import (
    prepare_separated_assimilation, validate_separated_assimilation_decision,
    final_scope_payload, final_scope_verification_rows, apply_separated_assimilation,
    judged_update_payload, final_scope_proof,
)
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEvidence
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.source_report import ReportOmission
from harness_mem.mcp.distill_handlers import _consume_supplied_final_scope


def classification(parts):
    return SourceClassificationPoint.model_validate({"candidate_index": 0, "semantic_support": "supported",
        "future_scope": "unclear", "source_use": "reusable_knowledge",
        "reason": "Every original claim, evidence qualification and disposable span is inventoried.",
        "scope_segments": parts, "claim_units": [{"first_segment": 0, "end_segment_exclusive": len(parts),
            "standalone": True, "source_support": "supported", "source_use": "reusable_knowledge", "future_scope": "durable"}]})


def manual_case(backend):
    text = "Cache remains local. Count=7. Natural startup remains unverified."
    report, source = _capture_report(backend, text)
    root = Path(backend.data_dir) / "report-project"
    ids = _run(record_assimilation_result(backend, project_root=root, source_refs=[source],
        candidate=KnowledgeCandidate(id="original-manual-report", project_name="demo", candidate_type="memory",
            statement=report.text, source_report=report),
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(),
            "statement": report.render_statement(), "topic_path": ["reports"], "claim_kind": "source_report"}],
            "reason": "Keep this exact attributed source account.", "final_scope_judgment": _verdict(report)}))
    old = _run(backend.structured_store.knowledge_store.get_entry(ids[0], project_name="demo"))
    job = SessionDistillJob(id="manual-original-source-job", idempotency_key="manual-original-source-job",
        project_name="demo", project_root=str(root), client="codex", session_id=report.session_id,
        source_id=report.source_id, source_revision=report.source_revision, status="completed", phase="done")
    with backend.transcript_store._lock:
        backend.transcript_store._distill._upsert_job_locked(job)
        backend.transcript_store._conn.commit()
    candidate = KnowledgeCandidate(id="candidate", project_name="demo", candidate_type="memory",
        statement=report.text, source_report=report)
    store = backend.structured_store.knowledge_store
    _run(store.save_candidate(candidate))
    _run(store.save_evidence(KnowledgeEvidence(project_name="demo", candidate_id=candidate.id,
        distill_job_id=job.id, evidence_basis="source_report", verification_outcome="verified",
        verification_reason_codes=["source_scope_durable", "source_use_reusable_knowledge", "future_scope_durable"],
        verification_refs=[{"kind": "source_report", "exchange_index": 1, "role": "assistant", "content_sha256": source.digest}])))
    prepared = _run(prepare_separated_assimilation(backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id]))
    output, written = _output(report, "Local cache evidence boundary", "Cache remains local. Natural startup remains unverified.")
    decision = _decision(output, ReportOmission(text=" Count=7.", classification="temporary_context"))
    decision.points[0].matched_truth_handles = list(prepared.truth_by_handle)
    decision.points[0].report_original_classification = classification([
        segment("Cache remains local."), segment(" Count=7.", temporary=True), segment(" Natural startup remains unverified.")])
    plan = validate_separated_assimilation_decision(prepared, decision)
    payload = final_scope_payload(prepared, plan["points"][0])
    rows = final_scope_verification_rows(payload, [{"kind": "source_report", "role": "assistant", "content": report.text}])
    manifest = {"contract_version": "final-knowledge-scope-v1", "candidates": rows}
    return root, candidate, old, written, prepared, plan, payload, manifest, source


@pytest.mark.parametrize("missing_vote", [False, True])
def test_real_manual_consume_then_canonical_apply_retains_inventory_and_reopens(backend, missing_vote):
    root, candidate, old, written, prepared, plan, payload, manifest, _source = manual_case(backend)
    native = native_vote(manifest)
    if missing_vote:
        native["points"][0]["update_meaning_judgment"].pop("report_preservation")
    decision = expand(manifest, native)
    before = copy.deepcopy(plan)
    refusal = _run(_consume_supplied_final_scope(backend, project_name="demo", project_root=str(root),
        candidate_ids=[candidate.id], plan=plan, contract={candidate.id: decision}))
    store = backend.structured_store.knowledge_store
    if missing_vote:
        assert refusal["reason_codes"] == ["final_scope_judgment_rejected"]
        assert plan == before
        assert _run(store.get_entry(old.id, project_name="demo")) == old
        return
    assert refusal is None
    point = plan["points"][0]
    assert "report_preservation_inventory" not in before["points"][0]
    assert point["report_preservation_inventory"] == payload["report_preservation_inventory"]
    assert point["update_meaning_judgment"]["report_preservation"]
    result = _run(apply_separated_assimilation(backend, project_name="demo", project_root=str(root),
        candidate_ids=[candidate.id], plan=plan))
    assert result.get("promoted") == 1, result
    assert _run(store.get_entry(old.id, project_name="demo")) is None
    current = _run(store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].source_report == written
    canonical = backend.structured_store._canonical
    assert written.text in canonical.get_payload_json("knowledge_entries", current[0].id)
    assert len(_run(store.list_sources(current[0].id))) == 1


def test_legacy_cached_final_proof_cannot_bypass_missing_original_inventory(backend):
    root, candidate, old, _written, _prepared, plan, payload, manifest, source = manual_case(backend)
    decision = expand(manifest, native_vote(manifest))
    stamped, blocked = judged_update_payload(payload, decision, manifest["candidates"])
    assert blocked is None
    legacy = copy.deepcopy(stamped)
    legacy.pop("report_preservation_inventory")
    legacy["update_meaning_judgment"].pop("report_preservation")
    evidence = _run(backend.structured_store.knowledge_store.list_evidence(candidate.id))[0]
    evidence.verification_reason_codes += ["autonomous_final_scope_required", final_scope_proof(legacy)]
    _run(backend.structured_store.knowledge_store.save_evidence(evidence))
    point = {**plan["points"][0], "update_meaning_judgment": legacy["update_meaning_judgment"],
        "retained_conditions": legacy["retained_conditions"]}
    point.pop("report_original_classification", None)
    with pytest.raises(ValueError, match="final_report_original_inventory_missing"):
        _run(commit_shared_knowledge_change(backend, candidate=candidate, point=point, project_root=root,
            source_refs=[source], expected_predecessor_entries=[old]))
    assert _run(backend.structured_store.knowledge_store.get_entry(old.id, project_name="demo")) == old


def test_report_confirmation_still_uses_existing_final_scope_without_body_edit_inventory(backend):
    from harness_mem.commands.knowledge_assimilation import _require_new_write_final_judgment
    _root, candidate, old, _written, _prepared, _plan, _payload, _manifest, _source = manual_case(backend)
    _require_new_write_final_judgment(candidate,
        {"disposition": "confirm", "final_scope_judgment": _verdict(old.source_report)},
        items=[], predecessors=[old], evidence_codes=set())


def test_real_dream_proposal_keeps_original_crossing_units_separate_from_output_proof(report_case):
    from harness_mem.commands.dream import dream_once
    from harness_mem.config.merge import MergedConfig
    backend, root, _report, before, _output_proposal, retained = report_case
    class Provider(RenderedProvider):
        def assimilate(self, manifest, **kwargs):
            kwargs["heartbeat"]()
            self.charge()
            self.phases.append("proposal")
            self.manifests.append(copy.deepcopy(manifest))
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": manifest["verified_candidates"][0]["candidate_id"], "disposition": "replace",
                "matched_truth_handles": [manifest["current_truth"][0]["handle"]],
                "report_outputs": [self.case[4].model_dump(mode="json")],
                "report_omissions": [{"text": TEMPORARY, "classification": "temporary_context"}],
                "reason": "Keep the complete useful original account and omit only a disposable run statistic."}]}))

        def verify(self, manifest, **kwargs):
            if manifest["contract_version"] != "final-knowledge-scope-v1":
                super().verify(manifest, **kwargs)
                point = classification([segment(RETAINED), segment(TEMPORARY, temporary=True)])
                return _result(CandidateVerificationDecision(points=[point.model_dump(mode="json")]))
            if any(row.get("update_context") for row in manifest["candidates"]):
                kwargs["heartbeat"]()
                self.charge()
                self.phases.append("final")
                self.manifests.append(copy.deepcopy(manifest))
                assert manifest["candidates"][0]["update_context"]["report_preservation_inventory"]["claim_units"][0]["end_segment_exclusive"] == 2
                return _result(expand(manifest, native_vote(manifest)))
            return super().verify(manifest, **kwargs)
    provider = Provider(report_case)
    result = _run(dream_once(backend, project_name="demo", project_root=root, source="agent",
        semantic_provider=provider, config=MergedConfig(distill_autonomous_enabled=True)))
    current = _run(backend.structured_store.knowledge_store.list_entries("demo", project_root=root))
    assert len(current) == 1 and current[0].source_report == retained, (result.notes, result.items, provider.phases)
    assert _run(backend.structured_store.knowledge_store.get_entry(before.id, project_name="demo")) is None
    assert provider.phases.count("source") == 1 and provider.phases.count("final") == 1
    original = result.continuation["verification"][before.id]["point"]
    assert original["claim_units"][0]["end_segment_exclusive"] == 2
    final = next(manifest for manifest in provider.manifests
        if any(row.get("update_context") for row in manifest.get("candidates", [])))
    assert final["candidates"][0]["update_context"]["report_preservation_inventory"]["claim_units"][0]["end_segment_exclusive"] == 2
