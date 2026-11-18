"""Negative inventory observations retain evidence without admission credit."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest

from harness_mem.autonomous.models import NativeSourceCoverageVerificationDecision
from harness_mem.autonomous.provider import (
    _coverage_digest, expand_source_coverage_verification_decision,
    get_source_coverage_audit_binding, get_source_coverage_audit_observation,
    source_coverage_audit_binding_block, source_coverage_audit_block, source_coverage_audit_has_unresolved,
)
from test_source_coverage_inventory_transport import fixture, verification
from test_dream_source_coverage import CoverageProvider, coverage as coverage
from test_dream_complete_user_context import captured as captured


def observation(*, verdict="contradicted", unclear=False):
    manifest, extraction = fixture(zero=True)
    if unclear:
        extraction["inventory"][2]["spans"][0]["d"] = "unclear"
    _extracted, manifest, native = verification(manifest, extraction)
    native["audit"][0]["verdict"] = verdict
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=manifest)
    return decision, manifest, get_source_coverage_audit_observation(decision, manifest)


@pytest.mark.parametrize("verdict,unclear", [("contradicted", False), ("unclear", False), ("supported", False), ("supported", True)])
def test_observation_is_structural_evidence_and_always_unresolved(verdict, unclear):
    decision, manifest, summary = observation(verdict=verdict, unclear=unclear)
    assert summary["admission_mode"] == "observation"
    assert summary["extracted_point_sha256"] == []
    assert source_coverage_audit_has_unresolved(summary) is True
    assert source_coverage_audit_binding_block(summary, manifest, admission_mode="observation") is None
    assert source_coverage_audit_binding_block(summary, manifest)
    assert source_coverage_audit_binding_block(summary, manifest, admission_mode="selected_points")
    with pytest.raises(ValueError):
        get_source_coverage_audit_binding(decision, manifest, admission_mode="observation")
    if verdict != "supported" or unclear:
        assert source_coverage_audit_block(decision, manifest) == "source_coverage_inventory_audit_unresolved"
        with pytest.raises(ValueError, match="audit_unresolved"):
            get_source_coverage_audit_binding(decision, manifest)
    else:
        ordinary = get_source_coverage_audit_binding(decision, manifest)
        assert source_coverage_audit_binding_block(ordinary, manifest) is None
        assert source_coverage_audit_has_unresolved(ordinary) is False
    for source in manifest["source_coverage"]["inventory_input"]["windows"]:
        assert source["text"] not in json.dumps(summary, ensure_ascii=False)


@pytest.mark.parametrize("field", ["input_sha256", "inventory_sha256", "candidate_output_sha256",
    "verification_rows_sha256", "candidate_verification_sha256", "audit_binding_sha256", "summary_sha256"])
def test_observation_rejects_each_changed_hash(field):
    _decision, manifest, summary = observation()
    summary[field] = "0" * 64
    assert source_coverage_audit_binding_block(summary, manifest, admission_mode="observation")
    with pytest.raises(ValueError):
        source_coverage_audit_has_unresolved(summary)


@pytest.mark.parametrize("mutation", [
    lambda summary: summary["windows"][0]["spans"][0].update(s=1),
    lambda summary: summary["windows"][0]["spans"][0].update(e=1),
    lambda summary: summary["audit"][0].update(verdict="supported"),
    lambda summary: summary["audit"].pop(),
    lambda summary: summary.update(admission_mode="full_inventory"),
    lambda summary: summary.update(admission_mode="selected_points"),
])
def test_offsets_votes_and_mode_cannot_change_with_only_summary_resealed(mutation):
    _decision, manifest, summary = observation()
    mutation(summary)
    summary["summary_sha256"] = _coverage_digest({key: value for key, value in summary.items() if key != "summary_sha256"})
    assert source_coverage_audit_binding_block(summary, manifest, admission_mode="observation")
    with pytest.raises(ValueError):
        source_coverage_audit_has_unresolved(summary)


@pytest.mark.parametrize("mutation", [
    lambda decision, manifest: setattr(decision, "_source_coverage_audit", None),
    lambda decision, manifest: decision._source_coverage_audit["audit"].pop(),
    lambda decision, manifest: decision._source_coverage_audit.update(candidate_verification_sha256="0" * 64),
    lambda decision, manifest: manifest["source_coverage"]["inventory_input"].update(source_revision="another-revision"),
    lambda decision, manifest: manifest["candidates"].append({"candidate_index": 0, "statement": "Invented candidate."}),
])
def test_observation_does_not_hide_technical_or_candidate_binding_failures(mutation):
    decision, manifest, _summary = observation()
    mutation(decision, manifest)
    with pytest.raises(ValueError):
        get_source_coverage_audit_observation(decision, manifest)


class NegativeProvider(CoverageProvider):
    def __init__(self, *, fault=None, with_candidate=False, semantic_support=None):
        super().__init__(no_candidate=not with_candidate and fault != "selected_candidate")
        self.fault = fault
        self.with_candidate = with_candidate
        self.semantic_support = semantic_support

    def verify(self, manifest, **kwargs):
        result = super().verify(manifest, **kwargs)
        result.decision._source_coverage_audit["audit"][0]["verdict"] = "contradicted"
        if self.with_candidate:
            inventory = manifest["source_coverage"]["inventory"]
            extracts = {(window["w"], index) for window in inventory["windows"]
                        for index, span in enumerate(window["spans"]) if span["d"] == "extract"}
            for row in result.decision._source_coverage_audit["audit"]:
                if (row["w"], row["span_index"]) in extracts:
                    row["verdict"] = "unclear"
        if self.semantic_support:
            result.decision.points[0].semantic_support = self.semantic_support
            result.decision._source_coverage_audit["candidate_verification_sha256"] = _coverage_digest(
                result.decision.model_dump(mode="json"))
        if self.fault == "audit_binding":
            result.decision._source_coverage_audit["input_sha256"] = "0" * 64
        elif self.fault == "selected_candidate":
            result.decision.points[0].semantic_support = "partial"
        return result


def run_worker(coverage, provider, monkeypatch, *, allow_workspace=False):
    from harness_mem.autonomous import worker
    from harness_mem.commands import separated_assimilation
    from harness_mem.commands.dream_source_coverage import run_applied_source_coverage
    from harness_mem.core.schemas.dream_run import DreamRun
    backend, root, _job, _entry, item, checkpoint, notes = coverage
    carrier = DreamRun(id="original-run", project_name="demo", status="processing", continuation=checkpoint)
    asyncio.run(backend.structured_store.save_dream_run(carrier))

    async def forbidden_write(*args, **kwargs):
        raise AssertionError("Negative observations must not create or apply candidates.")

    if not allow_workspace:
        monkeypatch.setattr(worker, "create_separated_candidates", forbidden_write)
    monkeypatch.setattr(separated_assimilation, "apply_separated_assimilation", forbidden_write)

    async def persist():
        carrier.continuation = deepcopy(checkpoint)
        carrier.notes = list(notes)
        await backend.structured_store.save_dream_run(carrier)

    worked = asyncio.run(run_applied_source_coverage(backend, project_name="demo", project_root=root,
        run_id=carrier.id, checkpoint=checkpoint, notes=notes, items=[item], provider=provider, persist=persist))
    return worked, asyncio.run(backend.structured_store.get_dream_run(carrier.id)), notes


def test_real_zero_point_worker_persists_negative_observation_without_mutation(coverage, monkeypatch):
    backend, root, job, _entry, item, _checkpoint, _notes = coverage
    store = backend.structured_store.knowledge_store
    before = [entry.to_dict() for entry in asyncio.run(store.list_entries("demo", project_root=root))]
    job_before = job.to_dict()
    provider = NegativeProvider()
    worked, carrier, notes = run_worker(coverage, provider, monkeypatch)
    state = carrier.continuation["source_coverage"][item.source_id]
    assert worked and state["status"] == "unresolved"
    assert state["reason_code"] == "source_coverage_inventory_audit_unresolved"
    assert state["candidate_ids"] == []
    assert state["inventory_workspace"] == {"input_sha256": state["inventory_verification"]["input_sha256"], "workspace": []}
    assert state["inventory_verification"]["admission_mode"] == "observation"
    assert source_coverage_audit_has_unresolved(state["inventory_verification"]) is True
    assert provider.calls == ["decide", "candidate_verify"]
    receipts = [json.loads(note.split(": ", 1)[1]) for note in notes if note.startswith("dream source coverage receipt: ")]
    assert [receipt["phase"] for receipt in receipts] == ["decide", "candidate_verify"]
    assert sum(receipt["input_tokens"] for receipt in receipts) == 2
    assert sum(receipt["output_tokens"] for receipt in receipts) == 2
    assert [entry.to_dict() for entry in asyncio.run(store.list_entries("demo", project_root=root))] == before
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before


@pytest.mark.parametrize("semantic_support", [None, "partial", "contradicted"])
def test_nonzero_negative_audit_retains_real_blocked_workspace_and_no_truth(coverage, monkeypatch, semantic_support):
    from harness_mem.commands.separated_assimilation import prepare_separated_assimilation
    backend, root, _job, _entry, item, _checkpoint, _notes = coverage
    canonical = backend.structured_store._canonical
    before = {name: canonical.list_payloads(name) for name in ("knowledge_entries", "knowledge_sources", "task_handoffs")}
    provider = NegativeProvider(with_candidate=True, semantic_support=semantic_support)
    worked, carrier, _notes = run_worker(coverage, provider, monkeypatch, allow_workspace=True)
    state = carrier.continuation["source_coverage"][item.source_id]
    assert worked and state["status"] == "unresolved"
    assert state["reason_code"] == "source_coverage_inventory_audit_unresolved"
    assert len(state["candidate_ids"]) == 1
    assert state["inventory_verification"]["admission_mode"] == "observation"
    assert len(state["inventory_verification"]["extracted_point_sha256"]) == 1
    assert not state.get("commit_bindings") and not state.get("candidate_outcomes")
    store = backend.structured_store.knowledge_store
    candidate = asyncio.run(store.get_candidate(state["candidate_ids"][0]))
    evidence = asyncio.run(store.list_evidence(candidate.id))
    assert candidate.status == "pending" and candidate.assimilation_disposition is None
    assert candidate.candidate_type == "memory" and "acceptance rituals" in candidate.statement
    assert len(evidence) == 1 and evidence[0].distill_job_id == _job.id
    assert evidence[0].verification_outcome == "unverified"
    assert evidence[0].evidence_basis == "user_statement" and evidence[0].verification_refs
    expected_point = "verified" if semantic_support is None else "unverified" if semantic_support == "partial" else "contradicted"
    assert "source_coverage_point_verification_" + expected_point in evidence[0].verification_reason_codes
    assert state["inventory_workspace"]["workspace"] == [{"id": candidate.id,
        "candidate_sha256": _coverage_digest(candidate.to_dict()),
        "evidence_sha256": _coverage_digest(evidence[0].to_dict())}]
    for name, rows in before.items():
        assert canonical.list_payloads(name) == rows
    assert provider.calls == ["decide", "candidate_verify"]
    # The ordinary source owner also cannot promote this held proposal.
    ordinary = asyncio.run(prepare_separated_assimilation(backend, project_name="demo", project_root=str(root),
        candidate_ids=[candidate.id]))
    assert ordinary.eligible_candidate_ids == ()
    assert ordinary.answer_status_by_candidate[candidate.id] != "ANSWERED"


def test_nonzero_technical_audit_error_creates_no_workspace_or_observation(coverage, monkeypatch):
    backend, _root, _job, _entry, item, _checkpoint, _notes = coverage
    store = backend.structured_store.knowledge_store
    before = [candidate.to_dict() for candidate in asyncio.run(store.list_candidates("demo"))]
    _worked, carrier, _notes = run_worker(coverage, NegativeProvider(fault="audit_binding", with_candidate=True),
        monkeypatch, allow_workspace=True)
    state = carrier.continuation["source_coverage"][item.source_id]
    assert state["status"] == "failed" and not state.get("candidate_ids")
    assert "inventory_verification" not in state and "inventory_workspace" not in state
    assert [candidate.to_dict() for candidate in asyncio.run(store.list_candidates("demo"))] == before


@pytest.mark.parametrize("fault", ["audit_binding", "selected_candidate"])
def test_worker_keeps_binding_and_selected_candidate_failures_rejected(coverage, monkeypatch, fault):
    _backend, _root, _job, _entry, item, _checkpoint, _notes = coverage
    _worked, carrier, _notes = run_worker(coverage, NegativeProvider(fault=fault), monkeypatch)
    state = carrier.continuation["source_coverage"][item.source_id]
    assert state["status"] == "failed"
    assert "inventory_verification" not in state
    assert state["candidate_ids"] == []
