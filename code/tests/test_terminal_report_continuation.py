"""Report continuation ownership uses isolated stores and no native transports."""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_source_coverage import coverage as coverage
from test_terminal_source_coverage import terminal as terminal
from test_terminal_report_carrier_integration import report_terminal as report_terminal, tick
from harness_mem.commands import dream_report_continuation as module
from harness_mem.commands.dream_source_coverage import _terminal_fixed, TERMINAL_TAKEOVER_CONTRACT
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.autonomous.executors.task_budget import task_budget_receipt_path, read_task_budget_receipt
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


def run(value):
    return asyncio.run(value)


def bind_origin(data, **kwargs):
    backend, root, _origin, _oldcarrier, _job, _provider, config, _bindings = data[0]
    return run(module.bound_terminal_report_origin(backend, project_name="demo", project_root=root,
        config=config, host_client="codex", **kwargs))


@pytest.fixture
def prepared(report_terminal):
    data, _case, _rendered = report_terminal
    backend, root, origin, _oldcarrier, job, provider, _config, bindings = data
    manifest = run(module.report_manifest(backend, origin, project_name="demo", project_root=root))
    reflection = ReflectionJob(id="report-controller-reflection", project_name="demo", project_root=str(root),
        kind="dream", status="processing", source="ide_hook", input_refs=[origin.id, job.id])
    backend.reflection_job_store.save(reflection)
    child = DreamRun(id="report-controller-child", project_name="demo", status="processing", trigger_source="ide_hook",
        reflection_job_id=reflection.id, continuation={"version": "dream-slices-v3", "slice_count": 1,
        "max_slices": manifest["max_slices"], "maintenance_scope": dict(origin.continuation["maintenance_scope"]),
        "terminal_report_origin_run_id": origin.id, "terminal_report_manifest": manifest,
        "terminal_report_manifest_sha256": module._digest(manifest),
        "target_ids": [row["id"] for row in manifest["targets"]],
        "signals": [{"target_ids": [row["id"]]} for row in manifest["targets"]],
        "completed_signal_indexes": []})
    run(backend.structured_store.save_dream_run(child))
    provider.bind_task_budget(bindings[0], phase="dream", slice_id=f"dream:{child.id}:1")
    return report_terminal, child


def claim(prepared, **kwargs):
    data, child = prepared
    backend, root, _origin, _carrier, _job, provider, config, _bindings = data[0]
    return run(module.claim_report_slice(backend, carrier_run_id=child.id, provider=provider,
        config=config, host_client="codex", project_root=root, **kwargs))


def overwrite(canonical, collection, identity, payload, *, key="isolated-concurrent-write"):
    canonical.apply_payload_transaction(idempotency_key=key, mutations=[{"operation": "upsert",
        "collection": collection, "entity_id": identity, "payload": payload}])


def test_report_manifest_freezes_current_typed_reports_without_old_selector_permission(report_terminal):
    origin, generation, trigger, source_job = bind_origin(report_terminal)
    data, case, _provider = report_terminal
    backend, root, old, *_ = data
    manifest = run(module.report_manifest(backend, origin, project_name="demo", project_root=root))
    assert case[3].id not in old.continuation["target_ids"]
    assert [row["id"] for row in manifest["targets"]] == [case[3].id]
    assert generation == "original-generation" and trigger == data[4].session_id and source_job == data[4].id
    serialized = json.dumps(manifest)
    assert case[3].statement not in serialized and case[2].text not in serialized
    assert manifest["max_slices"] == 2


def test_source_coverage_must_finish_before_report_only_recheck(report_terminal):
    data = report_terminal[0]
    backend, _root, origin, *_ = data
    origin.continuation["source_coverage_pending_ids"] = [origin.items[0].source_id]
    run(backend.structured_store.save_dream_run(origin))
    with pytest.raises(ValueError, match="terminal_report_source_coverage_pending"):
        bind_origin(report_terminal)


@pytest.mark.parametrize("fault", ["active", "unknown", "exhausted", "host", "bounds"])
def test_original_account_failures_never_use_fresh_account(report_terminal, fault):
    backend, _root, _origin, _carrier, _job, provider, _config, bindings = report_terminal[0]
    fresh = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    receipt = json.loads(path.read_text())
    if fault == "active":
        receipt["calls"][0]["status"] = "reserved"
    elif fault == "unknown":
        receipt["calls"][0]["usage_exact"] = False
    elif fault == "exhausted":
        receipt["calls"][0]["usage"]["output_tokens"] = 128000
    elif fault == "host":
        receipt["host_client"] = "hermes"
    else:
        receipt["bounds"]["max_calls"] += 1
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="continuation_"):
        bind_origin(report_terminal)
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == fresh
    assert not provider.calls


def test_latest_failed_original_does_not_fall_through_to_older_funded_origin(report_terminal):
    backend, _root, origin, _carrier, job, _provider, _config, bindings = report_terminal[0]
    older = origin.model_copy(deep=True)
    older.id = "older-funded-original"
    older.started_at -= timedelta(days=1)
    older.completed_at -= timedelta(days=1)
    older.continuation["maintenance_scope"]["dispatch_generation"] = "carrier-generation"
    older.notes = [note.replace(job.id, "carrier-source-job") for note in older.notes]
    run(backend.structured_store.save_dream_run(older))
    prior = read_task_budget_receipt(backend.data_dir, bindings[1].task_scope)
    path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    receipt = json.loads(path.read_text())
    receipt["calls"][0]["usage"]["output_tokens"] = 128000
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="continuation_budget_exhausted"):
        bind_origin(report_terminal)
    assert read_task_budget_receipt(backend.data_dir, bindings[1].task_scope) == prior


def test_claim_keeps_original_history_and_uses_shared_takeover_ledger(prepared):
    data, child = prepared
    backend, _root, origin, *_ = data[0]
    before = _terminal_fixed(origin)
    context = claim(prepared)
    saved = run(backend.structured_store.get_dream_run(origin.id))
    assert _terminal_fixed(saved) == before
    assert saved.status == origin.status and saved.completed_at == origin.completed_at and saved.items == origin.items
    assert saved.continuation["slice_count"] == origin.continuation["slice_count"]
    ledger = saved.continuation["terminal_coverage_takeover"]
    assert ledger["slice_count"] == len(ledger["claims"]) == 1
    assert ledger["claims"][f"{child.id}:1"]["kind"] == "report_recheck"
    assert context["remaining_original_slices"] == 19
    with pytest.raises(ValueError, match="slice_already_claimed"):
        claim(prepared)


@pytest.mark.parametrize("owner", ["origin", "child"])
def test_checkpoint_dual_cas_rejects_concurrent_owner_write(prepared, owner):
    data, child = prepared
    backend, _root, origin, *_ = data[0]
    context = claim(prepared)
    identity = origin.id if owner == "origin" else child.id
    other = run(backend.structured_store.get_dream_run(identity))
    other.notes = list(other.notes or []) + ["Concurrent canonical owner must survive."]
    run(backend.structured_store.save_dream_run(other))
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(context["persist"](context["carrier"]))
    assert run(backend.structured_store.get_dream_run(identity)).notes[-1] == other.notes[-1]


@pytest.mark.parametrize("owner", ["origin", "child"])
def test_checkpoint_does_not_adopt_race_between_commit_and_readback(prepared, monkeypatch, owner):
    data, _child = prepared
    backend, _root, _origin, *_ = data[0]
    context = claim(prepared)
    canonical = backend.structured_store._canonical
    actual = canonical.apply_payload_transaction
    injected = []
    identity = context[owner if owner == "origin" else "carrier"].id

    def write_then_race(*args, **kwargs):
        result = actual(*args, **kwargs)
        if not injected:
            payload = json.loads(canonical.get_payload_json("dream_runs", identity))
            payload["notes"] = list(payload.get("notes") or []) + ["Write after commit must not become our expected checkpoint."]
            injected.append(True)
            actual(idempotency_key="isolated-report-readback-race", mutations=[{"operation": "upsert",
                "collection": "dream_runs", "entity_id": identity, "payload": payload}])
        return result

    monkeypatch.setattr(canonical, "apply_payload_transaction", write_then_race)
    with pytest.raises(CanonicalTransactionPreconditionError, match="readback_changed"):
        run(context["persist"](context["carrier"]))
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(context["persist"](context["carrier"]))
    assert run(backend.structured_store.get_dream_run(identity)).notes[-1].startswith("Write after commit")


@pytest.mark.parametrize("fault", ["version", "source_membership", "source_ledger", "payload"])
def test_pending_report_cannot_change_after_freeze(prepared, monkeypatch, fault):
    data, _child = prepared
    backend, _root, _origin, *_ = data[0]
    entry = data[1][3]
    canonical = backend.structured_store._canonical
    if fault == "source_ledger":
        original = backend.transcript_store.get_revision

        def drift(*args):
            revision = original(*args)
            return revision.model_copy(update={"controller_fixture_drift": True}) if revision else None

        monkeypatch.setattr(backend.transcript_store, "get_revision", drift)
    elif fault == "source_membership":
        sources = run(backend.structured_store.knowledge_store.list_sources(entry.id))
        source = sources[0]
        payload = json.loads(canonical.get_payload_json("knowledge_sources", source.id))
        payload["locator"] += "#changed"
        overwrite(canonical, "knowledge_sources", source.id, payload)
    else:
        payload = json.loads(canonical.get_payload_json("knowledge_entries", entry.id))
        if fault == "version":
            payload["module_path"] = list(payload["module_path"]) + ["changed"]
        else:
            payload["updated_at"] = "2099-01-01T00:00:00+00:00"
        overwrite(canonical, "knowledge_entries", entry.id, payload)
    with pytest.raises(ValueError, match="terminal_report_current_"):
        claim(prepared)


def test_all_earlier_source_claims_consume_same_original_slice_bound(prepared):
    data, _child = prepared
    backend, _root, origin, *_ = data[0]
    available = origin.continuation["max_slices"] - origin.continuation["slice_count"]
    origin.continuation["terminal_coverage_takeover"] = {"contract": TERMINAL_TAKEOVER_CONTRACT,
        "origin_fixed_sha256": _terminal_fixed(origin), "slice_count": available,
        "claims": {f"source-{index}": {"kind": "source_coverage"} for index in range(available)}}
    run(backend.structured_store.save_dream_run(origin))
    with pytest.raises(ValueError, match="original_slices_exhausted"):
        claim(prepared)


def test_proved_bookkeeping_at_both_limits_never_claims_slice_or_dispatches(prepared):
    data, _child = prepared
    backend, _root, origin, _oldcarrier, _job, provider, _config, bindings = data[0]
    context = claim(prepared)
    context["carrier"].continuation["completed_signal_indexes"] = [0]
    run(context["persist"](context["carrier"]))
    parent = run(backend.structured_store.get_dream_run(origin.id))
    takeover = parent.continuation["terminal_coverage_takeover"]
    maximum = parent.continuation["max_slices"] - parent.continuation["slice_count"]
    for index in range(maximum - len(takeover["claims"])):
        takeover["claims"][f"earlier-source-{index}"] = {"kind": "source_coverage"}
    takeover["slice_count"] = len(takeover["claims"])
    run(backend.structured_store.save_dream_run(parent))
    receipt_path = task_budget_receipt_path(backend.data_dir, bindings[0].task_scope)
    receipt = json.loads(receipt_path.read_text())
    receipt["calls"][0]["usage"]["output_tokens"] = 128000
    receipt_path.write_text(json.dumps(receipt))
    finalized = claim(prepared, bookkeeping_only=True)
    current = run(backend.structured_store.get_dream_run(origin.id))
    assert current.continuation["terminal_coverage_takeover"]["claims"] == takeover["claims"]
    assert finalized["remaining_original_slices"] == 0
    with pytest.raises(ValueError, match="bookkeeping_cannot_dispatch"):
        finalized["heartbeat"]()
    assert read_task_budget_receipt(backend.data_dir, bindings[0].task_scope) == receipt
    assert not provider.calls


@pytest.mark.parametrize("completed", [[True], [0, 0], [-1], [1]])
def test_manifest_progress_never_treats_invalid_indexes_as_completed(prepared, completed):
    data, child = prepared
    backend = data[0][0]
    child.continuation["completed_signal_indexes"] = completed
    run(backend.structured_store.save_dream_run(child))
    with pytest.raises(ValueError, match="terminal_report_progress_invalid"):
        claim(prepared)


def test_heartbeat_rechecks_lease_and_reflection_even_inside_cached_interval(prepared, monkeypatch):
    data, _child = prepared
    backend = data[0][0]
    alive = [True]
    monkeypatch.setattr("harness_mem.hook_background.heartbeat_background_worker", lambda *_a, **_k: alive[0])
    context = claim(prepared)
    context["heartbeat"]()
    alive[0] = False
    with pytest.raises(ValueError, match="background_worker_lease_lost"):
        context["heartbeat"]()
    alive[0] = True
    reflection = backend.reflection_job_store.get(context["carrier"].reflection_job_id)
    reflection.status = "completed"
    backend.reflection_job_store.save(reflection)
    with pytest.raises(ValueError, match="terminal_report_reflection_changed"):
        context["heartbeat"]()


def test_terminal_bookkeeping_accepts_closed_same_reflection_without_resurrection(prepared):
    data, _child = prepared
    backend = data[0][0]
    context = claim(prepared)
    reflection = backend.reflection_job_store.get(context["carrier"].reflection_job_id)
    reflection.status = "completed"
    backend.reflection_job_store.save(reflection)
    child = context["carrier"].model_copy(deep=True)
    child.status = "failed"
    run(context["persist"](child))
    assert backend.reflection_job_store.get(reflection.id).status == "completed"
    assert run(backend.structured_store.get_dream_run(child.id)).status == "failed"


def test_one_report_contract_attempt_cannot_start_again_after_terminal_child(prepared):
    data, _child = prepared
    backend = data[0][0]
    context = claim(prepared)
    child = context["carrier"]
    child.status = "failed"
    run(context["persist"](child))
    reflection = backend.reflection_job_store.get(child.reflection_job_id)
    reflection.status = "failed"
    backend.reflection_job_store.save(reflection)
    with pytest.raises(ValueError, match="contract_already_attempted"):
        bind_origin(data)


def test_completed_refinement_requires_exact_current_final_bytes(report_terminal):
    result = tick(report_terminal, report_origin_run_id=report_terminal[0][2].id)
    assert result["status"] == "completed", result
    backend, root, origin, *_ = report_terminal[0]
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    current_origin = run(backend.structured_store.get_dream_run(origin.id))
    run(module._validate_manifest(backend, current_origin, child, project_root=root))
    reports = [row for row in run(backend.structured_store.knowledge_store.list_entries("demo")) if row.source_report]
    successor = reports[0]
    changed = successor.source_report.model_copy(update={"text": successor.source_report.text + " Extra same-account claim."})
    payload = copy.deepcopy(successor.model_dump(mode="json"))
    payload["source_report"] = changed.model_dump(mode="json")
    payload["title"], payload["statement"] = changed.render_title(), changed.render_statement()
    overwrite(backend.structured_store._canonical, "knowledge_entries", successor.id, payload)
    # Same ID, attribution and valid rendered structure cannot substitute for
    # the exact independently verified final output.
    assert module._account(successor) == module._account(successor.model_copy(update={"source_report": changed}))
    with pytest.raises(ValueError, match="original_successor_changed"):
        run(module._validate_manifest(backend, current_origin, child, project_root=root))


@pytest.mark.parametrize("fault", [None, "wrong_run", "wrong_id", "missing_marker",
    "invalid_marker", "uppercase_marker", "nonstring_marker", "legacy_owner_new_marker"])
def test_original_inventory_receipt_selects_only_exact_canonical_owner(fault):
    from harness_mem.commands.dream_source_coverage import _original_final_output_bindings
    run_id, source_id = "receipt-run", "receipt-source"
    owner_run = "other-run" if fault == "wrong_run" else run_id
    owner_source = "other-source" if fault == "wrong_id" else source_id
    row = {"owner_candidate_id": str(uuid5(NAMESPACE_URL,
        f"harness-mem:dream-candidate:{owner_run}:{owner_source}")),
        "report_preservation_inventory_sha256": "a" * 64}
    if fault == "missing_marker":
        row.pop("report_preservation_inventory_sha256")
    elif fault in {"invalid_marker", "uppercase_marker", "nonstring_marker"}:
        row["report_preservation_inventory_sha256"] = {
            "invalid_marker": "g" * 64, "uppercase_marker": "A" * 64,
            "nonstring_marker": 64}[fault]
    elif fault == "legacy_owner_new_marker":
        row["owner_candidate_id"] = "dream:" + source_id
    origin = SimpleNamespace(id=run_id, notes=["dream verification receipt: "
        + json.dumps({"final_output_bindings": [row]})])
    assert _original_final_output_bindings(origin, source_id) == ([row] if fault is None else [])


@pytest.mark.parametrize("fault", [None, "other_source", "canonical_without_marker", "invalid_marker"])
def test_historical_receipt_remains_exact_without_new_marker(fault):
    from harness_mem.commands.dream_source_coverage import _original_final_output_bindings
    row = {"owner_candidate_id": "dream:" + ("other-source" if fault == "other_source" else "source")}
    if fault == "canonical_without_marker":
        row["owner_candidate_id"] = str(uuid5(NAMESPACE_URL, "harness-mem:dream-candidate:run:source"))
    elif fault == "invalid_marker":
        row["report_preservation_inventory_sha256"] = None
    origin = SimpleNamespace(id="run", notes=["dream verification receipt: "
        + json.dumps({"final_output_bindings": [row]})])
    assert _original_final_output_bindings(origin, "source") == ([row] if fault is None else [])


@pytest.mark.parametrize("fault", ["wrong_run", "missing_marker", "old_owner_new_marker"])
def test_completed_report_cannot_resume_with_rebound_final_receipt(report_terminal, fault):
    result = tick(report_terminal, report_origin_run_id=report_terminal[0][2].id)
    assert result["status"] == "completed", result
    backend, root, origin, *_ = report_terminal[0]
    child = run(backend.structured_store.get_dream_run(result["run_id"]))
    current_origin = run(backend.structured_store.get_dream_run(origin.id))
    run(module._validate_manifest(backend, current_origin, child, project_root=root))
    source_id = child.continuation["target_ids"][0]
    changed = False
    for index, note in enumerate(child.notes):
        prefix = "dream verification receipt: "
        if not note.startswith(prefix):
            continue
        receipt = json.loads(note[len(prefix):])
        for row in receipt.get("final_output_bindings") or []:
            if "report_preservation_inventory_sha256" not in row:
                continue
            assert len(row["report_preservation_inventory_sha256"]) == 64
            if fault == "wrong_run":
                row["owner_candidate_id"] = str(uuid5(NAMESPACE_URL,
                    f"harness-mem:dream-candidate:another-run:{source_id}"))
            elif fault == "missing_marker":
                row.pop("report_preservation_inventory_sha256")
            else:
                row["owner_candidate_id"] = "dream:" + source_id
            changed = True
        child.notes[index] = prefix + json.dumps(receipt)
    assert changed
    with pytest.raises(ValueError, match="terminal_report_successor_receipt_changed"):
        run(module._validate_manifest(backend, current_origin, child, project_root=root))
