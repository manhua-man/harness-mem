"""Contract changes revisit semantic no-writes without replaying committed work."""

from __future__ import annotations

import copy

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage, CoverageProvider, _cover, run
from test_terminal_source_coverage import terminal as terminal, invoke
from harness_mem.commands import dream_source_coverage as owner
from harness_mem.core.schemas.knowledge import KnowledgeCandidate
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt


def previous_state(binding, *, status="no_write", reason="source_coverage_no_new_claim"):
    binding = {**binding, "contract": "dream-applied-source-coverage-v1"}
    return {
        "status": status, "reason_code": reason, "binding": binding,
        "binding_sha256": owner._digest(binding), "candidate_ids": ["old-candidate"],
        "candidate_outcomes": [{"candidate_id": "old-candidate", "status": "assimilated",
                                "candidate_sha256": "a" * 64, "truth_ids": []}],
        "commit_bindings": [], "result_status_counts": {"promoted": 0},
        "terminal_takeover_contract": owner.TERMINAL_TAKEOVER_CONTRACT,
    }


def prepare(data, run_id="original-run"):
    backend, root, _job, _entry, item, checkpoint, notes = data
    return run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=run_id, item=item, checkpoint=checkpoint, notes=notes))


@pytest.mark.parametrize("status,reason", [
    ("no_write", "source_coverage_no_candidate"),
    ("no_write", "source_coverage_no_new_claim"),
    ("unresolved", "source_coverage_partial_resolution"),
])
def test_only_changed_semantic_contract_opens_once(coverage, status, reason):
    binding = prepare(coverage)["binding"]
    state = previous_state(binding, status=status, reason=reason)
    assert owner._coverage_pending(state)
    before = copy.deepcopy(state)
    current = owner._state_for_binding(state, binding)
    assert state == before
    assert current["binding"]["contract"] == owner.CONTRACT
    assert current["binding_sha256"] != state["binding_sha256"]
    history = current["previous_contract_attempts"][0]
    assert history["state_sha256"] == owner._digest(state)
    assert history["candidate_ids"] == ["old-candidate"]
    assert history["reason_code"] == reason
    assert current["candidate_ids"] == []
    current.update(status=status, reason_code=reason)
    assert not owner._coverage_pending(current)


@pytest.mark.parametrize("change", [
    {"status": "applied"}, {"status": "failed"}, {"status": "not_applicable"},
    {"reason_code": "source_coverage_original_user_source_unproved"},
    {"reason_code": "source_coverage_context_changed_before_commit"},
    {"reason_code": "source_coverage_successor_changed"},
    {"reason_code": "source_coverage_user_context_scope_changed"},
    {"commit_bindings": [{"status": "committing", "truth_ids": ["existing"]}]},
    {"committed_candidate_ids": ["existing"]},
    {"candidate_outcomes": [{"truth_ids": ["existing"]}]},
    {"result_status_counts": {"promoted": 1}},
    {"binding_sha256": "wrong"},
])
def test_committed_and_unproved_or_failed_attempts_stay_closed(coverage, change):
    state = previous_state(prepare(coverage)["binding"])
    state.update(change)
    assert not owner._coverage_pending(state)


def test_same_contract_and_source_or_successor_changes_cannot_reopen(coverage):
    binding = prepare(coverage)["binding"]
    state = previous_state(binding)
    for field in ("source_revision", "successor_sha256", "source_job_sha256", "context_sha256"):
        with pytest.raises(ValueError, match="attempt_binding_changed"):
            owner._state_for_binding(state, {**binding, field: "changed"})
    state["binding"] = binding
    state["binding_sha256"] = owner._digest(binding)
    assert not owner._coverage_pending(state)


@pytest.mark.parametrize("mode", ["no_candidate", "final_failure"])
def test_normal_coverage_preserves_old_candidates_and_does_not_retry_v2_terminal(coverage, mode):
    backend, _root, job, _entry, item, checkpoint, _notes = coverage
    prepared = prepare(coverage)
    old = previous_state(prepared["binding"])
    checkpoint["source_coverage"] = {item.source_id: old}
    candidate = KnowledgeCandidate(id="old-candidate", project_name="demo",
        candidate_type="memory", statement="Retain old workspace.", status="assimilated")
    run(backend.structured_store.knowledge_store.save_candidate(candidate))
    pending = run(backend.structured_store.knowledge_store.get_candidate("unrelated-pending")).to_dict()
    job_before = job.to_dict()
    provider = CoverageProvider(**{mode: True})
    assert run(_cover(coverage, provider))
    state = checkpoint["source_coverage"][item.source_id]
    assert state["status"] in {"no_write", "unresolved", "failed"}
    assert state["previous_contract_attempts"][0]["binding_sha256"] == old["binding_sha256"]
    calls = list(provider.calls)
    assert not run(_cover(coverage, provider))
    assert provider.calls == calls
    assert run(backend.structured_store.knowledge_store.get_candidate(candidate.id)).to_dict() == candidate.to_dict()
    assert run(backend.structured_store.knowledge_store.get_candidate("unrelated-pending")).to_dict() == pending
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == job_before


def seed_terminal_retry(data):
    backend, root, old, _carrier, _job, _provider, _config, _bindings = data
    cp = old.continuation
    cp.update(target_ids=[old.items[0].source_id] + [f"old-{i}" for i in range(16)],
        terminal_source_coverage_initial_count=3, slice_count=5,
        source_coverage_pending_ids=[old.items[0].source_id, "failed-source"])
    prepared = run(owner._prepare(backend, project_name="demo", project_root=root,
        run_id=old.id, item=old.items[0], checkpoint=cp, notes=old.notes))
    state = previous_state(prepared["binding"])
    cp["source_coverage"] = {old.items[0].source_id: state,
        "failed-source": {"status": "failed", "reason_code": "source_coverage_original_user_source_unproved"}}
    claims = {f"old-carrier:{i}": {"predecessor_id": old.items[0].source_id,
        "source_binding_sha256": state["binding_sha256"], "runtime_fingerprint": "v1-code",
        "status": "no_write" if i == 3 else "failed", "reason": "old-semantic-receipt"}
        for i in range(1, 4)}
    cp["terminal_coverage_takeover"] = {"contract": owner.TERMINAL_TAKEOVER_CONTRACT,
        "slice_count": 3, "claims": claims, "origin_fixed_sha256": owner._terminal_fixed(old)}
    cp["terminal_coverage_receipts"] = ["old failed receipt hash: " + "b" * 64]
    run(backend.structured_store.save_dream_run(old))
    return copy.deepcopy(claims), copy.deepcopy(state)


def test_terminal_count_origin_and_runner_share_contract_eligibility_and_original_bounds(terminal):
    backend, root, old, _carrier, _job, provider, config, bindings = terminal
    claims, old_state = seed_terminal_retry(terminal)
    fixed = owner._terminal_fixed(old)
    source_job_before = backend.transcript_store.get_distill_job(terminal[4].id).to_dict()
    account_before = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    carrier_before = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    assert run(owner.pending_terminal_source_coverage_count(backend, project_name="demo")) == 1
    selected = run(owner.bound_terminal_source_coverage_origin(backend, project_name="demo",
        project_root=root, config=config, host_client="codex", origin_run_id=old.id, require_idle=False))
    assert selected[0].id == old.id
    result = invoke(terminal)
    assert result["worked"] and result["status"] == "applied", result
    retained = run(backend.structured_store.get_dream_run(old.id))
    cp = retained.continuation
    assert owner._terminal_fixed(retained) == fixed
    assert retained.status == "failed" and retained.items == old.items and retained.completed_at == old.completed_at
    assert cp["slice_count"] == 5 and cp["max_slices"] == 24
    assert cp["terminal_coverage_takeover"]["slice_count"] == 4
    assert all(cp["terminal_coverage_takeover"]["claims"][key] == value for key, value in claims.items())
    assert cp["terminal_coverage_receipts"][0].startswith("old failed receipt hash:")
    assert cp["source_coverage"][old.items[0].source_id]["previous_contract_attempts"][0]["state_sha256"] == owner._digest(old_state)
    assert cp["source_coverage"]["failed-source"]["status"] == "failed"
    assert run(owner.pending_terminal_source_coverage_count(backend, project_name="demo")) == 0
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == carrier_before
    account_after = read_task_budget_receipt(backend.data_dir, bindings[0].task_scope)
    assert account_after["calls"][:len(account_before["calls"])] == account_before["calls"]
    assert backend.transcript_store.get_distill_job(terminal[4].id).to_dict() == source_job_before
    calls = list(provider.calls)
    invoke(terminal)
    assert provider.calls == calls


def test_retry_cannot_extend_original_terminal_slice_limit(terminal):
    backend, _root, old, _carrier, _job, provider, _config, _bindings = terminal
    seed_terminal_retry(terminal)
    cp = old.continuation
    claims = cp["terminal_coverage_takeover"]["claims"]
    for i in range(4, 20):
        claims[f"already-used:{i}"] = {"status": "failed"}
    cp["terminal_coverage_takeover"]["slice_count"] = len(claims)
    run(backend.structured_store.save_dream_run(old))
    result = invoke(terminal)
    assert result["reason"] == "terminal_coverage_original_slices_exhausted"
    assert provider.calls == [] and cp["max_slices"] == 24 and cp["slice_count"] == 5


def test_new_contract_checkpoint_resumes_while_old_claims_remain_sealed(terminal):
    backend, _root, old, carrier, _job, provider, _config, bindings = terminal
    claims, _state = seed_terminal_retry(terminal)

    async def yield_before_extract():
        raise RuntimeError("isolated slice boundary")

    with pytest.raises(RuntimeError, match="isolated slice boundary"):
        invoke(terminal, boundary=yield_before_extract)
    assert provider.calls == []
    carrier.continuation["slice_count"] = 2
    run(backend.structured_store.save_dream_run(carrier))
    provider.bind_task_budget(bindings[1], phase="dream", slice_id="dream:carrier:2")
    result = invoke(terminal)
    assert result["worked"] and result["status"] == "applied", result
    retained = run(backend.structured_store.get_dream_run(old.id))
    assert all(retained.continuation["terminal_coverage_takeover"]["claims"][key] == value
               for key, value in claims.items())
    assert retained.continuation["terminal_coverage_takeover"]["slice_count"] == 5
    assert retained.continuation["max_slices"] == 24


@pytest.mark.parametrize("saved", [{"status": "planned_handoff"},
    {"status": "assimilated", "disposition": "handoff", "handoff_id": "retained-handoff"}])
def test_crash_recovery_retains_handoff_unresolved_alongside_committed_candidate(coverage, saved):
    backend, root, job, _entry, item, checkpoint, _notes = coverage
    assert run(_cover(coverage, CoverageProvider()))
    store = backend.structured_store.knowledge_store
    handoff = KnowledgeCandidate(id="handoff-candidate", project_name="demo", candidate_type="memory",
        statement="Independent unfinished work.", status="assimilated")
    run(store.save_candidate(handoff))
    state = checkpoint["source_coverage"][item.source_id]
    state["candidate_ids"].append(handoff.id)
    state["candidate_outcomes"].append({"candidate_id": handoff.id, **saved})
    state["status"] = "committing"
    run(owner._workspace_status(backend, state))
    assert next(row for row in state["candidate_outcomes"] if row["candidate_id"] == handoff.id)["disposition"] == "handoff"
    assert run(owner._recover_committed(backend, state, project_name="demo", project_root=root))
    assert state["status"] == "unresolved" and state["committed_candidate_ids"]
    outcome = next(row for row in state["candidate_outcomes"] if row["candidate_id"] == handoff.id)
    assert outcome["disposition"] == "handoff"
    assert outcome.get("handoff_id") == saved.get("handoff_id")
    assert not owner._coverage_pending(state)


@pytest.mark.parametrize("handoff_first", [False, True])
@pytest.mark.parametrize("planned", [False, True])
def test_same_candidate_add_and_handoff_survive_refresh_and_crash_recovery(coverage, handoff_first, planned):
    backend, root, _job, _entry, item, checkpoint, _notes = coverage
    provider = CoverageProvider()
    assert run(_cover(coverage, provider))
    state = checkpoint["source_coverage"][item.source_id]
    identity = state["candidate_ids"][0]
    writing = {"candidate_id": identity, "status": "planned_add" if planned else "assimilated",
               "point_sha256": "1" * 64}
    handoff = {"candidate_id": identity, "status": "planned_handoff" if planned else "assimilated",
               "point_sha256": "2" * 64}
    if not planned:
        writing["disposition"] = "add"
        handoff.update(disposition="handoff", handoff_id="retained-independent-handoff")
    state["candidate_outcomes"] = [handoff, writing] if handoff_first else [writing, handoff]
    # Existing materialized promotion evidence is not a candidate-status count.
    state["result_status_counts"] = {"promoted": 1, "confirmed": 0}
    if not planned:
        state["result_status_counts"]["handoff"] = 1
    else:
        from uuid import NAMESPACE_URL, uuid5
        expected_handoff = str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge-handoff:{identity}"))
        assert run(backend.structured_store.get_task_handoff(expected_handoff)) is None
    state["status"] = "committing"
    proofs = copy.deepcopy(state["commit_bindings"])
    calls = list(provider.calls)
    run(owner._workspace_status(backend, state))
    assert len(state["candidate_outcomes"]) == 2
    assert state["point_disposition_counts"] == {"add": 1, "handoff": 1}
    assert state["result_status_counts"].get("handoff", 0) == (0 if planned else 1)
    assert state["result_status_counts"]["promoted"] == 1
    assert state["candidate_status_counts"] == {"assimilated": 1}
    if planned:
        assert {row["planned_disposition"] for row in state["candidate_outcomes"]} == {"add", "handoff"}
    assert "assimilated" not in state["result_status_counts"]
    assert run(owner._recover_committed(backend, state, project_name="demo", project_root=root))
    assert state["status"] == "unresolved"
    assert len(state["candidate_outcomes"]) == 2
    assert [row["point_sha256"] for row in state["candidate_outcomes"]] == (
        ["2" * 64, "1" * 64] if handoff_first else ["1" * 64, "2" * 64])
    assert state["result_status_counts"].get("handoff", 0) == (0 if planned else 1)
    assert state["result_status_counts"]["promoted"] == 1
    assert state["point_disposition_counts"] == {"add": 1, "handoff": 1}
    assert state["commit_bindings"] == proofs
    assert state["committed_candidate_ids"] == [identity]
    assert not owner._coverage_pending(state)
    assert not run(_cover(coverage, provider))
    assert provider.calls == calls


def test_workspace_status_does_not_promote_a_planned_writing_point(coverage):
    backend, _root, _job, _entry, _item, _checkpoint, _notes = coverage
    state = {"candidate_ids": ["unrelated-pending"], "candidate_outcomes": [
        {"candidate_id": "unrelated-pending", "status": "planned_add"},
        {"candidate_id": "unrelated-pending", "status": "planned_handoff"}],
        "result_status_counts": {"promoted": 0}}
    run(owner._workspace_status(backend, state))
    assert state["result_status_counts"] == {"promoted": 0}
    assert state["point_disposition_counts"] == {"add": 1, "handoff": 1}
    assert state["candidate_status_counts"] == {"pending": 1}
