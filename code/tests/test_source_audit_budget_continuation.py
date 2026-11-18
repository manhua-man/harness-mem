"""Budget-refused source work resumes from exact isolated receipts, never proposals as writes."""
import hashlib
import json

import pytest

from test_residual_source_audit import captured as captured, coverage as coverage, terminal as terminal
from test_residual_source_audit import residual as residual, audit_child, run, seal_audit
from test_task_budget_allowance_grant import AUTH
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, TaskBudgetRefusal, dispatch_with_task_budget, grant_maintenance_allowance,
    read_task_budget_receipt, task_budget_observation, task_budget_receipt_path,
)
from harness_mem.commands import dream_source_audit as owner
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEvidence


@pytest.fixture
def budget_failed(residual):
    data = residual
    child, frozen, state = audit_child(data)
    prepared, _item, _rows = run(owner._prepared(data["backend"], origin=data["origin"], frozen=data["frozen"],
        key=data["key"], project_name="demo", project_root=data["root"], run_id=child.id))
    compared = {row["id"]: row for row in [*prepared["successors"], *prepared["comparison_current_truth"]]}
    source = {"contract": "source-coverage-inventory-v1",
        **{name: prepared["binding"][name] for name in ("source_id", "source_revision", "context_sha256")},
        "windows": [{**{k: v for k, v in row.items() if k != "anchor_sha256"},
                     "exchange_sha256": row["anchor_sha256"]} for row in prepared["authored_user_exchanges"]],
        "current": [compared[key] for key in sorted(compared)]}
    candidate = KnowledgeCandidate(id="budget-pending", project_name="demo", candidate_type="memory",
        statement="Preserve the exact same task scope during the remaining repair.")
    exchange = source["windows"][1]["exchange_index"]
    evidence = KnowledgeEvidence(id="budget-evidence", project_name="demo", candidate_id=candidate.id,
        distill_job_id=prepared["job"].id, evidence_basis="user_statement", verification_outcome="verified",
        verification_refs=[{"kind": "user_statement", "role": "user", "exchange_index": exchange,
                            "content_sha256": source["windows"][1]["exchange_sha256"]}])
    store = data["backend"].structured_store.knowledge_store
    run(store.save_candidate(candidate))
    run(store.save_evidence(evidence))
    audit = state["inventory_verification"]
    audit["input_sha256"] = owner._digest(source)
    audit["extracted_point_sha256"] = [owner._digest({"statement": candidate.statement})]
    audit["windows"][1]["spans"][0].update(d="extract", p=[0], c=[], r=[])
    for vote in audit["audit"]:
        vote["verdict"] = "unclear" if vote["w"] == 3 else "supported"
    seal_audit(audit)
    state.update(status="failed", reason_code="input_budget_exhausted", candidate_ids=[candidate.id],
        candidate_status_counts={"pending": 1}, result_status_counts={}, point_disposition_counts={},
        candidate_outcomes=[{"candidate_id": candidate.id, "status": "pending",
                             "candidate_sha256": owner._digest(candidate.to_dict())}],
        inventory_workspace={"input_sha256": audit["input_sha256"], "workspace": [{"id": candidate.id,
            "candidate_sha256": owner._digest(candidate.to_dict()), "evidence_sha256": owner._digest(evidence.to_dict())}]})
    binding = data["binding"]
    account_path = task_budget_receipt_path(data["backend"].data_dir, binding.task_scope)
    account = read_task_budget_receipt(data["backend"].data_dir, binding.task_scope)
    used = sum(call["usage"]["input_tokens"] for call in account["calls"])
    amounts = [1, 1, account["bounds"]["max_input_tokens"] - used - 1]
    prefix = f"source-coverage:{child.id}:{state['binding_sha256']}:"
    receipts = []
    for phase, suffix, amount in zip(("decide", "candidate_verify", "assimilate"),
            ("source-decide:" + prepared["job"].id, "source-verify", "source-assimilate"), amounts):
        dispatch_with_task_budget(binding, phase="dream", slice_id=prefix + suffix, timeout_seconds=1,
            transport=lambda _request, value=amount: NativeDispatchResult(status="completed",
                input_tokens=value, output_tokens=1, duration_seconds=.01, usage_exact=True))
        receipt = {"attempt_id": state["binding_sha256"], "phase": phase, "host_client": "codex",
            "source_job_id": prepared["job"].id, "schema_valid": True, "input_sha256": "a" * 64,
            "response_sha256": "b" * 64, "input_tokens": amount, "output_tokens": 1, "duration_seconds": .01,
            "native_attempts": [{"status": "completed", "terminal": "completed", "model_dispatched": True,
                "input_sha256": "a" * 64, "response_text_sha256": "b" * 64, "unknown_response_usage_count": 0}]}
        if phase == "candidate_verify":
            receipt["verification_points"] = [{"candidate_index": 0, "semantic_support": "supported",
                "future_scope": "durable", "scope_text_sha256": hashlib.sha256(candidate.statement.encode()).hexdigest()}]
        receipts.append(receipt)
    with pytest.raises(TaskBudgetRefusal) as failure:
        dispatch_with_task_budget(binding, phase="dream", slice_id=prefix + "source-final-scope", timeout_seconds=1,
            transport=lambda _request: pytest.fail("pre-dispatch refusal must not reach transport"))
    assert failure.value.code == "input_budget_exhausted"
    maintenance = child.continuation["maintenance_scope"]
    snapshot = task_budget_observation(data["backend"].data_dir, **maintenance)
    snapshot.update(native_dispatch="refused_before_transport", dispatch_failure_reason=failure.value.code)
    child.notes = ["dream source coverage receipt: " + json.dumps(row) for row in receipts]
    child.continuation.update(failure_reason=failure.value.code, task_budget=snapshot,
        source_coverage_failure={"failure_reason": failure.value.code, "kind": "unrecoverable", "bookkeeping_failure": None})
    run(data["backend"].structured_store.save_dream_run(child))
    grant_maintenance_allowance(binding, grant_id="budget-continuation-fixture",
        expected_receipt_sha256=hashlib.sha256(account_path.read_bytes()).hexdigest(),
        additional_bounds={"max_input_tokens": 1000}, authorization=AUTH)
    return {**data, "child": child, "child_frozen": frozen, "child_state": state, "held_candidate": candidate,
            "held_evidence": evidence, "account_path": account_path}


def prepare(data):
    return run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
        run_id="budget-child", origin_run_id=data["child"].id, predecessor_ids=[data["key"]]))


def persist_child(data):
    run(data["backend"].structured_store.save_dream_run(data["child"]))


def test_closed_budget_refusal_reopens_pending_extract_without_commit_handoff_or_mutation(budget_failed, monkeypatch):
    data = budget_failed
    backend = data["backend"]
    canonical = backend.structured_store._canonical
    before = {name: canonical.list_payloads(name) for name in ("knowledge_entries", "knowledge_sources", "dream_runs", "task_handoffs")}
    account_before = data["account_path"].read_bytes()
    manifest = prepare(data)
    prepared, _item, _rows = run(owner._prepared(backend, origin=data["child"], frozen=data["child_frozen"], key=data["key"],
        project_name="demo", project_root=data["root"], run_id="budget-child"))
    repair = prepared["inventory_audit_repair"]
    assert {row["w"] for row in repair["pending_spans"]} == {1, 3}
    assert len(repair["retained_spans"]) == len(prepared["authored_user_exchanges"]) - 2
    assert repair["committed_candidate_bindings"] == repair["committed_point_spans"] == []
    assert repair["deferred_workspace_bindings"] == [] and "resolved_handoff_proof" not in repair
    assert repair["budget_interrupted_candidate_bindings"][0]["candidate_id"] == data["held_candidate"].id
    assert repair["budget_interrupted_candidate_bindings"][0]["admission"] == "blocked_budget_interruption"
    assert manifest["task_scope"] == data["binding"].task_scope
    assert data["account_path"].read_bytes() == account_before
    for name, payloads in before.items():
        assert canonical.list_payloads(name) == payloads
    assert run(backend.structured_store.knowledge_store.get_candidate(data["held_candidate"].id)).to_dict() == data["held_candidate"].to_dict()
    seen = []
    def before_native(_provider, **kwargs):
        from harness_mem.autonomous.provider import _residual_inventory_basis
        native = kwargs["manifest"]
        basis = _residual_inventory_basis(native)
        assert (1, 0) in basis["pending"] and (1, 0) not in basis["retained"]
        assert native["source_coverage"]["inventory_audit_repair"]["budget_interrupted_candidate_bindings"]
        assert native.get("candidates", []) == []
        seen.append(native)
        raise ValueError("fixture_stop_before_fresh_extraction")
    monkeypatch.setattr("harness_mem.autonomous.worker._decide_with_candidate_retry", before_native)
    async def save():
        pass
    result = run(owner.run_explicit_source_audit(backend, project_name="demo", project_root=data["root"], run_id="budget-child",
        manifest=manifest, checkpoint={}, notes=[], provider=data["provider"], persist=save))
    assert result["status"] == "unresolved" and len(seen) == 1 and data["provider"].calls == []
    assert data["account_path"].read_bytes() == account_before


@pytest.mark.parametrize("fault", ["failure", "dispatch", "unknown_snapshot", "snapshot_call", "unknown_account", "active_account",
    "account_host", "allowance", "candidate", "evidence", "unverified", "source", "partial_commit", "handoff",
    "native_receipt", "native_hash", "native_point", "inventory_hash", "workspace_hash"])
def test_budget_continuation_refuses_unproved_or_changed_state(budget_failed, monkeypatch, fault):
    data = budget_failed
    continuation, state = data["child"].continuation, data["child_state"]
    store = data["backend"].structured_store.knowledge_store
    if fault in {"unknown_account", "active_account", "account_host", "allowance"}:
        account = json.loads(data["account_path"].read_text())
        if fault == "unknown_account":
            account["calls"][-1]["usage_exact"] = False
        elif fault == "active_account":
            account["calls"][-1]["status"] = "reserved"
        elif fault == "account_host":
            account["host_client"] = "hermes"
        else:
            account["allowance_grants"] = []
        data["account_path"].write_text(json.dumps(account))
    elif fault == "failure":
        continuation.pop("source_coverage_failure")
    elif fault == "dispatch":
        continuation["task_budget"]["native_dispatch"] = "ledger_present"
    elif fault == "unknown_snapshot":
        continuation["task_budget"]["unknown_calls"] = 1
    elif fault == "snapshot_call":
        continuation["task_budget"]["known_usage"][-1]["usage"]["input_tokens"] += 1
    elif fault == "candidate":
        run(store.save_candidate(data["held_candidate"].model_copy(update={"statement": "Changed pending content."})))
    elif fault in {"evidence", "unverified"}:
        change = {"verification_outcome": "unverified"} if fault == "unverified" else {"verification_reason_codes": ["changed"]}
        run(store.save_evidence(data["held_evidence"].model_copy(update=change)))
    elif fault == "source":
        ledger = data["backend"].transcript_store
        original = ledger.reconstruct_raw
        monkeypatch.setattr(ledger, "reconstruct_raw", lambda *args, **kwargs: original(*args, **kwargs) + b"changed")
    elif fault == "partial_commit":
        state["commit_bindings"] = [{"candidate_id": data["held_candidate"].id, "status": "applied"}]
    elif fault == "handoff":
        state["candidate_outcomes"][0].update(disposition="handoff", handoff_id="not-a-commit")
    elif fault.startswith("native_"):
        row = json.loads(data["child"].notes[1].split(": ", 1)[1])
        if fault == "native_receipt":
            row["native_attempts"][0]["unknown_response_usage_count"] = 1
        elif fault == "native_hash":
            row["input_sha256"] = "bad"
        else:
            row["verification_points"][0]["scope_text_sha256"] = "f" * 64
        data["child"].notes[1] = "dream source coverage receipt: " + json.dumps(row)
    elif fault == "inventory_hash":
        state["inventory_verification"]["summary_sha256"] = "f" * 64
    else:
        state["inventory_workspace"]["workspace"][0]["candidate_sha256"] = "f" * 64
    persist_child(data)
    with pytest.raises((ValueError, TaskBudgetRefusal)):
        prepare(data)
    assert data["provider"].calls == []


def test_budget_child_rejects_different_provider_account_before_native(budget_failed):
    data = budget_failed
    manifest = prepare(data)
    data["provider"].task_budget_binding = data["other_binding"]
    async def save():
        pass
    with pytest.raises(ValueError, match="same_account_required"):
        run(owner.run_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"], run_id="budget-child",
            manifest=manifest, checkpoint={}, notes=[], provider=data["provider"], persist=save))
    assert data["provider"].calls == []


def add_predispatch_ticket(data, **changes):
    state = data["child_state"]
    ticket = {"attempt_id": state["binding_sha256"], "phase": "provider_failure",
        "source_job_id": state["binding"]["source_job_id"], "failure_kind": "unrecoverable",
        "failure_reason": "input_budget_exhausted", "exit_code": None, "budget_call_id": None,
        "attempt_results": [], "native_attempts": [], "unknown_attempt_count": 0, **changes}
    data["child"].notes.append("dream source coverage receipt: " + json.dumps(ticket))
    persist_child(data)
    return ticket


@pytest.mark.parametrize("mirror", [False, True])
def test_repaired_predispatch_failure_ticket_keeps_three_paid_calls_and_all_workspace(budget_failed, monkeypatch, mirror):
    data = budget_failed
    ticket = add_predispatch_ticket(data)
    if mirror:
        data["child"].continuation["terminal_coverage_receipts"] = [data["child"].notes[-1]]
        persist_child(data)
    original = data["backend"].structured_store._canonical.get_payload_json("dream_runs", data["child"].id)
    account = data["account_path"].read_bytes()
    test_closed_budget_refusal_reopens_pending_extract_without_commit_handoff_or_mutation(data, monkeypatch)
    assert data["backend"].structured_store._canonical.get_payload_json("dream_runs", data["child"].id) == original
    assert data["account_path"].read_bytes() == account and ticket["budget_call_id"] is None


@pytest.mark.parametrize("fault", ["paid_id", "attempt_results", "native_attempts", "unknown", "different_reason",
                                   "different_job", "different_binding", "exit_code", "kind", "missing", "conflict"])
def test_predispatch_ticket_cannot_hide_real_attempts_or_foreign_binding(budget_failed, fault):
    data = budget_failed
    changes = {"paid_id": {"budget_call_id": "previous-successful-paid-call"},
        "attempt_results": {"attempt_results": [{"status": "completed"}]},
        "native_attempts": {"native_attempts": [{"status": "completed"}]},
        "unknown": {"unknown_attempt_count": 1}, "different_reason": {"failure_reason": "output_budget_exhausted"},
        "different_job": {"source_job_id": "another-job"}, "different_binding": {"attempt_id": "another-attempt"},
        "exit_code": {"exit_code": 0}, "kind": {"failure_kind": "transient"}}
    ticket = add_predispatch_ticket(data, **changes.get(fault, {}))
    if fault == "missing":
        ticket.pop("native_attempts")
        data["child"].notes[-1] = "dream source coverage receipt: " + json.dumps(ticket)
        persist_child(data)
    elif fault == "conflict":
        add_predispatch_ticket(data, budget_call_id="previous-successful-paid-call")
    with pytest.raises(ValueError, match="budget_refusal_receipt_"):
        prepare(data)
    assert data["provider"].calls == []
