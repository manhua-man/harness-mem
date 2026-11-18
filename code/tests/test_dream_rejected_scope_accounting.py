"""Rejected final scope stays unresolved and cannot inherit stale coverage."""
import json
from datetime import datetime, timedelta, timezone

from test_dream_stage4_contract import (
    backend as backend, _run, _publish, _ConfirmProvider,
)
from test_dream_rendered_report_proposals import RenderedProvider, invoke, report_case as report_case
from harness_mem.commands import dream
from harness_mem.core.schemas.dream_run import DreamRun, DreamItem
from harness_mem.core.schemas.knowledge import KnowledgeEntry


def test_durable_report_body_with_mixed_final_scope_is_unresolved_without_mutation(report_case):
    backend, _root, _report, before, _output, _retained = report_case
    provider = RenderedProvider(report_case, failure="defer")
    run = invoke(report_case, provider)
    assert provider.phases == ["source", "rendered", "proposal"]
    store = backend.structured_store.knowledge_store
    after = _run(store.get_entry(before.id, project_name="demo"))
    assert before.model_dump() == after.model_dump()
    assert run.resolution_status == "unresolved"
    assert before.id in run.continuation["unresolved_scope"]
    assert run.items[0].final_action == "rejected"
    assert run.items[0].result["truth_change"] == "none"
    assert before.id not in _run(dream._scope_upgrade_coverage(backend, "demo"))
    records = _run(dream._scope_upgrade_coverage(backend, "demo", include_rejections=True))
    assert records[before.id]["scope_status"] != "source_scope_durable"
    assert records[before.id]["fingerprint"] == dream._scope_fingerprint(after)


def test_new_negative_current_fingerprint_supersedes_old_durable_coverage(backend):
    entry = KnowledgeEntry(id="coverage-target", project_name="demo", title="Cache rule",
                           statement="Cache stays local.", module_path=["cache"])
    root, _path, _entries = _publish(backend, entry)
    now = datetime.now(timezone.utc)
    fingerprint = dream._scope_fingerprint(entry)
    for index, status in enumerate(["source_scope_durable", "final_scope_or_proposal_rejected"]):
        _run(backend.structured_store.save_dream_run(DreamRun(
            id=f"coverage-run-{index}", project_name="demo", started_at=now + timedelta(seconds=index),
            status="completed", trigger_source="agent", notes=["dream scope_partition_v3: " + json.dumps({entry.id: {
                "fingerprint": fingerprint, "scope_status": status, "semantic_support": "supported",
            }})],
        )))
    assert _run(dream._scope_upgrade_coverage(backend, "demo")) == {}
    assert _run(dream._scope_upgrade_coverage(backend, "demo", include_rejections=True))[entry.id]["scope_status"] == "final_scope_or_proposal_rejected"
    signals = _run(dream._detect_separated_rechecks(backend, project_name="demo", project_root=root))
    assert any(signal.target_ids == (entry.id,) and signal.cause_id == "scope_partition_v3" for signal in signals)


def test_contract_upgrade_recovers_omitted_rejection_without_replaying_applied_or_changed_groups(backend):
    entries = [KnowledgeEntry(id=f"resume-{index}", project_name="demo", title=f"Rule {index}",
                             statement=f"Cache {index} stays local.", module_path=[f"cache-{index}"])
               for index in range(3)]
    root, _path, _entries = _publish(backend, *entries)
    fingerprints = {entry.id: dream._scope_fingerprint(entry) for entry in entries}
    fingerprints[entries[2].id] = "old-content-before-external-change"
    scope = {"trigger_id": "same-original-trigger", "dispatch_generation": "same-original-generation"}
    legacy = DreamRun(
        id="legacy-v10-continuation", project_name="demo", status="continuing", trigger_source="agent",
        items=[DreamItem(source_kind="knowledge_stale", source_id=entry.id, risk="medium", proposed_action="replace",
                         final_action="applied" if index == 1 else "rejected",
                         reason="Earlier contract result, retained without replaying writes.",
                         result={"truth_change": "verification_refreshed" if index == 1 else "none"})
               for index, entry in enumerate(entries)],
        notes=["dream target snapshots: " + json.dumps([
            {"entry_id": identity, "fingerprint": fingerprint} for identity, fingerprint in fingerprints.items()
        ])],
        continuation={"verification_contract": "dream-source-recheck-v10", "slice_count": 2,
                      "completed_signal_indexes": [0, 1, 2], "unresolved_scope": {},
                      "maintenance_scope": scope, "task_budget": {"reserved_calls": 7, "unknown_calls": 0},
                      "signals": [dict(kind="stale", target_ids=[entry.id], proposed_action="replace", risk="medium",
                                       reason="Original source-bound frozen target.", cause_id="scope_partition_v3")
                                  for entry in entries]},
    )
    provider = _ConfirmProvider()
    run = _run(dream._dream_once(backend, project_name="demo", project_root=root,
                               semantic_provider=provider, _resume=legacy, _run_id=legacy.id))
    assert provider.calls == 1
    assert {row["target_snapshot"]["id"] for manifest in provider.manifests for row in manifest["candidates"]} == {entries[0].id}
    assert len([item for item in run.items if item.source_id == entries[1].id]) == 1
    assert len([item for item in run.items if item.source_id == entries[2].id]) == 1
    assert entries[2].id in run.continuation["unresolved_scope"]
    assert run.continuation["maintenance_scope"] == scope
    assert run.continuation["task_budget"] == {"reserved_calls": 7, "unknown_calls": 0}
