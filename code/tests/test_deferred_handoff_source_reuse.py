"""A real deferred-final annotation never grants source coverage by itself."""
import json
from datetime import timedelta

import pytest

from harness_mem.commands import dream_source_audit as owner
from harness_mem.core.schemas.knowledge import AssimilationDecision
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.knowledge_job_workspace import KnowledgeJobWorkspace
from test_residual_source_audit import (
    captured as captured,
    coverage as coverage,
    no_write_child,
    recovery_child,
    residual as residual,
    run,
    terminal as terminal,
)

CODE = "final_source_scope_partition_missing"
REASON = "Final knowledge scope verification deferred this complete point: " + CODE + "."


def deferred_child(data, monkeypatch, *, writing=False, annotation=True):
    values = recovery_child(data, monkeypatch) if writing else no_write_child(data, monkeypatch)
    child, frozen, state, proof = values[:4]
    store = data["backend"].structured_store.knowledge_store
    outcome = state["candidate_outcomes"][0]
    outcome.update(disposition="defer", status="deferred", result_sha256="a" * 64)
    state.update(plan_sha256="b" * 64, result_sha256="c" * 64)
    final = {"phase": "final_scope", "attempt_id": state["binding_sha256"],
        "source_job_id": state["binding"]["source_job_id"], "schema_valid": True,
        "verification_points": [{"candidate_index": 0, "semantic_support": "partial",
            "future_scope": "unclear", "source_use": "unclear", "scope_text_sha256": owner._raw_digest(""),
            "scope_segments": [], "update_meaning": None}]}
    child.notes = [*(child.notes or []), "dream source coverage receipt: " + json.dumps(final)]
    candidate = run(store.get_candidate(outcome["candidate_id"]))
    candidate.status = "deferred"
    run(store.save_candidate(candidate))
    evidence = run(store.list_evidence(candidate.id))[0]
    if annotation:
        evidence.verification_reason_codes.append(CODE)
    run(store.save_evidence(evidence))
    original = proof["resolved"][0]["original_binding"]
    original["candidate_sha256"] = owner._digest(candidate.to_dict())
    original["evidence_sha256"] = owner._digest([evidence.to_dict()])
    original["original_point_sha256"] = owner._digest({"point": outcome,
        "mode": "inventory_workspace", "state_sha256": owner._digest(state)})
    run(data["backend"].structured_store.save_dream_run(child))
    decision = AssimilationDecision(id="original-rejection", project_name="demo", candidate_id=candidate.id,
                                    disposition="defer", reason=REASON)
    run(store.save_decision(decision))
    handoff = run(data["backend"].structured_store.get_task_handoff(outcome["handoff_id"]))
    if handoff is None:
        handoff = TaskHandoff(id=outcome["handoff_id"], project_name="demo", task_id="assimilation:source-point",
                              summary="The original final proof was rejected.", status="done")
    handoff.context.update(candidate_id=candidate.id, distill_job_id=state["binding"]["source_job_id"])
    handoff.next_steps = [REASON]
    run(data["backend"].structured_store.save_task_handoff(handoff))
    return child, frozen, state, proof, decision


def prepare(data, child):
    return run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[data["key"]], resolved_handoff_run_id="canonical-recovery"))


@pytest.mark.parametrize("writing", [False, True])
@pytest.mark.parametrize("annotation", [False, True])
def test_proven_deferred_handoff_reuses_common_no_write_or_actual_commit(residual, monkeypatch, writing, annotation):
    child, frozen, _state, _proof, decision = deferred_child(residual, monkeypatch, writing=writing, annotation=annotation)
    backend = residual["backend"]
    before = backend.structured_store._canonical.get_payload_json("dream_runs", child.id)
    evidence_before = [e.to_dict() for e in run(backend.structured_store.knowledge_store.list_evidence("source-point"))]
    prepare(residual, child)
    prepared, _, _ = run(owner._prepared(backend, origin=child, frozen=frozen, key=residual["key"],
        project_name="demo", project_root=residual["root"], run_id="grandchild",
        resolved_handoff_run_id="canonical-recovery"))
    repair = prepared["inventory_audit_repair"]
    if writing:
        assert repair["committed_point_spans"][0]["candidate_ids"] == ["source-point"]
        binding = repair["committed_candidate_bindings"][0]
    else:
        assert repair["committed_candidate_bindings"] == []
        binding = repair["resolved_no_write_points"][0]
        assert binding["coverage_authority"] is False
        assert {s["w"] for s in repair["pending_spans"]} == {0, 1, 4}
    if annotation:
        assert binding["source_evidence_reopen"]["decision_sha256"] == owner._digest(decision.to_dict())
    else:
        assert "source_evidence_reopen" not in binding
    assert backend.structured_store._canonical.get_payload_json("dream_runs", child.id) == before
    assert [e.to_dict() for e in run(backend.structured_store.knowledge_store.list_evidence("source-point"))] == evidence_before
    assert residual["provider"].calls == []


@pytest.mark.parametrize("fault", ["missing_handoff", "wrong_original", "state", "evidence",
    "unknown_reason", "decision_reason", "decision_workspace", "missing_decision", "handoff_job",
    "handoff_candidate", "handoff_reason", "writing_pending", "unknown_account", "missing_commit",
    "final_missing", "final_wrong_attempt", "final_positive", "final_job", "missing_plan_hash", "original_pending"])
def test_deferred_reuse_keeps_exact_binding_guards(residual, monkeypatch, fault):
    child, _frozen, state, proof, decision = deferred_child(residual, monkeypatch, writing=fault == "missing_commit")
    backend = residual["backend"]
    store = backend.structured_store.knowledge_store
    if fault in {"missing_handoff", "handoff_job", "handoff_candidate", "handoff_reason"}:
        handoff = run(backend.structured_store.get_task_handoff("actual-original-handoff"))
        if fault == "missing_handoff":
            handoff.status = "in_progress"
        elif fault == "handoff_reason":
            handoff.next_steps = []
        else:
            handoff.context["distill_job_id" if fault == "handoff_job" else "candidate_id"] = "foreign"
        run(backend.structured_store.save_task_handoff(handoff))
    elif fault == "wrong_original":
        proof["resolved"][0]["original_binding"]["original_point_sha256"] = "f" * 64
    elif fault == "state":
        state["candidate_outcomes"][0]["status"] = "pending"
        run(backend.structured_store.save_dream_run(child))
    elif fault in {"evidence", "unknown_reason"}:
        evidence = run(store.list_evidence("source-point"))[0]
        if fault == "unknown_reason":
            evidence.verification_reason_codes.insert(0, "unproved_new_source_judgment")
        else:
            evidence.created_at += timedelta(days=1)
        run(store.save_evidence(evidence))
        proof["resolved"][0]["original_binding"]["evidence_sha256"] = owner._digest([evidence.to_dict()])
    elif fault in {"decision_reason", "decision_workspace", "missing_decision"}:
        path = KnowledgeJobWorkspace(backend.data_dir)._decision_path(decision.id)
        if fault == "missing_decision":
            path.unlink()
        else:
            wrapper = json.loads(path.read_text())
            if fault == "decision_reason":
                wrapper["data"]["reason"] = "A different rejection."
            else:
                wrapper["workspace_id"] = "foreign-job"
            path.write_text(json.dumps(wrapper))
    elif fault == "writing_pending":
        candidate = run(store.get_candidate("recovery-writing-point"))
        candidate.status = "pending"
        run(store.save_candidate(candidate))
    elif fault == "original_pending":
        candidate = run(store.get_candidate("source-point"))
        candidate.status = "pending"
        run(store.save_candidate(candidate))
    elif fault.startswith("final_"):
        prefix = "dream source coverage receipt: "
        final = json.loads(child.notes[-1][len(prefix):])
        if fault == "final_missing":
            child.notes.pop()
        else:
            if fault == "final_wrong_attempt":
                final["attempt_id"] = "foreign"
            elif fault == "final_job":
                final["source_job_id"] = "foreign"
            else:
                final["verification_points"][0]["semantic_support"] = "supported"
            child.notes[-1] = prefix + json.dumps(final)
        run(backend.structured_store.save_dream_run(child))
    elif fault == "missing_plan_hash":
        state.pop("plan_sha256")
        # Keep the original-state digest consistent to exercise the new gate.
        proof["resolved"][0]["original_binding"]["original_point_sha256"] = owner._digest({
            "point": state["candidate_outcomes"][0], "mode": "inventory_workspace", "state_sha256": owner._digest(state)})
        run(backend.structured_store.save_dream_run(child))
    elif fault == "unknown_account":
        from harness_mem.autonomous.executors.task_budget import task_budget_receipt_path
        path = task_budget_receipt_path(backend.data_dir, frozen_scope(child))
        account = json.loads(path.read_text())
        account["calls"][0]["usage_exact"] = False
        path.write_text(json.dumps(account))
    else:
        proof["resolved"][0]["commit_bindings"] = []
    with pytest.raises(ValueError):
        prepare(residual, child)
    assert residual["provider"].calls == []


def frozen_scope(child):
    return child.continuation["explicit_repair_scope"]["source"]["task_scope"]
