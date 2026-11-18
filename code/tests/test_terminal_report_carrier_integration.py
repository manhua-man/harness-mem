"""Report-only native-shaped slices use real canonical stores and fake transports."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal, _idle_carrier
from test_dream_rendered_report_proposals import RenderedProvider, REPORT, TEMPORARY
from test_dream_stage4_contract import _capture_report, _output
from test_report_single_commit import _verdict
from harness_mem.commands import dream, dream_source_coverage
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.core.schemas.knowledge import KnowledgeCandidate
from harness_mem.autonomous.executors.task_budget import read_task_budget_receipt


def run(value):
    return asyncio.run(value)


@pytest.fixture
def report_terminal(terminal, monkeypatch):
    backend, root, origin, carrier, job, _provider, config, bindings = terminal
    # Remove the isolated fixture's ordinary obligation. A production source
    # obligation must run first and is covered separately by controller tests.
    origin.continuation["source_coverage_pending_ids"] = []
    run(backend.structured_store.save_dream_run(origin))
    carrier.continuation["terminal_source_coverage_origin_run_id"] = origin.id
    run(backend.structured_store.save_dream_run(carrier))
    _idle_carrier(terminal)
    report, ref = _capture_report(backend, REPORT)
    ids = run(record_assimilation_result(backend,
        candidate=KnowledgeCandidate(id="carrier-original-report", project_name="demo",
            candidate_type="memory", statement=report.text, source_report=report),
        project_root=root, source_refs=[ref],
        point={"disposition": "add", "knowledge_items": [{"title": report.render_title(),
            "statement": report.render_statement(), "topic_path": ["reports"],
            "claim_kind": "source_report"}], "reason": "Retain the complete fixture account.",
            "final_scope_judgment": _verdict(report)}))
    before = run(backend.structured_store.knowledge_store.get_entry(ids[0], project_name="demo"))
    output, retained = _output(report, "Alpha cache", "Alpha cache stays local.")
    case = backend, root, report, before, output, retained
    provider = RenderedProvider(case)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setattr(dream, "_dream_provider_from_config", lambda *_a, **_k: provider)
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_a, **_k: True)

    async def forbidden(*_a, **_k):
        raise AssertionError("report-only carrier cannot detect ordinary work or run source coverage")

    def no_intake(*_a, **_k):
        raise AssertionError("report-only carrier cannot stage or extract a new source")

    monkeypatch.setattr(dream, "_detect_separated_rechecks", forbidden)
    monkeypatch.setattr(dream_source_coverage, "run_pending_terminal_source_coverage", forbidden)
    monkeypatch.setattr(dream_source_coverage, "run_applied_source_coverage", forbidden)
    monkeypatch.setattr("harness_mem.autonomous.worker.run_autonomous_distill_batch", no_intake)
    return terminal, case, provider


def tick(data, **kwargs):
    terminal, _case, _provider = data
    backend, root, origin, _carrier, job, _oldprovider, config, _bindings = terminal
    return run(dream.dream_auto_tick(backend, project_name="demo", project_root=str(root),
        config=config, source="ide_hook", host_client="codex", trigger_id=job.session_id, **kwargs))


def test_report_carrier_full_owner_replaces_current_outside_old_manifest_and_reads_back(report_terminal):
    terminal, case, provider = report_terminal
    backend, _root, origin, _carrier, job, _oldprovider, _config, bindings = terminal
    assert case[3].id not in origin.continuation["target_ids"]
    fixed = dream_source_coverage._terminal_fixed(origin)
    new_account = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    source_before = backend.transcript_store.get_distill_job(job.id).to_dict()
    result = tick(report_terminal, report_origin_run_id=origin.id)
    assert result["status"] == "completed", result
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    assert child.id != origin.id and child.continuation["target_ids"] == [case[3].id]
    assert child.continuation["terminal_report_origin_run_id"] == origin.id
    assert provider.phases == ["source", "rendered", "proposal", "final"]
    assert getattr(provider, "_dream_owner_heartbeat", None) is None
    final_origin = run(backend.structured_store.get_dream_run(origin.id))
    assert dream_source_coverage._terminal_fixed(final_origin) == fixed
    assert final_origin.status == "failed" and final_origin.completed_at == origin.completed_at
    assert final_origin.continuation["slice_count"] == origin.continuation["slice_count"]
    takeover = final_origin.continuation["terminal_coverage_takeover"]
    assert takeover["slice_count"] == 1
    assert next(iter(takeover["claims"].values()))["kind"] == "report_recheck"
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    assert origin.id in reflection.input_refs and job.id in reflection.input_refs
    assert len(reflection.input_refs) == len(set(reflection.input_refs))
    assert all(scope == bindings[0].task_scope for scope in provider.scopes)
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == new_account
    assert backend.transcript_store.get_distill_job(job.id).to_dict() == source_before
    assert run(backend.structured_store.knowledge_store.get_entry(case[3].id, project_name="demo")) is None
    current = run(backend.structured_store.knowledge_store.list_entries("demo"))
    reports = [row for row in current if row.source_report is not None]
    assert len(reports) == 1 and reports[0].source_report == case[-1]
    assert TEMPORARY not in reports[0].statement


def test_report_carrier_resumes_same_manifest_with_fresh_reflection_and_shared_slice_count(report_terminal, monkeypatch):
    terminal, case, provider = report_terminal
    backend, _root, origin, _carrier, job, _oldprovider, _config, bindings = terminal
    real_now = dream._now
    elapsed = [False]
    monkeypatch.setattr(dream, "_now", lambda: real_now() + timedelta(seconds=200 if elapsed[0] else 0))
    original_verify = provider.verify

    def delay_after_verify(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        if provider.phases[-1] == "source":
            elapsed[0] = True
        return result

    monkeypatch.setattr(provider, "verify", delay_after_verify)
    first = tick(report_terminal, report_origin_run_id=origin.id)
    assert first["status"] == "continuing", first
    child_before = run(backend.structured_store.get_dream_run(first["run_id"]))
    manifest = child_before.continuation["terminal_report_manifest"]
    assert child_before.continuation["slice_count"] == 1
    elapsed[0] = False
    second = tick(report_terminal, resume_run_id=first["run_id"])
    assert second["status"] == "completed", second
    child = run(backend.structured_store.get_dream_run(first["run_id"]))
    assert child.continuation["terminal_report_manifest"] == manifest
    assert child.continuation["slice_count"] == 2
    assert child.reflection_job_id != child_before.reflection_job_id
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    assert origin.id in reflection.input_refs and job.id in reflection.input_refs
    final_origin = run(backend.structured_store.get_dream_run(origin.id))
    assert final_origin.continuation["terminal_coverage_takeover"]["slice_count"] == 2
    assert all(scope == bindings[0].task_scope for scope in provider.scopes)


@pytest.mark.parametrize("failure", ["rendered_partial", "final_partial", "drops_meaning", "drop_qualifier"])
def test_report_carrier_rejections_keep_original_and_remain_unresolved(report_terminal, failure):
    terminal, case, provider = report_terminal
    backend = terminal[0]
    provider.failure = failure
    result = tick(report_terminal, report_origin_run_id=terminal[2].id)
    assert result["status"] == "failed", result
    current = run(backend.structured_store.knowledge_store.get_entry(case[3].id, project_name="demo"))
    assert current.statement == case[3].statement
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    assert child.continuation["unresolved_scope"]
    assert child.resolution_status == "unresolved"


def test_report_bootstrap_rejects_parent_race_without_creating_or_overwriting_child(report_terminal):
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
    terminal, _case, _provider = report_terminal
    backend, _root, origin, *_rest = terminal
    child = DreamRun(id="guarded-new-report-child", project_name="demo", status="processing")
    writer = run(dream._report_bootstrap_writer(backend, origin=origin, prior=None, child_id=child.id))
    changed = origin.model_copy(deep=True)
    changed.notes = list(changed.notes or []) + ["Concurrent parent update must survive."]
    run(backend.structured_store.save_dream_run(changed))
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(writer(child))
    assert run(backend.structured_store.get_dream_run(child.id)) is None
    assert run(backend.structured_store.get_dream_run(origin.id)).notes == changed.notes


def test_report_bootstrap_rejects_stale_resume_before_processing_write(report_terminal):
    from harness_mem.core.schemas.dream_run import DreamRun
    from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
    terminal, _case, _provider = report_terminal
    backend, _root, origin, *_rest = terminal
    prior = DreamRun(id="guarded-existing-report-child", project_name="demo", status="continuing")
    run(backend.structured_store.save_dream_run(prior))
    concurrent = prior.model_copy(deep=True)
    concurrent.notes = ["A concurrent owner changed this exact child."]
    run(backend.structured_store.save_dream_run(concurrent))
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(dream._report_bootstrap_writer(backend, origin=origin, prior=prior, child_id=prior.id))
    assert run(backend.structured_store.get_dream_run(prior.id)).to_dict() == concurrent.to_dict()


def test_report_complete_bookkeeping_does_not_claim_an_extra_slice_or_call_model(report_terminal, monkeypatch):
    terminal, _case, provider = report_terminal
    backend, _root, origin, *_rest = terminal
    real_now = dream._now
    elapsed = [False]
    monkeypatch.setattr(dream, "_now", lambda: real_now() + timedelta(seconds=200 if elapsed[0] else 0))
    original_verify = provider.verify

    def delay_after_final(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        if provider.phases[-1] == "final":
            elapsed[0] = True
        return result

    monkeypatch.setattr(provider, "verify", delay_after_final)
    first = tick(report_terminal, report_origin_run_id=origin.id)
    assert first["status"] == "continuing", first
    before = run(backend.structured_store.get_dream_run(first["run_id"]))
    assert before.continuation["completed_signal_indexes"] == [0]
    parent_before = run(backend.structured_store.get_dream_run(origin.id))
    phases = list(provider.phases)
    elapsed[0] = False
    second = tick(report_terminal, resume_run_id=first["run_id"])
    assert second["status"] == "completed", second
    after = run(backend.structured_store.get_dream_run(first["run_id"]))
    parent_after = run(backend.structured_store.get_dream_run(origin.id))
    assert after.continuation["slice_count"] == before.continuation["slice_count"]
    assert (parent_after.continuation["terminal_coverage_takeover"]["slice_count"]
            == parent_before.continuation["terminal_coverage_takeover"]["slice_count"])
    assert provider.phases == phases


def test_report_receipt_cas_failure_still_closes_provider_restores_callbacks_and_preserves_race(report_terminal, monkeypatch):
    import copy
    terminal, _case, provider = report_terminal
    backend, _root, origin, *_rest = terminal
    canonical = backend.structured_store._canonical
    original_apply = canonical.apply_payload_transaction
    changed = []
    closed = []
    def prior_heartbeat():
        return None

    def prior_persist(_value):
        return None
    provider._dream_owner_heartbeat = prior_heartbeat
    provider._dream_report_persist = prior_persist
    provider.close = lambda: closed.append(True) or {"closed": True}

    def race_before_receipt(*args, **kwargs):
        if not changed:
            child_mutation = next((item for item in kwargs.get("mutations", [])
                if item.get("collection") == "dream_runs" and item.get("entity_id") != origin.id
                and "task_budget" in (item.get("payload") or {}).get("continuation", {})), None)
            if child_mutation is not None:
                current = run(backend.structured_store.get_dream_run(child_mutation["entity_id"]))
                current.notes = list(current.notes or []) + ["Concurrent final receipt update must survive."]
                payload = copy.deepcopy(current.to_dict())
                original_apply(idempotency_key="fixture-concurrent-report-final", mutations=[{
                    "operation": "upsert", "collection": "dream_runs", "entity_id": current.id,
                    "payload": payload}])
                changed.append(current.id)
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(canonical, "apply_payload_transaction", race_before_receipt)
    result = tick(report_terminal, report_origin_run_id=origin.id)
    assert result["status"] == "failed" and changed, result
    assert closed == [True]
    assert provider._dream_owner_heartbeat is prior_heartbeat
    assert provider._dream_report_persist is prior_persist
    current = run(backend.structured_store.get_dream_run(changed[0]))
    assert current.notes[-1] == "Concurrent final receipt update must survive."
