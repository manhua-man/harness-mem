"""Residual source recovery uses isolated ledger fixtures and fake transports."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal
from harness_mem.commands import dream_source_audit as owner
from harness_mem.commands import dream_source_coverage as original
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt, task_budget_receipt_path
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.knowledge import KnowledgeCandidate, KnowledgeEvidence
from harness_mem.core.schemas.task_handoff import TaskHandoff


def run(value):
    return asyncio.run(value)


def seal_audit(audit):
    digest = owner._digest
    audit["inventory_sha256"] = digest({k: audit[k] for k in (
        "input_sha256", "candidate_output_sha256", "windows")})
    audit["audit_binding_sha256"] = digest({k: audit[k] for k in (
        "input_sha256", "inventory_sha256", "candidate_output_sha256", "verification_rows_sha256",
        "candidate_verification_sha256", "audit")})
    audit["summary_sha256"] = digest({k: v for k, v in audit.items() if k != "summary_sha256"})


def save_origin(data):
    backend = data["backend"]
    failed = data["origin"]
    failed.continuation["repair_source_coverage"]["manifest_sha256"] = owner._digest(
        failed.continuation["explicit_repair_scope"]["source"])
    run(backend.structured_store.save_dream_run(failed))


@pytest.fixture
def residual(terminal):
    backend, root, old, _carrier, _job, provider, _config, bindings = terminal
    item = old.items[0]
    prepared = run(original._prepare(backend, project_name="demo", project_root=root,
        run_id="failed-audit", item=item, checkpoint=old.continuation, notes=old.notes,
        include_current_comparison=True))
    store = backend.structured_store.knowledge_store
    point = KnowledgeCandidate(id="fixture", project_name="demo", candidate_type="rule",
                               statement="Preserve explicit corrections during this repair.")
    run(store.save_candidate(point))
    exchange = prepared["authored_user_exchanges"][2]["exchange_index"]
    anchor = next(row["content_sha256"] for row in prepared["packet"]["semantic_decision_exchanges"]
                  if row["exchange_index"] == exchange)
    point_evidence = KnowledgeEvidence(id="fixture-evidence", project_name="demo", candidate_id=point.id,
        distill_job_id=prepared["job"].id, evidence_basis="user_statement", verification_outcome="verified",
        verification_refs=[{"kind": "user_statement", "role": "user", "exchange_index": exchange,
                            "content_sha256": anchor}])
    run(store.save_evidence(point_evidence))
    run(store.save_candidate(point.model_copy(update={"status": "assimilated"})))
    snapshots, _entries = run(original._explicit_current_rows(backend, prepared,
        project_name="demo", project_root=root))
    snapshots["retired-neighbor"] = {"payload_sha256": "c" * 64,
                                    "scope_sha256": "d" * 64, "sources_sha256": "e" * 64}
    windows = []
    for w, row in enumerate(prepared["authored_user_exchanges"]):
        span = {"s": 0, "e": len(row["text"]), "d": "temporary", "p": [], "c": [], "r": []}
        if w == 0:
            span.update(d="covered", c=[0])
        elif w == 1:
            span.update(d="unclear")
        elif w == 2:
            span.update(d="extract", p=[0])
        elif w == 3:
            span.update(d="covered", c=[1])
        windows.append({"w": w, "spans": [span]})
    audit = {"input_sha256": "a" * 64, "candidate_output_sha256": "b" * 64,
             "verification_rows_sha256": "c" * 64, "candidate_verification_sha256": "d" * 64,
             "windows": windows, "extracted_point_sha256": ["e" * 64], "admission_mode": "selected_points",
             "audit": [{"w": w, "span_index": 0, "verdict": "unclear" if w == 1 else "supported"}
                       for w in range(len(windows))]}
    seal_audit(audit)
    entry = prepared["successor_entries"][0]
    state = {"status": "unresolved", "reason_code": "source_coverage_inventory_audit_unresolved",
             "binding": prepared["binding"], "binding_sha256": owner._digest(prepared["binding"]),
             "candidate_ids": ["fixture"], "committed_candidate_ids": ["fixture"],
             "inventory_verification": audit,
             "inventory_workspace": {"input_sha256": audit["input_sha256"], "workspace": [
                 {"id": "fixture", "candidate_sha256": owner._digest(point.to_dict()),
                  "evidence_sha256": owner._digest(point_evidence.to_dict())}]},
             "commit_bindings": [{"candidate_id": "fixture", "status": "applied",
                 "decision_id": "fixture-publish", "truth_ids": [entry.id], "predecessor_ids": [],
                 "truth_sha256": [owner._digest({"title": entry.title, "statement": entry.statement,
                                                 "topic_path": entry.module_path})]}],
             "candidate_outcomes": [{"candidate_id": "fixture", "disposition": "add",
                 "status": "assimilated", "truth_ids": [entry.id]}]}
    frozen = {"contract": original.EXPLICIT_REPAIR_CONTRACT, "project_name": "demo",
              "project_root_sha256": owner._digest(str(root.resolve())), "run_id": "failed-audit",
              "host_client": "codex", "source_bindings": {item.source_id: {
                  "binding": prepared["binding"], "current_rows": snapshots}}}
    origin = DreamRun(id="failed-audit", project_name="demo", status="failed", trigger_source="agent",
        completed_at=datetime.now(timezone.utc), execution_status="completed", resolution_status="unresolved",
        notes=[], continuation={"maintenance_scope": dict(_carrier.continuation["maintenance_scope"]),
            "explicit_repair_scope": {"source": frozen}, "repair_source_coverage": {
            "contract": original.EXPLICIT_REPAIR_CONTRACT, "manifest_sha256": owner._digest(frozen),
            "task_scope": bindings[1].task_scope, "source_coverage": {item.source_id: state}}})
    data = {"backend": backend, "root": root, "origin": origin, "key": item.source_id,
            "state": state, "frozen": frozen, "provider": provider, "binding": bindings[1],
            "other_binding": bindings[0], "prepared": prepared, "checkpoint": {"slice_count": 1}}
    save_origin(data)
    return data


def prepare(data):
    return run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="residual-run", origin_run_id=data["origin"].id,
        predecessor_ids=[data["key"]]))


def invoke(data, manifest, *, boundary=None):
    async def persist():
        data["checkpoint"]["persist_count"] = data["checkpoint"].get("persist_count", 0) + 1
    return run(owner.run_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="residual-run", manifest=manifest,
        checkpoint=data["checkpoint"], notes=[], provider=data["provider"], persist=persist, boundary=boundary))


def test_prepare_reopens_original_source_and_computes_only_changed_positions(residual):
    before = residual["backend"].structured_store._canonical.get_payload_json("dream_runs", "failed-audit")
    manifest = prepare(residual)
    prepared, _item, _snapshots = run(owner._prepared(residual["backend"], origin=residual["origin"],
        frozen=residual["frozen"], key=residual["key"], project_name="demo",
        project_root=residual["root"], run_id="residual-run"))
    metadata = prepared["inventory_audit_repair"]
    assert manifest["contract"] == owner.CONTRACT
    assert manifest["task_scope"] == residual["binding"].task_scope
    assert metadata["contract"] == owner.RESIDUAL_CONTRACT
    assert {row["w"] for row in metadata["pending_spans"]} == {1, 3}
    assert len(metadata["retained_spans"]) == len(prepared["authored_user_exchanges"]) - 2
    assert metadata["retained_spans"][0]["span"]["c"] == [0]
    assert metadata["already_applied_truth_ids"] == ["narrow-successor"]
    protected = metadata["committed_point_spans"]
    assert len(protected) == 1 and protected[0]["w"] == 2
    assert protected[0]["candidate_ids"] == ["fixture"]
    assert protected[0]["truth_ids"] == ["narrow-successor"]
    assert protected[0]["basis_sha256"] == owner._digest(
        {k: v for k, v in protected[0].items() if k != "basis_sha256"})
    converted = next(row for row in metadata["retained_spans"] if row["w"] == 2)
    assert converted["span"]["d"] == "covered" and converted["span"]["c"] == [0]
    assert converted["span"]["p"] == converted["span"]["r"] == []
    assert all(len(row["basis_sha256"]) == 64 for row in metadata["retained_spans"])
    assert before == residual["backend"].structured_store._canonical.get_payload_json("dream_runs", "failed-audit")


def test_existing_worker_runs_on_guarded_child_and_same_account_without_replaying_truth(residual, monkeypatch):
    seen = []
    backend, provider = residual["backend"], residual["provider"]
    manifest = prepare(residual)
    canonical = backend.structured_store._canonical
    origin_before = canonical.get_payload_json("dream_runs", "failed-audit")
    truth_before = canonical.get_payload_json("knowledge_entries", "narrow-successor")
    account_before = read_task_budget_receipt(backend.data_dir, residual["binding"].task_scope)

    def worker(_backend, **kwargs):
        seen.append(kwargs["prepared"]["inventory_audit_repair"])
        provider.charge()  # Existing finite ledger; transport is the isolated fake.
        kwargs["save"]({"status": "no_write", "reason_code": "source_coverage_no_candidate"})
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt", worker)
    result = invoke(residual, manifest)
    assert result == {"worked": True, "pending": False, "status": "no_write"}
    assert len(seen) == 1 and seen[0]["already_applied_truth_ids"] == ["narrow-successor"]
    assert canonical.get_payload_json("dream_runs", "failed-audit") == origin_before
    assert canonical.get_payload_json("knowledge_entries", "narrow-successor") == truth_before
    after = read_task_budget_receipt(backend.data_dir, residual["binding"].task_scope)
    assert after["calls"][:len(account_before["calls"])] == account_before["calls"]
    assert len(after["calls"]) == len(account_before["calls"]) + 1
    assert invoke(residual, manifest)["worked"] is False
    assert len(seen) == 1


@pytest.mark.parametrize("field", ["scope_sha256", "sources_sha256"])
def test_changed_original_current_proof_is_fresh_not_retained(residual, field):
    residual["frozen"]["source_bindings"][residual["key"]]["current_rows"]["narrow-successor"][field] = "f" * 64
    save_origin(residual)
    prepare(residual)
    value, _item, _snapshots = run(owner._prepared(residual["backend"], origin=residual["origin"],
        frozen=residual["frozen"], key=residual["key"], project_name="demo",
        project_root=residual["root"], run_id="residual-run"))
    assert 0 in {row["w"] for row in value["inventory_audit_repair"]["pending_spans"]}


@pytest.mark.parametrize("fault", ["summary", "votes", "range", "point_link", "old_current_link", "workspace_input"])
def test_corrupt_old_inventory_refuses_without_transport(residual, fault):
    audit = residual["state"]["inventory_verification"]
    if fault == "summary":
        audit["summary_sha256"] = "0" * 64
    elif fault == "votes":
        audit["audit"].pop()
        seal_audit(audit)
    elif fault == "range":
        audit["windows"][0]["spans"][0]["e"] += 1
        seal_audit(audit)
    elif fault == "point_link":
        audit["windows"][2]["spans"][0]["p"] = [8]
        seal_audit(audit)
    elif fault == "old_current_link":
        audit["windows"][0]["spans"][0]["c"] = [999]
        seal_audit(audit)
    else:
        residual["state"]["inventory_workspace"]["input_sha256"] = "f" * 64
    save_origin(residual)
    with pytest.raises(ValueError, match="source_coverage_audit_"):
        prepare(residual)
    assert residual["provider"].calls == []


def test_unproved_p0_transaction_cannot_become_a_source_anchor(residual):
    residual["state"]["commit_bindings"][0]["decision_id"] = "never-committed"
    save_origin(residual)
    with pytest.raises(ValueError, match="commit_unproved"):
        prepare(residual)


@pytest.mark.parametrize("fault", ["account", "origin", "current", "job", "account_prefix"])
def test_frozen_runtime_drift_refuses_before_worker(residual, monkeypatch, fault):
    manifest = prepare(residual)
    backend = residual["backend"]
    if fault == "account":
        residual["provider"].task_budget_binding = residual["other_binding"]
    elif fault == "origin":
        residual["origin"].notes.append("Changed independently.")
        save_origin(residual)
    elif fault == "current":
        canonical = backend.structured_store._canonical
        payload = json.loads(canonical.get_payload_json("knowledge_entries", "narrow-successor"))
        payload["statement"] += " Changed independently."
        canonical.apply_payload_transaction(idempotency_key="current-drift", mutations=[{
            "operation": "upsert", "collection": "knowledge_entries", "entity_id": payload["id"], "payload": payload}])
    elif fault == "job":
        ledger = backend.transcript_store
        job = residual["prepared"]["job"].model_copy(update={"phase": "review"})
        with ledger._lock:
            ledger._distill._upsert_job_locked(job)
            ledger._conn.commit()
    else:
        path = task_budget_receipt_path(backend.data_dir, residual["binding"].task_scope)
        account = json.loads(path.read_text())
        account["calls"][0]["usage"]["input_tokens"] += 1
        path.write_text(json.dumps(account), encoding="utf-8")
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt",
                        lambda *_args, **_kwargs: pytest.fail("worker must not start"))
    with pytest.raises(ValueError, match="source_coverage_audit_"):
        invoke(residual, manifest)


def add_deferred(residual):
    backend, state = residual["backend"], residual["state"]
    store = backend.structured_store.knowledge_store
    candidate = KnowledgeCandidate(id="old-deferred", project_name="demo", candidate_type="rule",
                                   statement="Only during this Hook repair, preserve its existing configuration.")
    run(store.save_candidate(candidate))
    evidence = KnowledgeEvidence(id="old-deferred-evidence", project_name="demo", candidate_id=candidate.id,
        distill_job_id=state["binding"]["source_job_id"], evidence_basis="user_statement",
        verification_outcome="verified")
    run(store.save_evidence(evidence))
    state["candidate_ids"].append(candidate.id)
    state["inventory_workspace"]["workspace"].append({"id": candidate.id,
        "candidate_sha256": owner._digest(candidate.to_dict()), "evidence_sha256": owner._digest(evidence.to_dict())})
    run(store.save_candidate(candidate.model_copy(update={"status": "deferred"})))
    handoff = TaskHandoff(id="old-deferred-handoff", project_name="demo", task_id="task:old-deferred",
        summary="Preserve configuration during the Hook repair.",
        context={"candidate_id": candidate.id, "distill_job_id": evidence.distill_job_id})
    run(backend.structured_store.save_task_handoff(handoff))
    state["candidate_outcomes"].append({"candidate_id": candidate.id, "status": "deferred",
        "disposition": "handoff", "truth_ids": [], "handoff_id": handoff.id})
    state["inventory_verification"]["extracted_point_sha256"].append("f" * 64)
    state["inventory_verification"]["windows"][4]["spans"][0].update(d="extract", p=[1])
    seal_audit(state["inventory_verification"])
    save_origin(residual)
    return candidate, evidence, handoff


def test_actual_deferred_workspace_and_handoff_are_bound_without_promoting_them(residual):
    candidate, evidence, handoff = add_deferred(residual)
    prepare(residual)
    prepared, _item, _snapshots = run(owner._prepared(residual["backend"], origin=residual["origin"],
        frozen=residual["frozen"], key=residual["key"], project_name="demo",
        project_root=residual["root"], run_id="residual-run"))
    bindings = prepared["inventory_audit_repair"]["deferred_workspace_bindings"]
    assert len(bindings) == 1 and bindings[0]["candidate_id"] == candidate.id
    assert bindings[0]["handoff_id"] == handoff.id
    assert bindings[0]["evidence_sha256"] == owner._digest(evidence.to_dict())
    assert run(residual["backend"].structured_store.knowledge_store.get_candidate(candidate.id)).status == "deferred"


def test_deferred_evidence_change_is_not_repaired_from_diagnostic_files(residual):
    candidate, evidence, _handoff = add_deferred(residual)
    run(residual["backend"].structured_store.knowledge_store.save_evidence(
        evidence.model_copy(update={"verification_outcome": "unverified"})))
    with pytest.raises(ValueError, match="deferred_workspace_changed"):
        prepare(residual)
    assert candidate.id not in residual["state"]["committed_candidate_ids"]


@pytest.mark.parametrize("fault", ["candidate", "evidence", "truth", "outcome", "point_mapping"])
def test_committed_protection_requires_exact_point_workspace_and_canonical_proof(residual, fault):
    store = residual["backend"].structured_store.knowledge_store
    if fault == "candidate":
        candidate = run(store.get_candidate("fixture"))
        run(store.save_candidate(candidate.model_copy(update={"statement": "A different point."})))
    elif fault == "evidence":
        evidence = run(store.list_evidence("fixture"))[0]
        run(store.save_evidence(evidence.model_copy(update={"verification_reason_codes": ["different-original-proof"]})))
    elif fault == "truth":
        residual["state"]["commit_bindings"][0]["truth_sha256"] = ["f" * 64]
        save_origin(residual)
    elif fault == "outcome":
        residual["state"]["candidate_outcomes"][0]["truth_ids"] = ["some-other-truth"]
        save_origin(residual)
    else:
        add_deferred(residual)
        residual["state"]["candidate_ids"].reverse()
        residual["state"]["inventory_workspace"]["workspace"].reverse()
        save_origin(residual)
    with pytest.raises(ValueError, match="source_coverage_audit_committed_"):
        prepare(residual)
    assert residual["provider"].calls == []


@pytest.mark.parametrize("fault", ["mixed", "unsupported", "wrong_exchange"])
def test_partial_or_unverified_committed_span_cannot_cover_uncommitted_text(residual, fault):
    audit = residual["state"]["inventory_verification"]
    if fault == "mixed":
        add_deferred(residual)
        audit["windows"][2]["spans"][0]["p"] = [0, 1]
    elif fault == "unsupported":
        audit["audit"][2]["verdict"] = "unclear"
    else:
        audit["windows"][1]["spans"][0].update(d="extract", p=[0])
        audit["audit"][1]["verdict"] = "supported"
    seal_audit(audit)
    save_origin(residual)
    with pytest.raises(ValueError, match="committed_span_"):
        prepare(residual)


def test_only_shared_final_scope_marker_may_be_added_to_committed_evidence(residual):
    store = residual["backend"].structured_store.knowledge_store
    evidence = run(store.list_evidence("fixture"))[0]
    run(store.save_evidence(evidence.model_copy(update={"verification_reason_codes": ["fsv_" + "a" * 60]})))
    manifest = prepare(residual)
    assert manifest["contract"] == owner.CONTRACT
    run(store.save_evidence(evidence.model_copy(update={"verification_reason_codes": ["fsv_not-a-real-marker"]})))
    with pytest.raises(ValueError, match="committed_evidence_changed"):
        prepare(residual)


def test_guard_rejects_leaking_protected_span_back_into_native_pending_ranges(residual, monkeypatch):
    manifest = prepare(residual)
    real = owner._prepared
    async def poisoned(*args, **kwargs):
        prepared, item, snapshots = await real(*args, **kwargs)
        repair = prepared["inventory_audit_repair"]
        protected = repair["committed_point_spans"][0]
        repair["pending_spans"].append({k: protected[k] for k in ("w", "span_index", "s", "e")})
        repair["retained_spans"] = [row for row in repair["retained_spans"]
                                    if (row["w"], row["span_index"]) != (protected["w"], protected["span_index"])]
        repair["reuse_binding_sha256"] = owner._digest({k: v for k, v in repair.items() if k != "reuse_binding_sha256"})
        return prepared, item, snapshots
    monkeypatch.setattr(owner, "_prepared", poisoned)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt",
                        lambda *_a, **_kw: pytest.fail("protected range must not reach native proposal"))
    result = invoke(residual, manifest)
    assert result["status"] == "unresolved"
    child = residual["checkpoint"]["source_inventory_audit"]["source_coverage"][residual["key"]]
    assert child["status"] == "failed" and child["reason_code"] == "source_coverage_audit_prepared_changed"


def audit_child(data):
    """Freeze a zero-write failed child with its inherited p0 now covered."""
    manifest = prepare(data)
    value, _item, _snapshots = run(owner._prepared(data["backend"], origin=data["origin"],
        frozen=data["frozen"], key=data["key"], project_name="demo",
        project_root=data["root"], run_id="residual-run"))
    audit = deepcopy(data["state"]["inventory_verification"])
    audit["extracted_point_sha256"] = []
    for window in audit["windows"]:
        for span in window["spans"]:
            if span["d"] in {"extract", "covered"}:
                span.update(d="covered", p=[], c=[0])
    audit["audit"][0]["verdict"] = "unclear"
    seal_audit(audit)
    state = {"status": "unresolved", "reason_code": "source_coverage_inventory_audit_unresolved",
        "binding": value["binding"], "binding_sha256": owner._digest(value["binding"]),
        "inventory_verification": audit, "inventory_workspace": {
            "input_sha256": audit["input_sha256"], "workspace": []},
        "candidate_ids": [], "candidate_outcomes": [], "commit_bindings": []}
    child = DreamRun(id="residual-run", project_name="demo", status="failed", trigger_source="agent",
        completed_at=datetime.now(timezone.utc), execution_status="completed", resolution_status="unresolved",
        continuation={"maintenance_scope": dict(data["origin"].continuation["maintenance_scope"]),
            "explicit_repair_scope": {"source": manifest}, "source_inventory_audit": {
                "contract": owner.CONTRACT, "manifest_sha256": owner._digest(manifest),
                "task_scope": manifest["task_scope"], "source_coverage": {data["key"]: state}}})
    run(data["backend"].structured_store.save_dream_run(child))
    return child, manifest, state


def test_zero_write_failed_audit_child_reuses_ancestor_without_inventing_commit(residual):
    child, frozen, _state = audit_child(residual)
    canonical = residual["backend"].structured_store._canonical
    before = canonical.get_payload_json("dream_runs", child.id)
    manifest = run(owner.prepare_explicit_source_audit(residual["backend"], project_name="demo",
        project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[residual["key"]]))
    prepared, _item, _snapshots = run(owner._prepared(residual["backend"], origin=child, frozen=frozen,
        key=residual["key"], project_name="demo", project_root=residual["root"], run_id="grandchild"))
    repair = prepared["inventory_audit_repair"]
    assert manifest["origin_run_id"] == child.id
    assert {row["w"] for row in repair["pending_spans"]} == {0, 1}
    assert repair["already_applied_truth_ids"] == ["narrow-successor"]
    assert repair["committed_point_spans"] == []  # Child has no own commits.
    assert repair["ancestor_source_bindings"][0]["run_id"] == "failed-audit"
    assert repair["ancestor_committed_candidate_bindings"][0]["candidate_id"] == "fixture"
    assert canonical.get_payload_json("dream_runs", child.id) == before
    assert child.continuation["source_inventory_audit"]["source_coverage"][residual["key"]]["commit_bindings"] == []


def test_failed_audit_child_runs_only_guarded_residual_under_original_account(residual, monkeypatch):
    child, _frozen, _state = audit_child(residual)
    backend = residual["backend"]
    manifest = run(owner.prepare_explicit_source_audit(backend, project_name="demo",
        project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[residual["key"]]))
    before = backend.structured_store._canonical.get_payload_json("dream_runs", child.id)
    calls = []
    checkpoint = {"slice_count": 1}
    async def persist():
        pass
    def worker(_backend, **kwargs):
        repair = kwargs["prepared"]["inventory_audit_repair"]
        calls.append(repair)
        assert {row["w"] for row in repair["pending_spans"]} == {0, 1}
        assert repair["origin_run_id"] == child.id
        assert repair["committed_point_spans"] == []
        residual["provider"].charge()
        kwargs["save"]({"status": "no_write", "reason_code": "source_coverage_no_candidate"})
    monkeypatch.setattr("harness_mem.autonomous.worker.run_source_coverage_attempt", worker)
    result = run(owner.run_explicit_source_audit(backend, project_name="demo",
        project_root=residual["root"], run_id="grandchild", manifest=manifest,
        checkpoint=checkpoint, notes=[], provider=residual["provider"], persist=persist))
    assert result["status"] == "no_write" and len(calls) == 1
    assert backend.structured_store._canonical.get_payload_json("dream_runs", child.id) == before


@pytest.mark.parametrize("fault", ["ancestor_payload", "ancestor_source", "ancestor_commit", "account_prefix"])
def test_audit_child_rejects_changed_or_unproved_ancestor(residual, fault):
    child, frozen, _state = audit_child(residual)
    if fault == "ancestor_payload":
        frozen["origin_payload_sha256"] = "f" * 64
        child.continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(frozen)
        run(residual["backend"].structured_store.save_dream_run(child))
    elif fault == "ancestor_source":
        frozen["source_bindings"][residual["key"]]["binding"]["source_id"] = "foreign"
        child.continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(frozen)
        run(residual["backend"].structured_store.save_dream_run(child))
    elif fault == "ancestor_commit":
        residual["state"]["commit_bindings"][0]["decision_id"] = "uncommitted"
        save_origin(residual)
        frozen["origin_payload_sha256"] = owner._raw_digest(
            residual["backend"].structured_store._canonical.get_payload_json("dream_runs", "failed-audit"))
        child.continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(frozen)
        run(residual["backend"].structured_store.save_dream_run(child))
    else:
        frozen["account_prefix_sha256"] = "f" * 64
        child.continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(frozen)
        run(residual["backend"].structured_store.save_dream_run(child))
    with pytest.raises(ValueError, match="source_coverage_audit_"):
        run(owner.prepare_explicit_source_audit(residual["backend"], project_name="demo",
            project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
            predecessor_ids=[residual["key"]]))
    assert residual["provider"].calls == []


@pytest.mark.parametrize("fault", [None, "wrong_project", "incomplete", "invalid_reopen"])
def test_other_source_project_comparison_requires_full_reopened_source(residual, monkeypatch, fault):
    entry = residual["prepared"]["successor_entries"][0].model_copy(update={"id": "other-source-current"})
    revision = SimpleNamespace(source_id="other-source", source_revision="other-revision",
        session_id="other-session", project_name="demo", project_root=str(residual["root"]))
    body = {"context_scope": "complete-authored-user-v1", "role": "user", "project_name": "demo",
        "source_id": revision.source_id, "source_revision": revision.source_revision,
        "session_id": revision.session_id}
    if fault == "wrong_project":
        body["project_name"] = "foreign"
    if fault == "incomplete":
        body["context_scope"] = "excerpt"
    ref = SimpleNamespace(source_kind="user_statement", project_name="demo", knowledge_id=entry.id,
        locator="native#source_id=other-source&source_revision=other-revision&exchange=1")
    class Store:
        async def list_entries(self, *_args, **_kwargs):
            return [entry]
        async def list_sources(self, *_args):
            return [ref]
        async def get_entry(self, *_args, **_kwargs):
            return entry
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=Store()),
        transcript_store=SimpleNamespace(get_revision=lambda *_args: revision))
    monkeypatch.setattr(original, "_reopen_complete_user_context", lambda *_args:
        ("unverified" if fault == "invalid_reopen" else "verified", None, json.dumps(body), False, None))
    result = run(owner._project_comparisons(backend, project_name="demo",
        project_root=residual["root"], successor_ids=["narrow-successor"]))
    assert len(result) == (1 if fault is None else 0)
    if result:
        assert result[0]["comparison_only"] is True
        assert result[0]["kind"] == "current_knowledge_comparison_not_source_evidence"
        assert result[0]["id"] == "other-source-current"


def recovery_child(data, monkeypatch):
    child, frozen, state = audit_child(data)
    store = data["backend"].structured_store.knowledge_store
    original_candidate = KnowledgeCandidate(id="source-point", project_name="demo", candidate_type="rule",
        statement="Only during this Hook repair, preserve the existing configuration.")
    authored = data["prepared"]["authored_user_exchanges"][4]
    anchor = next(row["content_sha256"] for row in data["prepared"]["packet"]["semantic_decision_exchanges"]
                  if row["exchange_index"] == authored["exchange_index"])
    evidence = KnowledgeEvidence(id="source-point-evidence", project_name="demo", candidate_id=original_candidate.id,
        distill_job_id=state["binding"]["source_job_id"], evidence_basis="user_statement",
        verification_outcome="verified", verification_refs=[{"kind": "user_statement", "role": "user",
            "exchange_index": authored["exchange_index"], "content_sha256": anchor}])
    run(store.save_candidate(original_candidate.model_copy(update={"status": "assimilated"})))
    run(store.save_evidence(evidence))
    writing = original_candidate.model_copy(update={"id": "recovery-writing-point", "status": "assimilated"})
    writing_evidence = evidence.model_copy(update={"id": "writing-evidence", "candidate_id": writing.id})
    run(store.save_candidate(writing))
    run(store.save_evidence(writing_evidence))
    state["candidate_ids"] = [original_candidate.id]
    state["candidate_outcomes"] = [{"candidate_id": original_candidate.id, "status": "assimilated",
        "disposition": "handoff", "truth_ids": [], "handoff_id": "actual-original-handoff"}]
    state["inventory_workspace"]["workspace"] = [{"id": original_candidate.id,
        "candidate_sha256": owner._digest(original_candidate.to_dict()),
        "evidence_sha256": owner._digest(evidence.to_dict())}]
    state["inventory_verification"]["extracted_point_sha256"] = ["a" * 64]
    state["inventory_verification"]["windows"][4]["spans"][0].update(d="extract", p=[0], c=[])
    seal_audit(state["inventory_verification"])
    run(data["backend"].structured_store.save_dream_run(child))
    entry = data["prepared"]["successor_entries"][0]
    raw = data["backend"].structured_store._canonical.get_payload_json("knowledge_entries", entry.id)
    truth_binding = {"id": entry.id, "payload_sha256": owner._raw_digest(raw),
        "scope_sha256": "e" * 64, "sources": []}
    recovered = {"original_candidate_id": original_candidate.id, "writing_candidate_id": writing.id,
        "original_binding": {"original_candidate_id": original_candidate.id, "mode": "retained_workspace",
            "handoff_id": "actual-original-handoff", "original_point_sha256": owner._digest({
                "point": state["candidate_outcomes"][0], "mode": "inventory_workspace",
                "state_sha256": owner._digest(state)}),
            "candidate_sha256": owner._digest(run(store.get_candidate(original_candidate.id)).to_dict()),
            "evidence_sha256": owner._digest([evidence.to_dict()])},
        "handoff_id": "actual-original-handoff", "writing_candidate_sha256": owner._digest(writing.to_dict()),
        "writing_evidence_sha256": owner._digest([writing_evidence.to_dict()]),
        "point_proofs": [{"disposition": "add", "point_sha256": "f" * 64,
            "truth_ids": [entry.id], "truth_bindings": [truth_binding]}],
        "commit_bindings": [{"candidate_id": writing.id, "original_candidate_id": original_candidate.id,
            "status": "applied", "decision_id": "actual-recovery-decision", "truth_ids": [entry.id],
            "point_sha256": "f" * 64,
            "truth_semantic_sha256": ["e" * 64], "truth_bindings": [truth_binding]}]}
    proof = {"contract": "explicit-source-handoff-recovery-v1", "recovery_run_id": "canonical-recovery",
        "origin_run_id": child.id, "source_job_id": state["binding"]["source_job_id"],
        "source_id": state["binding"]["source_id"], "source_revision": state["binding"]["source_revision"],
        "task_scope": frozen["task_scope"], "binding_sha256": "b" * 64,
        "payload_sha256": "c" * 64, "resolved": [recovered]}
    carrier = DreamRun(id="canonical-recovery", project_name="demo", status="completed", trigger_source="agent",
        completed_at=datetime.now(timezone.utc), execution_status="completed", resolution_status="resolved")
    run(data["backend"].structured_store.save_dream_run(carrier))
    proof["payload_sha256"] = owner._raw_digest(
        data["backend"].structured_store._canonical.get_payload_json("dream_runs", carrier.id))
    async def canonical_proof(_backend, **kwargs):
        assert kwargs == {"run_id": "canonical-recovery", "origin_run_id": child.id,
                          "source_job_id": state["binding"]["source_job_id"]}
        return proof
    monkeypatch.setattr("harness_mem.commands.source_handoff_recovery.read_source_handoff_recovery_proof", canonical_proof)
    return child, frozen, state, proof


def test_actual_recovery_api_maps_old_rule_point_to_new_writing_id_without_reextraction(residual, monkeypatch):
    child, frozen, _state, proof = recovery_child(residual, monkeypatch)
    before = residual["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id)
    manifest = run(owner.prepare_explicit_source_audit(residual["backend"], project_name="demo",
        project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[residual["key"]], resolved_handoff_run_id="canonical-recovery"))
    prepared, _item, _snapshots = run(owner._prepared(residual["backend"], origin=child, frozen=frozen,
        key=residual["key"], project_name="demo", project_root=residual["root"], run_id="grandchild",
        resolved_handoff_run_id="canonical-recovery"))
    repair = prepared["inventory_audit_repair"]
    assert manifest["resolved_handoff_run_id"] == "canonical-recovery"
    assert {row["w"] for row in repair["pending_spans"]} == {0, 1}
    protected = repair["committed_point_spans"][0]
    assert protected["w"] == 4 and protected["candidate_ids"] == ["source-point"]
    assert protected["writing_candidate_ids"] == ["recovery-writing-point"]
    assert protected["commit_bindings"][0]["candidate_id"] == "recovery-writing-point"
    assert protected["recovery_proof_sha256"] == owner._digest(proof)
    assert repair["resolved_handoff_proof"] == proof
    assert repair["deferred_workspace_bindings"] == []
    old = run(residual["backend"].structured_store.knowledge_store.get_candidate("source-point"))
    assert old.candidate_type == "rule" and old.status == "assimilated"
    assert residual["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id) == before


@pytest.mark.parametrize("fault", ["missing_recovery", "no_write", "unbound_confirm", "original", "writing_kind", "commit"])
def test_recovery_without_actual_bound_truth_never_reextracts_a_proven_point(residual, monkeypatch, fault):
    child, _frozen, _state, proof = recovery_child(residual, monkeypatch)
    if fault in {"no_write", "unbound_confirm"}:
        proof["resolved"][0]["point_proofs"] = [{"disposition": "no_write" if fault == "no_write" else "confirm",
            "truth_ids": [], "truth_bindings": []}]
        proof["resolved"][0]["commit_bindings"] = []
    elif fault == "original":
        proof["resolved"][0]["original_binding"]["original_point_sha256"] = "f" * 64
    elif fault == "writing_kind":
        store = residual["backend"].structured_store.knowledge_store
        candidate = run(store.get_candidate("recovery-writing-point"))
        run(store.save_candidate(candidate.model_copy(update={"candidate_type": "memory"})))
    elif fault == "commit":
        proof["resolved"][0]["commit_bindings"][0]["point_sha256"] = "a" * 64
    kwargs = {} if fault == "missing_recovery" else {"resolved_handoff_run_id": "canonical-recovery"}
    with pytest.raises(ValueError, match="source_coverage_audit_(handoff_recovery_|recovery_)"):
        run(owner.prepare_explicit_source_audit(residual["backend"], project_name="demo",
            project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
            predecessor_ids=[residual["key"]], **kwargs))
    assert residual["provider"].calls == []


def test_recovery_carrier_is_immutable_after_source_manifest_freezes(residual, monkeypatch):
    child, _frozen, _state, _proof = recovery_child(residual, monkeypatch)
    backend = residual["backend"]
    manifest = run(owner.prepare_explicit_source_audit(backend, project_name="demo",
        project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[residual["key"]], resolved_handoff_run_id="canonical-recovery"))
    carrier = run(backend.structured_store.get_dream_run("canonical-recovery"))
    carrier.notes = [*(carrier.notes or []), "An independent mutation."]
    run(backend.structured_store.save_dream_run(carrier))
    async def persist():
        pass
    with pytest.raises(ValueError, match="recovery_carrier_changed"):
        run(owner.run_explicit_source_audit(backend, project_name="demo", project_root=residual["root"],
            run_id="grandchild", manifest=manifest, checkpoint={}, notes=[],
            provider=residual["provider"], persist=persist))
    assert residual["provider"].calls == []


def no_write_child(data, monkeypatch):
    child, frozen, state, proof = recovery_child(data, monkeypatch)
    resolved = proof["resolved"][0]
    writer = resolved["writing_candidate_id"]
    binding = {"contract": proof["contract"], "run_id": proof["recovery_run_id"],
        "origin_run_id": child.id, "source_job_id": proof["source_job_id"]}
    proof["binding_sha256"] = owner._digest(binding)
    point = {"candidate_id": writer, "answer_status": "ANSWERED", "disposition": "no_write",
        "matched_truth_ids": [], "knowledge_items": [], "reason": "This instruction belongs only to that repair."}
    plan = {"version": "separated-v1", "candidate_ids": [writer], "point_count": 1, "points": [point]}
    runtime = data["backend"].data_dir / "autonomous" / "provider-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    plan_path = runtime / ("source-handoff-plan-" + owner._digest(binding) + ".json")
    plan_bytes = json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()
    plan_path.write_bytes(plan_bytes)
    resolved["commit_bindings"] = []
    resolved["point_proofs"] = [{"disposition": "no_write", "point_sha256": owner._digest(point),
        "truth_ids": [], "truth_bindings": []}]
    carrier = run(data["backend"].structured_store.get_dream_run("canonical-recovery"))
    carrier.continuation["source_handoff_recovery"] = {"binding": binding,
        "binding_sha256": proof["binding_sha256"], "plan_path": str(plan_path),
        "plan_sha256": owner._raw_digest(plan_bytes.decode()), "result_sha256": "d" * 64,
        "apply_outcomes": [{"candidate_id": writer, "disposition": "no_write",
            "canonical_truth_ids": [], "handoff_id": None}], "commit_bindings": [],
        "canonical_outcomes": [{"original_candidate_id": resolved["original_candidate_id"],
            "candidate_id": writer, "status": "resolved", "point_proofs": resolved["point_proofs"],
            "candidate_sha256": resolved["writing_candidate_sha256"],
            "terminal_evidence_sha256": resolved["writing_evidence_sha256"], "handoff_id": resolved["handoff_id"]}]}
    run(data["backend"].structured_store.save_dream_run(carrier))
    proof["payload_sha256"] = owner._raw_digest(
        data["backend"].structured_store._canonical.get_payload_json("dream_runs", carrier.id))
    witness = {"contract": proof["contract"], "binding_sha256": proof["binding_sha256"],
        "run_id": proof["recovery_run_id"], "source_job_id": proof["source_job_id"],
        "original_candidate_id": resolved["original_candidate_id"],
        "points_sha256": owner._digest(resolved["point_proofs"])}
    handoff = TaskHandoff(id=resolved["handoff_id"], project_name="demo", task_id="assimilation:source-point",
        summary="No independent lasting point from this one repair.", status="done",
        context={"source_handoff_resolution": witness})
    run(data["backend"].structured_store.save_task_handoff(handoff))
    return child, frozen, state, proof, carrier, plan_path


def test_resolved_common_no_write_reopens_source_span_without_inheriting_coverage(residual, monkeypatch):
    child, frozen, _state, proof, _carrier, _plan = no_write_child(residual, monkeypatch)
    before = residual["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id)
    prepared, _item, _snapshots = run(owner._prepared(residual["backend"], origin=child, frozen=frozen,
        key=residual["key"], project_name="demo", project_root=residual["root"], run_id="grandchild",
        resolved_handoff_run_id="canonical-recovery"))
    repair = prepared["inventory_audit_repair"]
    assert {row["w"] for row in repair["pending_spans"]} == {0, 1, 4}
    assert not any(row["w"] == 4 for row in repair["retained_spans"])
    assert repair["committed_point_spans"] == [] and repair["committed_candidate_bindings"] == []
    assert repair["already_applied_truth_ids"] == ["narrow-successor"]
    assert repair["deferred_workspace_bindings"] == []
    resolved = repair["resolved_no_write_points"][0]
    assert resolved["original_point_index"] == 0 and resolved["candidate_id"] == "source-point"
    assert resolved["writing_candidate_id"] == "recovery-writing-point" and resolved["coverage_authority"] is False
    assert resolved["recovery_proof_sha256"] == owner._digest(proof)
    assert resolved["canonical_no_write_binding"]["common_no_write_receipt"]["disposition"] == "no_write"
    assert residual["backend"].structured_store._canonical.get_payload_json("dream_runs", child.id) == before
    assert residual["provider"].calls == []


@pytest.mark.parametrize("fault", ["receipt_missing", "receipt_truth", "plan_hash", "point_hash",
                                  "truth_claimed", "handoff", "writing_status", "original_candidate"])
def test_no_write_requires_exact_common_receipt_source_plan_and_closure(residual, monkeypatch, fault):
    child, frozen, _state, proof, carrier, _plan = no_write_child(residual, monkeypatch)
    ledger = carrier.continuation["source_handoff_recovery"]
    if fault == "receipt_missing":
        ledger["apply_outcomes"] = []
    elif fault == "receipt_truth":
        ledger["apply_outcomes"][0]["canonical_truth_ids"] = ["narrow-successor"]
    elif fault == "plan_hash":
        ledger["plan_sha256"] = "f" * 64
    elif fault == "point_hash":
        proof["resolved"][0]["point_proofs"][0]["point_sha256"] = "f" * 64
    elif fault == "truth_claimed":
        proof["resolved"][0]["point_proofs"][0]["truth_ids"] = ["narrow-successor"]
    elif fault == "handoff":
        handoff = run(residual["backend"].structured_store.get_task_handoff("actual-original-handoff"))
        handoff.status = "in_progress"
        run(residual["backend"].structured_store.save_task_handoff(handoff))
    elif fault in {"writing_status", "original_candidate"}:
        store = residual["backend"].structured_store.knowledge_store
        identity = "recovery-writing-point" if fault == "writing_status" else "source-point"
        candidate = run(store.get_candidate(identity))
        change = {"status": "pending"} if fault == "writing_status" else {"statement": "An unrelated instruction."}
        run(store.save_candidate(candidate.model_copy(update=change)))
    run(residual["backend"].structured_store.save_dream_run(carrier))
    proof["payload_sha256"] = owner._raw_digest(
        residual["backend"].structured_store._canonical.get_payload_json("dream_runs", carrier.id))
    with pytest.raises(ValueError, match="source_coverage_audit_recovery_"):
        run(owner._prepared(residual["backend"], origin=child, frozen=frozen, key=residual["key"],
            project_name="demo", project_root=residual["root"], run_id="grandchild",
            resolved_handoff_run_id="canonical-recovery"))
    assert residual["provider"].calls == []


@pytest.mark.parametrize("drift", [False, True])
def test_guard_supplies_complete_current_to_actual_worker_native_manifest(residual, monkeypatch, drift):
    from harness_mem.autonomous.provider import _residual_inventory_basis

    child, _frozen, _state, proof = recovery_child(residual, monkeypatch)
    backend = residual["backend"]
    canonical = backend.structured_store._canonical
    store = backend.structured_store.knowledge_store
    existing = residual["prepared"]["successor_entries"][0]
    entry = existing.model_copy(update={"id": "new-compared-truth", "title": "A separately admitted current point"})
    refs = [ref.model_copy(update={"id": ref.id + "-new", "knowledge_id": entry.id})
            for ref in run(store.list_sources(existing.id))]
    canonical.apply_payload_transaction(idempotency_key="fixture-new-comparison", mutations=[
        {"operation": "upsert", "collection": "knowledge_entries", "entity_id": entry.id,
         "payload": entry.to_dict()}, *[{"operation": "upsert", "collection": "knowledge_sources",
         "entity_id": ref.id, "payload": ref.to_dict()} for ref in refs]])
    semantic = owner._digest({"title": entry.title, "statement": entry.statement,
                             "topic_path": entry.module_path, "source_report": None})
    bound = {"id": entry.id, "payload_sha256": owner._raw_digest(
        canonical.get_payload_json("knowledge_entries", entry.id)), "scope_sha256": semantic,
        "sources": [{"source_id": ref.id, "knowledge_id": entry.id, "payload_sha256": owner._raw_digest(
            canonical.get_payload_json("knowledge_sources", ref.id))} for ref in refs]}
    resolved = proof["resolved"][0]
    resolved["point_proofs"][0].update(truth_ids=[entry.id], truth_bindings=[bound])
    resolved["commit_bindings"][0].update(truth_ids=[entry.id], truth_bindings=[bound],
        truth_semantic_sha256=[semantic], truth_payload_sha256=[owner._digest(entry.to_dict())],
        transaction_sha256="a" * 64)
    async def narrow_comparisons(*_args, **_kwargs):
        return []  # Shared _prepare still provides the old narrow projection.
    monkeypatch.setattr(original, "_current_source_comparison", narrow_comparisons)
    manifest = run(owner.prepare_explicit_source_audit(backend, project_name="demo",
        project_root=residual["root"], run_id="grandchild", origin_run_id=child.id,
        predecessor_ids=[residual["key"]], resolved_handoff_run_id="canonical-recovery"))
    captured = []
    def before_native(_provider, **kwargs):
        native = kwargs["manifest"]
        scope = native["source_coverage"]
        basis = _residual_inventory_basis(native)
        captured.append(native)
        assert entry.id in {row["id"] for row in scope["comparison_current_truth"]}
        current = scope["inventory_input"]["current"]
        protected = scope["inventory_audit_repair"]["committed_point_spans"][0]
        assert current[protected["truth_bindings"][0]["current_index"]]["id"] == entry.id
        assert (4, 0) in basis["retained"] and (4, 0) not in basis["pending"]
        raise ValueError("fixture_stop_before_native")
    monkeypatch.setattr("harness_mem.autonomous.worker._decide_with_candidate_retry", before_native)
    if drift:
        changed = entry.model_copy(update={"statement": entry.statement + " An independent change."})
        canonical.apply_payload_transaction(idempotency_key="fixture-comparison-drift", mutations=[{
            "operation": "upsert", "collection": "knowledge_entries", "entity_id": entry.id,
            "payload": changed.to_dict()}])
    async def persist():
        pass
    action = owner.run_explicit_source_audit(backend, project_name="demo", project_root=residual["root"],
        run_id="grandchild", manifest=manifest, checkpoint={}, notes=[],
        provider=residual["provider"], persist=persist)
    if drift:
        with pytest.raises(ValueError, match="current_changed"):
            run(action)
        assert captured == []
    else:
        assert run(action)["status"] == "unresolved"
        assert len(captured) == 1
    assert residual["provider"].calls == []


@pytest.mark.parametrize("fault", [None, "foreign_session", "changed_prefix", "truncated", "old_revision"])
def test_later_packet_is_exact_reopened_same_session_extension(residual, monkeypatch, fault):
    prepared = residual["prepared"]
    old = prepared["binding"]
    job = prepared["job"]
    authored = prepared["authored_user_exchanges"]
    exchanges = []
    for window in authored:
        if not exchanges or exchanges[-1]["exchange_index"] != window["exchange_index"]:
            exchanges.append({"exchange_index": window["exchange_index"], "messages": []})
        exchanges[-1]["messages"].append(window["text"])
    last = max(window["exchange_index"] for window in authored)
    exchanges.append({"exchange_index": last + 1, "messages": ["Keep explicit history review available."]})
    revision_id = old["source_revision"] if fault == "old_revision" else "later-revision"
    body = {"role": "user", "context_scope": "complete-authored-user-v1", "project_name": "demo",
        "source_id": old["source_id"], "source_revision": revision_id,
        "session_id": job.session_id, "authored_exchanges": exchanges}
    if fault == "changed_prefix":
        body["authored_exchanges"][0]["messages"][0] += " Changed."
    content = json.dumps(body, ensure_ascii=False)
    revision = SimpleNamespace(source_id=old["source_id"], source_revision=revision_id,
        session_id="foreign" if fault == "foreign_session" else job.session_id,
        client=job.client, project_name="demo", project_root=str(residual["root"]))
    entry = prepared["successor_entries"][0]
    ref = SimpleNamespace(source_kind="user_statement", project_name="demo", knowledge_id=entry.id,
        locator=f"native#source_id={old['source_id']}&source_revision={revision_id}&exchange={last + 1}",
        content_sha256="d" * 64)
    class Store:
        async def list_entries(self, *_args, **_kwargs):
            return [entry]
        async def list_sources(self, *_args):
            return [ref, ref]  # Duplicate references never duplicate raw input.
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=Store()),
        transcript_store=SimpleNamespace(get_revision=lambda *_args: revision))
    monkeypatch.setattr(original, "_reopen_complete_user_context", lambda *_args:
        ("verified", None, content, fault == "truncated", None))
    original_binding = {"source_id": old["source_id"], "session_id": job.session_id, "client": job.client,
        "project_name": "demo", "project_root_sha256": owner._digest(str(residual["root"].resolve()))}
    packets, windows = run(owner._later_user_contexts(backend, prepared, project_name="demo",
        project_root=residual["root"], original_binding=original_binding))
    assert len(packets) == (1 if fault is None else 0)
    if packets:
        packet = packets[0]
        assert packet["content"] == content and packet["context_sha256"] == owner._raw_digest(content)
        assert packet["original_context_sha256"] == old["context_sha256"]
        assert windows[packet["context_sha256"]][(last + 1, 0)]["text"] == exchanges[-1]["messages"][0]
        audit = deepcopy(residual["state"])
        text = exchanges[-1]["messages"][0]
        audit["inventory_verification"]["windows"][0]["spans"][0].update(d="superseded", c=[], r=[{
            "context_sha256": packet["context_sha256"], "exchange_index": last + 1, "message_index": 0,
            "content_sha256": owner._raw_digest(text), "s": 0, "e": len(text)}])
        seal_audit(audit["inventory_verification"])
        owner._audit_windows(audit, authored, 2, windows)
        with pytest.raises(ValueError, match="later_link_invalid"):
            owner._audit_windows(audit, authored, 2, {})


def test_maximal_later_packets_drop_only_exact_prefixes_and_keep_referenced_hashes():
    def packet(identity, messages):
        return {"context_sha256": identity, "content": json.dumps({"authored_exchanges": [
            {"exchange_index": index + 1, "messages": [message]} for index, message in enumerate(messages)]})}
    short = packet("short", ["old", "later"])
    long = packet("long", ["old", "later", "newest"])
    conflicting = packet("conflict", ["old", "different"])
    assert owner._maximal_later_contexts([short, long, conflicting], []) == [long, conflicting]
    assert owner._maximal_later_contexts([short, long, conflicting], ["short"]) == [short, long, conflicting]


@pytest.fixture
def failed_observation(residual):
    from dataclasses import replace
    from harness_mem.autonomous.provider import _coverage_inventory_hash, _build_verification_prompt
    from harness_mem.autonomous.worker import _build_candidate_verification_manifest
    from harness_mem.autonomous.executors.task_budget import dispatch_with_task_budget, NativeDispatchResult

    data = residual
    from harness_mem.autonomous.executors.task_budget import maintenance_task_scope
    old_account = read_task_budget_receipt(data["backend"].data_dir, data["binding"].task_scope)
    scope = data["origin"].continuation["maintenance_scope"]
    scope["trigger_id"] = "explicit-agent-memory-repair-fixture"
    task = maintenance_task_scope(scope["trigger_id"], scope["dispatch_generation"])
    data["binding"] = replace(data["binding"], task_scope=task)
    old_account["task_scope"] = task
    task_budget_receipt_path(data["backend"].data_dir, task).write_text(json.dumps(old_account))
    data["origin"].continuation["repair_source_coverage"]["task_scope"] = task
    save_origin(data)
    frozen = prepare(data)
    prepared, _item, _snapshots = run(owner._prepared(data["backend"], origin=data["origin"],
        frozen=data["frozen"], key=data["key"], project_name="demo", project_root=data["root"],
        run_id="residual-run"))
    binding = prepared["binding"]
    repair = prepared["inventory_audit_repair"]
    compared = {row["id"]: row for row in [*prepared["successors"], *prepared["comparison_current_truth"]]}
    source = {"contract": "source-coverage-inventory-v1",
        **{name: binding[name] for name in ("source_id", "source_revision", "context_sha256")},
        "windows": [{**{k: v for k, v in row.items() if k != "anchor_sha256"},
                     "exchange_sha256": row["anchor_sha256"]} for row in prepared["authored_user_exchanges"]],
        "current": [compared[key] for key in sorted(compared)]}
    windows = deepcopy(repair["origin_windows"])
    for retained in repair["retained_spans"]:
        windows[retained["w"]]["spans"][retained["span_index"]] = retained["span"]
    for pending in repair["pending_spans"]:
        span = windows[pending["w"]]["spans"][pending["span_index"]]
        span.update(d="unclear" if pending["w"] == 1 else "temporary", p=[], c=[], r=[])
    inventory = {"input_sha256": owner._digest(source), "candidate_output_sha256": owner._digest([]),
        "extracted_points": [], "windows": windows}
    inventory["inventory_sha256"] = _coverage_inventory_hash(inventory)
    scope = {"kind": "runtime_maintenance_scope_not_source_evidence", "contract": binding["contract"],
        "retain_still_applicable_scoped_conditions": True, "run_id": "residual-run",
        "predecessor_id": data["key"], "current_successors": prepared["successors"],
        "comparison_current_truth": prepared["comparison_current_truth"],
        "inventory_input": source, "inventory_audit_repair": repair, "inventory": inventory}
    base = _build_candidate_verification_manifest(packet=prepared["packet"], validated_candidates=[],
        project_root=data["root"], backend=data["backend"], distill_job_id=prepared["job"].id)
    manifest = {**base, "source_coverage": scope, "session_context": [{
        "kind": "runtime_maintenance_scope_not_source_evidence",
        "content": json.dumps(scope, ensure_ascii=False, sort_keys=True)}, *(base.get("session_context") or [])]}
    response = json.dumps({"points": [], "audit": [{"w": row["w"], "span_index": row["span_index"],
        "verdict": "unclear" if row["w"] == 1 else "supported"} for row in repair["pending_spans"]]})
    state = {"status": "failed", "reason_code": "source_coverage_inventory_audit_unresolved",
        "binding": binding, "binding_sha256": owner._digest(binding), "candidate_ids": [], "commit_bindings": []}
    dispatch_with_task_budget(data["binding"], phase="dream",
        slice_id=f"source-coverage:residual-run:{state['binding_sha256']}:source-verify", timeout_seconds=1,
        transport=lambda _: NativeDispatchResult(status="completed", input_tokens=12, output_tokens=3,
            duration_seconds=.01, usage_exact=True))
    receipt = {"attempt_id": state["binding_sha256"], "phase": "candidate_verify",
        "source_job_id": prepared["job"].id, "schema_valid": True,
        "input_sha256": owner._raw_digest(_build_verification_prompt(manifest)),
        "response_sha256": owner._raw_digest(response), "input_tokens": 12, "output_tokens": 3,
        "duration_seconds": .01}
    child = DreamRun(id="residual-run", project_name="demo", status="failed", trigger_source="agent",
        completed_at=datetime.now(timezone.utc), execution_status="failed", resolution_status="unresolved",
        notes=["dream source coverage receipt: " + json.dumps(receipt)],
        continuation={"maintenance_scope": data["origin"].continuation["maintenance_scope"],
            "explicit_repair_scope": {"source": frozen}, "source_inventory_audit": {
                "contract": owner.CONTRACT, "task_scope": frozen["task_scope"],
                "manifest_sha256": owner._digest(frozen), "source_coverage": {data["key"]: state}}})
    run(data["backend"].structured_store.save_dream_run(child))
    canonical = data["backend"].structured_store._canonical
    raw = canonical.get_payload_json("dream_runs", child.id)
    return {**data, "child": child, "manifest": manifest, "response": response,
            "before_raw": raw, "expected_sha": owner._raw_digest(raw)}


def settle(data):
    return run(owner.settle_failed_source_audit_observation(data["backend"], project_name="demo",
        project_root=data["root"], run_id=data["child"].id, predecessor_id=data["key"],
        expected_payload_sha256=data["expected_sha"], manifest=data["manifest"], raw_response=data["response"]))


def test_failed_negative_observation_appends_only_proof_and_resumes_without_replaying(failed_observation):
    data = failed_observation
    canonical = data["backend"].structured_store._canonical
    before_truth = canonical.list_payloads("knowledge_entries")
    before_account = read_task_budget_receipt(data["backend"].data_dir, data["binding"].task_scope)
    with pytest.raises(ValueError, match="origin_state_invalid"):
        run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
            run_id="new-child", origin_run_id=data["child"].id, predecessor_ids=[data["key"]]))
    result = settle(data)
    after = json.loads(canonical.get_payload_json("dream_runs", data["child"].id))
    state = after["continuation"]["source_inventory_audit"]["source_coverage"][data["key"]]
    assert state["status"] == "failed" and state["inventory_verification"]["admission_mode"] == "observation"
    for name in owner._OBSERVATION_FIELDS:
        state.pop(name)
    assert after == json.loads(data["before_raw"])
    assert result["replayed"] is False and settle(data)["replayed"] is True
    manifest = run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo",
        project_root=data["root"], run_id="new-child", origin_run_id=data["child"].id,
        predecessor_ids=[data["key"]]))
    assert manifest["origin_payload_sha256"] == result["after_payload_sha256"]
    assert canonical.list_payloads("knowledge_entries") == before_truth
    assert read_task_budget_receipt(data["backend"].data_dir, data["binding"].task_scope) == before_account


@pytest.mark.parametrize("fault", ["raw_response", "manifest_context", "manifest_current", "sha", "receipt",
                                   "account", "descendant", "current"])
def test_failed_observation_rejects_unbound_or_changed_input(failed_observation, fault):
    data = failed_observation
    backend = data["backend"]
    canonical = backend.structured_store._canonical
    if fault == "raw_response":
        data["response"] += " "
    elif fault == "manifest_context":
        data["manifest"]["session_context"][-1]["content"] += " Changed."
    elif fault == "manifest_current":
        data["manifest"]["source_coverage"]["inventory_input"]["current"][0]["statement"] += " Changed."
    elif fault == "sha":
        data["expected_sha"] = "f" * 64
    elif fault == "receipt":
        data["child"].notes = []
        run(backend.structured_store.save_dream_run(data["child"]))
        data["expected_sha"] = owner._raw_digest(canonical.get_payload_json("dream_runs", data["child"].id))
    elif fault == "account":
        path = task_budget_receipt_path(backend.data_dir, data["binding"].task_scope)
        account = json.loads(path.read_text())
        account["calls"][-1]["usage_exact"] = False
        path.write_text(json.dumps(account))
    elif fault == "descendant":
        child = data["child"].model_copy(deep=True, update={"id": "illicit-old-descendant"})
        child.continuation["explicit_repair_scope"]["source"].update(origin_run_id=data["child"].id,
            origin_payload_sha256=data["expected_sha"])
        run(backend.structured_store.save_dream_run(child))
    else:
        entry = run(backend.structured_store.knowledge_store.get_entry("narrow-successor", project_name="demo"))
        entry.statement += " Changed."
        canonical.upsert_payload("knowledge_entries", entry.id, entry.to_dict())
    before = canonical.get_payload_json("dream_runs", data["child"].id)
    from harness_mem.autonomous.executors.task_budget import TaskBudgetRefusal
    with pytest.raises((ValueError, TaskBudgetRefusal)):
        settle(data)
    assert canonical.get_payload_json("dream_runs", data["child"].id) == before


@pytest.mark.parametrize("conflict", [False, True])
def test_observation_deduplicates_historical_receipts_and_rejects_conflicts(failed_observation, conflict):
    data = failed_observation
    note = data["child"].notes[0]
    if conflict:
        prefix = "dream source coverage receipt: "
        receipt = json.loads(note[len(prefix):])
        receipt["response_sha256"] = "f" * 64
        note = prefix + json.dumps(receipt)
    data["child"].continuation["terminal_coverage_receipts"] = [note]
    run(data["backend"].structured_store.save_dream_run(data["child"]))
    raw = data["backend"].structured_store._canonical.get_payload_json("dream_runs", data["child"].id)
    data["expected_sha"] = owner._raw_digest(raw)
    if conflict:
        with pytest.raises(ValueError, match="observation_receipt_conflict"):
            settle(data)
    else:
        assert settle(data)["replayed"] is False


def test_observation_cas_rejects_concurrent_failed_row_change(failed_observation, monkeypatch):
    from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
    data = failed_observation
    canonical = data["backend"].structured_store._canonical
    original_transaction = canonical.apply_payload_transaction
    def raced(**kwargs):
        child = json.loads(data["before_raw"])
        child["notes"].append("An independently persisted failure detail.")
        canonical.upsert_payload("dream_runs", child["id"], child)
        return original_transaction(**kwargs)
    monkeypatch.setattr(canonical, "apply_payload_transaction", raced)
    with pytest.raises(CanonicalTransactionPreconditionError):
        settle(data)
    current = json.loads(canonical.get_payload_json("dream_runs", data["child"].id))
    assert "inventory_observation" not in current["continuation"]["source_inventory_audit"]["source_coverage"][data["key"]]


@pytest.fixture
def observed_workspace_child(residual):
    child, frozen, state = audit_child(residual)
    prepared = residual["prepared"]
    exchange = prepared["authored_user_exchanges"][1]["exchange_index"]
    anchor = next(row["content_sha256"] for row in prepared["packet"]["semantic_decision_exchanges"]
                  if row["exchange_index"] == exchange)
    candidate = KnowledgeCandidate(id="held-observation-rule", project_name="demo", candidate_type="rule",
        statement="Preserve the exact task boundary while this point is reviewed.")
    evidence = KnowledgeEvidence(id="held-observation-evidence", project_name="demo", candidate_id=candidate.id,
        distill_job_id=prepared["job"].id, evidence_basis="user_statement", verification_outcome="unverified",
        verification_reason_codes=["source_coverage_inventory_observation_unresolved",
                                   "source_coverage_point_verification_verified"],
        verification_refs=[{"kind": "user_statement", "role": "user", "exchange_index": exchange,
                            "content_sha256": anchor}])
    store = residual["backend"].structured_store.knowledge_store
    run(store.save_candidate(candidate))
    run(store.save_evidence(evidence))
    state["candidate_ids"] = [candidate.id]
    audit = state["inventory_verification"]
    audit["admission_mode"] = "observation"
    audit["extracted_point_sha256"] = [owner._digest({"kind": "rule", "statement": candidate.statement})]
    audit["windows"][1]["spans"][0].update(d="extract", p=[0], c=[], r=[])
    next(row for row in audit["audit"] if row["w"] == 1 and row["span_index"] == 0)["verdict"] = "unclear"
    seal_audit(audit)
    state["inventory_workspace"]["workspace"] = [{"id": candidate.id,
        "candidate_sha256": owner._digest(candidate.to_dict()), "evidence_sha256": owner._digest(evidence.to_dict())}]
    run(residual["backend"].structured_store.save_dream_run(child))
    return {**residual, "child": child, "child_frozen": frozen, "child_state": state,
            "held_candidate": candidate, "held_evidence": evidence}


def test_observation_extract_reopens_as_pending_without_handoff_or_replaying_candidate(observed_workspace_child, monkeypatch):
    data = observed_workspace_child
    backend = data["backend"]
    canonical = backend.structured_store._canonical
    before = {name: canonical.list_payloads(name) for name in ("knowledge_entries", "knowledge_sources", "task_handoffs")}
    manifest = run(owner.prepare_explicit_source_audit(backend, project_name="demo", project_root=data["root"],
        run_id="observation-review-child", origin_run_id=data["child"].id, predecessor_ids=[data["key"]]))
    prepared, _item, _rows = run(owner._prepared(backend, origin=data["child"], frozen=data["child_frozen"],
        key=data["key"], project_name="demo", project_root=data["root"], run_id="observation-review-child"))
    repair = prepared["inventory_audit_repair"]
    assert (1, 0) in {(row["w"], row["span_index"]) for row in repair["pending_spans"]}
    assert repair["committed_candidate_bindings"] == [] and repair["committed_point_spans"] == []
    assert "resolved_handoff_proof" not in repair and repair["deferred_workspace_bindings"] == []
    assert repair["observed_candidate_bindings"] == [{"point_index": 0,
        "point_sha256": data["child_state"]["inventory_verification"]["extracted_point_sha256"][0],
        "candidate_id": data["held_candidate"].id,
        "candidate_sha256": owner._digest(data["held_candidate"].to_dict()),
        "evidence_sha256": owner._digest(data["held_evidence"].to_dict()),
        "source_id": prepared["binding"]["source_id"], "source_revision": prepared["binding"]["source_revision"],
        "source_job_id": prepared["job"].id, "source_job_sha256": prepared["binding"]["source_job_sha256"],
        "status": "pending", "admission": "blocked_inventory_observation"}]
    assert manifest["task_scope"] == data["binding"].task_scope
    assert run(backend.structured_store.knowledge_store.get_candidate(data["held_candidate"].id)).to_dict() == data["held_candidate"].to_dict()
    for name, values in before.items():
        assert canonical.list_payloads(name) == values
    seen = []
    def before_native(_provider, **kwargs):
        from harness_mem.autonomous.provider import _residual_inventory_basis
        native = kwargs["manifest"]
        basis = _residual_inventory_basis(native)
        assert (1, 0) in basis["pending"] and (1, 0) not in basis["retained"]
        assert native["source_coverage"]["inventory_audit_repair"]["observed_candidate_bindings"] == repair["observed_candidate_bindings"]
        seen.append(native)
        raise ValueError("fixture_stop_before_native")
    monkeypatch.setattr("harness_mem.autonomous.worker._decide_with_candidate_retry", before_native)
    async def persist():
        pass
    result = run(owner.run_explicit_source_audit(backend, project_name="demo", project_root=data["root"],
        run_id="observation-review-child", manifest=manifest, checkpoint={}, notes=[], provider=data["provider"],
        persist=persist))
    assert result["status"] == "unresolved" and len(seen) == 1
    assert data["provider"].calls == []
    assert run(backend.structured_store.knowledge_store.get_candidate(data["held_candidate"].id)).to_dict() == data["held_candidate"].to_dict()


@pytest.mark.parametrize("fault", ["candidate", "evidence", "approved", "source_job", "source_revision"])
def test_observation_workspace_drift_refuses_child_before_native(observed_workspace_child, fault):
    data = observed_workspace_child
    store = data["backend"].structured_store.knowledge_store
    if fault == "candidate":
        run(store.save_candidate(data["held_candidate"].model_copy(update={"statement": "Changed pending point."})))
    elif fault in {"evidence", "approved"}:
        change = {"verification_reason_codes": []} if fault == "evidence" else {"verification_outcome": "verified"}
        run(store.save_evidence(data["held_evidence"].model_copy(update=change)))
    else:
        binding = data["child_state"]["binding"]
        binding["source_job_id" if fault == "source_job" else "source_revision"] = "foreign"
        data["child_state"]["binding_sha256"] = owner._digest(binding)
        data["child_frozen"]["source_bindings"][data["key"]]["binding"] = binding
        data["child"].continuation["source_inventory_audit"]["manifest_sha256"] = owner._digest(data["child_frozen"])
        run(data["backend"].structured_store.save_dream_run(data["child"]))
    with pytest.raises(ValueError, match="source_coverage_audit_"):
        run(owner.prepare_explicit_source_audit(data["backend"], project_name="demo", project_root=data["root"],
            run_id="observation-review-child", origin_run_id=data["child"].id, predecessor_ids=[data["key"]]))
    assert data["provider"].calls == []
