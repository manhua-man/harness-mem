"""Recovered commits preserve the independently bound incomplete inventory."""
from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from harness_mem.autonomous.models import NativeSourceCoverageVerificationDecision
from harness_mem.autonomous.provider import (
    _coverage_digest,
    expand_source_coverage_verification_decision,
    get_source_coverage_audit_binding,
)
from harness_mem.commands import dream_source_coverage as owner
from test_source_coverage_inventory_transport import fixture, verification


def audit_binding(*, partial=False, selected=False, verdict="unclear"):
    manifest, extraction = fixture()
    _decision, verify, native = verification(manifest, extraction)
    if partial:
        native["audit"][1]["verdict"] = verdict
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify)
    return get_source_coverage_audit_binding(decision, verify,
        admission_mode="selected_points" if selected else "full_inventory")


def recovery(monkeypatch, binding=None):
    entry = NS(id="truth", title="Scoped requirement", statement="Keep the original task limits.",
               module_path=["repair"])
    candidate = NS(status="assimilated", to_dict=lambda: {"id": "candidate", "status": "assimilated"})

    async def current_change_committed(identity):
        assert identity == "actual-transaction"
        return True

    async def get_entry(identity, **_scope):
        assert identity == "truth"
        return entry

    async def get_candidate(identity):
        assert identity == "candidate"
        return candidate

    async def ordinary_search_readback(*_args, **kwargs):
        assert kwargs["added_entries"] == [entry]

    monkeypatch.setattr("harness_mem.commands.knowledge_assimilation._verify_normal_search_after_truth_write",
                        ordinary_search_readback)
    backend = NS(structured_store=NS(knowledge_store=NS(
        current_change_committed=current_change_committed, get_entry=get_entry, get_candidate=get_candidate)))
    state = dict(status="committing", candidate_ids=["candidate"], commit_bindings=[dict(
        decision_id="actual-transaction", candidate_id="candidate", truth_ids=["truth"],
        truth_sha256=[owner._digest(dict(title=entry.title, statement=entry.statement, topic_path=entry.module_path))],
        predecessor_ids=[], status="committing")], candidate_outcomes=[dict(
            candidate_id="candidate", disposition="add", status="planned_add", truth_ids=["truth"])])
    if binding is not None:
        state["inventory_verification"] = binding
    return backend, state


@pytest.mark.parametrize("mode", ["legacy", "strict", "selected_complete", "selected_partial", "selected_contradicted"])
def test_actual_recovered_write_does_not_claim_unclear_inventory_complete(monkeypatch, tmp_path, mode):
    binding = None if mode == "legacy" else audit_binding(
        partial=mode in {"selected_partial", "selected_contradicted"}, selected=mode.startswith("selected"),
        verdict="contradicted" if mode == "selected_contradicted" else "unclear")
    backend, state = recovery(monkeypatch, binding)
    assert asyncio.run(owner._recover_committed(backend, state, project_name="demo", project_root=tmp_path))
    assert state["committed_candidate_ids"] == ["candidate"]
    assert state["result_status_counts"]["promoted"] == 1
    assert state["commit_bindings"][0]["status"] == "applied"
    if mode in {"selected_partial", "selected_contradicted"}:
        assert state["status"] == "unresolved"
        assert state["reason_code"] == "source_coverage_inventory_audit_unresolved"
        assert state["inventory_verification"]["audit"][1]["verdict"] == ("contradicted" if mode == "selected_contradicted" else "unclear")
    else:
        assert state["status"] == "applied"
    # Repeated bookkeeping neither replays the transaction nor upgrades partial coverage.
    original = copy.deepcopy(state)
    assert asyncio.run(owner._recover_committed(backend, state, project_name="demo", project_root=tmp_path))
    assert state == original


@pytest.mark.parametrize("fault", ["summary_hash", "audit_hash", "mode", "missing_span"])
def test_invalid_inventory_cannot_upgrade_a_recovered_write(monkeypatch, tmp_path, fault):
    binding = audit_binding(partial=True, selected=True)
    if fault == "summary_hash":
        binding["summary_sha256"] = "0" * 64
    else:
        if fault == "audit_hash":
            binding["audit_binding_sha256"] = "0" * 64
        elif fault == "mode":
            binding["admission_mode"] = "invented"
        else:
            binding["audit"].pop()
        binding["summary_sha256"] = _coverage_digest({k: v for k, v in binding.items() if k != "summary_sha256"})
    backend, state = recovery(monkeypatch, binding)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        asyncio.run(owner._recover_committed(backend, state, project_name="demo", project_root=tmp_path))
    assert state == before
