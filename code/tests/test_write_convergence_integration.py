"""Cross-owner checks use temporary stores and an explicit fake native adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from test_dream_stage4_contract import _publish, _ConfirmProvider
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.task_budget import (
    NativeDispatchResult, bind_maintenance_task, fake_input_capability,
    fake_output_limit_surface, read_task_budget_receipt,
)
from harness_mem.autonomous.provider import ProviderError
from harness_mem.autonomous.worker import _invoke_provider
from harness_mem.commands.dream import dream_once
from harness_mem.commands.dream_assimilation import _source_refs
from harness_mem.commands.dream_assimilation import (
    DreamAssimilationCandidate, prepare_dream_assimilation,
    build_dream_maintenance_plan, apply_dream_assimilation,
)
from harness_mem.autonomous.models import (
    CandidateVerificationPoint, UpdateMeaningJudgment, SourceClassificationDecision,
    SourceClassificationPoint, DREAM_SOURCE_RECHECK_CONTRACT,
)
from harness_mem.commands.separated_assimilation import target_version
from harness_mem.commands.knowledge_assimilation import record_assimilation_result
from harness_mem.commands.separated_assimilation import _current_truth_handles
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import KnowledgeCandidate, KnowledgeEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    value = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(value.init())
    try:
        yield value
    finally:
        asyncio.run(value.close())


def test_native_source_and_reopened_dream_slices_share_one_budget(backend, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A real native transport is forbidden in this integration check")

    monkeypatch.setattr("harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen", forbidden)
    monkeypatch.setattr("harness_mem.autonomous.executors.codex_app_server.CodexAppServer.run", forbidden)
    entries = [KnowledgeEntry(id=f"budget-{index}", project_name="demo",
        title=f"Cache rule {index}", statement=f"Cache rule {index} stays local.",
        module_path=["cache"]) for index in range(5)]
    root, _, _ = _publish(backend, *entries)
    config = MergedConfig(task_model_budget_max_calls=3, task_model_budget_max_seconds=1200,
        task_model_budget_max_input_tokens=100, task_model_budget_max_output_tokens=20,
        task_model_budget_host_max_output_tokens=5)
    scope = {"trigger_id": "original-source-turn", "dispatch_generation": "original-generation"}
    binding = bind_maintenance_task(data_dir=backend.data_dir, host_client="fake-host", config=config, **scope)

    class NativeFake(HostStructuredCliProvider):
        manifest = None

        def verify(self, manifest, **kwargs):
            self.manifest = manifest
            return super().verify(manifest, **kwargs)

    def make_provider():
        provider = NativeFake(host_client="fake-host", executable="FORBIDDEN_NATIVE")

        def fake_native(request):
            decision = _ConfirmProvider().verify(provider.manifest, runtime_dir=backend.data_dir).decision
            if provider.manifest.get("contract_version") == DREAM_SOURCE_RECHECK_CONTRACT:
                decision = SourceClassificationDecision(points=[SourceClassificationPoint.model_validate({
                    key: getattr(point, key) for key in SourceClassificationPoint.model_fields
                }) for point in decision.points])
            return decision, NativeDispatchResult(status="completed", input_tokens=10,
                output_tokens=1, duration_seconds=1, usage_exact=True)

        provider.bind_task_budget(binding, phase="source", slice_id="source-first",
            input_capability=fake_input_capability("fake-host", max_complete_input_tokens=10),
            output_limit_surface=fake_output_limit_surface("fake-host"),
            explicit_fake_transport=fake_native)
        return provider

    first_provider = make_provider()
    _invoke_provider(first_provider, "verify", {"candidates": []},
        runtime_dir=backend.data_dir / "source-runtime", heartbeat=None,
        phase="source", slice_id="source-first")
    first = asyncio.run(dream_once(backend, project_name="demo", project_root=root,
        config=config, reflection_job_id="natural-source-maintenance", semantic_provider=first_provider,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1), maintenance_scope=scope))
    assert first.status == "continuing"
    assert len(first.items) == 4
    assert first.continuation["maintenance_scope"] == scope
    second_provider = make_provider()
    second = asyncio.run(dream_once(backend, project_name="demo", project_root=root,
        config=config, resume_run_id=first.id, semantic_provider=second_provider,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        maintenance_scope={"trigger_id": "later-stop", "dispatch_generation": "later-generation"}))
    assert second.id == first.id
    assert second.status == "completed"
    assert second.execution_status == "completed" and second.resolution_status == "resolved"
    assert len(second.items) == 5
    assert all(item.final_action == "applied" for item in second.items)
    assert second.continuation["maintenance_scope"] == scope
    ledger = read_task_budget_receipt(backend.data_dir, binding.task_scope)
    assert [call["phase"] for call in ledger["calls"]] == ["source", "dream", "dream"]
    with pytest.raises(ProviderError) as error:
        second_provider.verify({"candidates": []}, runtime_dir=backend.data_dir / "new-runtime")
    assert error.value.failure_reason == "call_budget_exhausted"
    assert len(read_task_budget_receipt(backend.data_dir, binding.task_scope)["calls"]) == 3


def test_bounded_truth_discovery_keeps_explicit_targets_and_honest_total(backend):
    entries = [KnowledgeEntry(id=f"rank-{index:03}", project_name="demo",
        title=f"Local cache rule {index}", statement=f"Local cache rule {index} stays signed.",
        module_path=["cache"]) for index in range(80)]
    root, _, _ = _publish(backend, *entries)
    candidate = KnowledgeCandidate(project_name="demo", candidate_type="memory",
        statement="An unrelated topic has no established predecessor.",
        assimilation_target_ids=["rank-079"])
    discovery = {}
    handles, rows = asyncio.run(_current_truth_handles(backend, project_name="demo",
        project_root=str(root), candidates=[candidate], discovery=discovery))
    assert len(rows) <= 33
    assert "rank-079" in handles.values()
    assert discovery["current_count"] == 80
    assert discovery["offered_count"] == len(rows)
    assert discovery["next_offset"] == 32
    assert discovery["absence_proved"] is False


def test_shared_confirmation_needs_a_final_judgment_and_failure_stays_retryable(backend):
    original = KnowledgeEntry(id="confirm-boundary", project_name="demo", title="Cache locality",
        statement="The cache stays local.", module_path=["cache"])
    root, _, rows = _publish(backend, original)
    store = backend.structured_store.knowledge_store
    refs = _source_refs(asyncio.run(store.list_sources(original.id)))
    candidate = KnowledgeCandidate(project_name="demo", candidate_type="memory", statement=original.statement)
    point = {"disposition": "confirm", "matched_truth_ids": [original.id],
             "reason": "Confirm exactly the currently scoped cache rule."}
    for _ in range(2):
        with pytest.raises(ValueError, match="final semantic judgment"):
            asyncio.run(record_assimilation_result(backend, candidate=candidate, point=point,
                project_root=root, source_refs=refs))
        assert candidate.status == "pending"
    assert asyncio.run(store.get_entry(original.id, project_name="demo")).to_dict() == rows[0].to_dict()


@pytest.mark.parametrize("meaning_state", ["missing", "drops_applicable_meaning", "unclear",
                                          "wrong_version", "output_missing", "output_disagrees"])
def test_dream_never_synthesizes_a_preservation_verdict(backend, meaning_state):
    original = KnowledgeEntry(id="preserve-boundaries", project_name="demo", title="Cache policy",
        statement="The cache stays local. The rollout approval is undecided.", module_path=["cache"])
    root, _, rows = _publish(backend, original)
    current = rows[0]
    item = {"title": "Cache locality", "statement": "The cache stays local.",
            "topic_path": ["cache"], "claim_kind": "implementation_fact"}
    version = target_version({"title": current.title, "statement": current.statement,
                              "topic_path": current.module_path, "source_report": None})
    relationship = (meaning_state if meaning_state in {"drops_applicable_meaning", "unclear"}
                    else "preserves_applicable_meaning")
    meaning = None if meaning_state == "missing" else UpdateMeaningJudgment(
        relationship=relationship, successor_statements=[item["statement"]],
        predecessor_statements=[current.statement],
        predecessor_versions=["wrong-version" if meaning_state == "wrong_version" else version],
        basis="This isolated verdict must not be replaced by an invented runtime acceptance.")
    output_meaning = None if meaning_state == "output_missing" else meaning
    if meaning_state == "output_disagrees":
        output_meaning = meaning.model_copy(update={"relationship": "drops_applicable_meaning"})

    def segment(text):
        return {"text": text, "source_use": "standing_decision", "future_scope": "durable",
                "standalone": True, "content_role": "claim", "source_support": "supported"}

    point = CandidateVerificationPoint.model_validate({
        "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
        "source_use": "standing_decision", "reason": "The proposed sentence alone is supported.",
        "scope_segments": [segment(current.title + "\n" + current.statement)],
        "replacement_items": [item],
        "update_meaning_judgment": meaning.model_dump() if meaning else None,
        "output_verifications": [{"semantic_support": "supported", "future_scope": "durable",
            "source_use": "standing_decision", "reason": "The final new sentence was independently checked.",
            "scope_segments": [segment(item["title"] + "\n" + item["statement"])],
            "update_meaning_judgment": output_meaning.model_dump() if output_meaning else None}],
    })
    sources = asyncio.run(backend.structured_store.knowledge_store.list_sources(current.id))
    prepared = prepare_dream_assimilation(project_name="demo", project_root=root, run_id="meaning-refusal",
        signal_kind="stale", candidates=[DreamAssimilationCandidate(candidate_id="meaning-target",
            entry=current, sources=tuple(sources), semantic_support="supported", future_scope="durable",
            verification_reason=point.reason, source_excerpts=(), scope_verification=point)])
    plan = build_dream_maintenance_plan(prepared)
    asyncio.run(apply_dream_assimilation(backend, prepared=prepared, plan=plan))
    assert plan[0]["disposition"] == "no_write"
    assert [row.to_dict() for row in asyncio.run(
        backend.structured_store.knowledge_store.list_entries("demo"))] == [current.to_dict()]


def test_dream_production_refusal_records_no_unknown_dispatch(backend, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No native production process may start")

    monkeypatch.setattr("harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen", forbidden)
    monkeypatch.setattr("harness_mem.autonomous.executors.codex_app_server.CodexAppServer.run", forbidden)
    entry = KnowledgeEntry(id="production-closed", project_name="demo", title="Cache locality",
        statement="The cache stays local.", module_path=["cache"])
    root, _, rows = _publish(backend, entry)
    config = MergedConfig(task_model_budget_max_calls=3, task_model_budget_max_seconds=1200,
        task_model_budget_max_input_tokens=100, task_model_budget_max_output_tokens=20,
        task_model_budget_host_max_output_tokens=5)
    provider = HostStructuredCliProvider(host_client="codex", executable="FORBIDDEN_NATIVE")
    with pytest.raises(ProviderError) as error:
        asyncio.run(dream_once(backend, project_name="demo", project_root=root,
            config=config, semantic_provider=provider))
    assert error.value.failure_reason == "host_output_limit_unsupported"
    run = asyncio.run(backend.structured_store.list_dream_runs("demo", limit=1))[0]
    assert run.status == "failed"
    assert run.continuation["failure_reason"] == "host_output_limit_unsupported"
    assert run.continuation["task_budget"]["native_dispatch"] == "refused_before_transport"
    receipt = next(note for note in run.notes if note.startswith("dream verification receipt: "))
    evidence = json.loads(receipt.removeprefix("dream verification receipt: "))
    assert evidence["native_dispatch"] == "refused_before_transport"
    assert evidence["usage_unknown"] is False
    assert evidence["results"] == evidence["native_attempts"] == []
    assert [row.to_dict() for row in asyncio.run(
        backend.structured_store.knowledge_store.list_entries("demo"))] == [rows[0].to_dict()]


def test_dream_cannot_inject_an_unverified_delete_plan(backend):
    entry = KnowledgeEntry(id="no-injected-delete", project_name="demo", title="Cache locality",
        statement="The cache stays local.", module_path=["cache"])
    root, _, rows = _publish(backend, entry)
    sources = asyncio.run(backend.structured_store.knowledge_store.list_sources(entry.id))
    prepared = prepare_dream_assimilation(project_name="demo", project_root=root,
        run_id="no-delete-injection", signal_kind="stale", candidates=[DreamAssimilationCandidate(
            candidate_id="D1", entry=rows[0], sources=tuple(sources), semantic_support="supported",
            future_scope="durable", verification_reason="This source does not authorize deletion.",
            source_excerpts=())])
    plan = build_dream_maintenance_plan(prepared)
    assert plan[0]["disposition"] == "no_write"
    forged = [{**plan[0], "disposition": "reject", "matched_truth_ids": [entry.id]}]
    with pytest.raises(ValueError, match="complete verified maintenance plan"):
        asyncio.run(apply_dream_assimilation(backend, prepared=prepared, plan=forged))
    assert [row.to_dict() for row in asyncio.run(
        backend.structured_store.knowledge_store.list_entries("demo"))] == [rows[0].to_dict()]
