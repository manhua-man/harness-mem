"""Regression for the three recovered natural v9 validation failures.

Controlled inputs demonstrate those validator rules; they are not the lost
native response bytes. No native program, Hook, model, or live store is used.
"""
import json

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.models import (
    CandidateVerificationDecision, DREAM_SOURCE_RECHECK_CONTRACT,
    SourceClassificationDecision,
)
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.commands.dream_assimilation import (
    DreamAssimilationCandidate, build_dream_maintenance_plan, prepare_dream_assimilation,
)
from harness_mem.core.schemas.knowledge import KnowledgeEntry
from test_dream_stage4_contract import _result


def _packet():
    return {"points": [{"candidate_index": 0, "semantic_support": "supported",
        "future_scope": "unclear", "source_use": "unclear",
        "reason": "An enduring claim has a required qualifier after a temporary receipt.",
        "scope_segments": [
            {"text": "Cache remains local.", "source_support": "supported", "source_use": "reusable_knowledge",
             "future_scope": "durable", "standalone": False, "content_role": "claim"},
            {"text": " Ran one check.", "source_support": "supported", "source_use": "task_context",
             "future_scope": "session_only", "standalone": True, "content_role": "temporary_context"},
            {"text": " Within this platform only.", "source_support": "supported", "source_use": "reusable_knowledge",
             "future_scope": "durable", "standalone": False, "content_role": "qualifier"},
        ],
        "claim_units": [{"first_segment": 0, "end_segment_exclusive": 3, "standalone": True,
                         "source_support": "supported", "source_use": "reusable_knowledge", "future_scope": "durable"}],
    }]}


def test_classification_inventory_can_span_temporary_context_but_cannot_write(tmp_path):
    packet = _packet()
    packet["points"][0]["scope_segments"][0]["text"] = "Scoped cache\n" + packet["points"][0]["scope_segments"][0]["text"]
    classified = SourceClassificationDecision.model_validate(packet)
    decision = classified.as_verification()
    unit = decision.points[0].claim_units[0]
    assert unit.retained_text == "" and not unit.selected_for_retention
    assert unit.excluded_segments == []
    text = "".join(item["text"] for item in packet["points"][0]["scope_segments"])
    entry = KnowledgeEntry(id="classification-only", project_name="demo", title="Scoped cache", statement=text.removeprefix("Scoped cache\n"), module_path=["cache"])
    assert text == entry.title + "\n" + entry.statement
    prepared = prepare_dream_assimilation(project_name="demo", project_root=tmp_path, run_id="inventory", signal_kind="stale",
        candidates=[DreamAssimilationCandidate(candidate_id="classification-only", entry=entry, sources=(),
            semantic_support="supported", future_scope="unclear", verification_reason="Classification inventory only.",
            source_excerpts=(), scope_verification=decision.points[0], verification_contract=DREAM_SOURCE_RECHECK_CONTRACT)])
    assert build_dream_maintenance_plan(prepared)[0]["disposition"] == "no_write"


@pytest.mark.parametrize("field,value", [("retained_text", "rewritten"), ("selected_for_retention", True),
    ("excluded_segments", [1]), ("title_start", 0)])
def test_native_source_inventory_cannot_request_literal_edit_authority(field, value):
    packet = _packet()
    packet["points"][0]["claim_units"][0][field] = value
    with pytest.raises(ValidationError) as caught:
        SourceClassificationDecision.model_validate(packet)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("field,value", [("replacement_items", []), ("report_outputs", []),
    ("output_verifications", []), ("update_meaning_judgment", None), ("literal_edit_contract", None)])
def test_native_source_point_cannot_supply_proposals_or_final_judgments(field, value):
    packet = _packet()
    packet["points"][0][field] = value
    with pytest.raises(ValidationError) as caught:
        SourceClassificationDecision.model_validate(packet)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("selected,contract", [(True, None), (False, "dream-existing-literal-edit-v1")])
def test_retention_proof_still_rejects_a_temporary_bridge(selected, contract):
    packet = _packet()
    point = packet["points"][0]
    point["literal_edit_contract"] = contract
    point["claim_units"][0].update(selected_for_retention=selected,
        retained_text="".join(part["text"] for part in point["scope_segments"]))
    with pytest.raises(ValidationError, match="cannot bridge a temporary-context"):
        CandidateVerificationDecision.model_validate(packet)


def test_legacy_retained_text_must_still_match_its_exact_projection():
    packet = _packet()
    packet["points"][0]["claim_units"][0]["retained_text"] = "A fabricated retained claim."
    with pytest.raises(ValidationError, match="retained_text must exactly project"):
        CandidateVerificationDecision.model_validate(packet)


def test_inventory_range_must_still_be_bound_to_existing_segments():
    packet = _packet()
    packet["points"][0]["claim_units"][0]["end_segment_exclusive"] = 4
    with pytest.raises(ValidationError, match="extends beyond"):
        SourceClassificationDecision.model_validate(packet)


def test_source_json_schema_cannot_request_unused_proof_fields():
    schema = json.dumps(SourceClassificationDecision.model_json_schema())
    for name in ("retained_text", "selected_for_retention", "excluded_segments", "replacement_items",
                 "output_verifications", "update_meaning_judgment", "literal_edit_contract"):
        assert name not in schema


@pytest.mark.parametrize("host", ["codex", "claude-code", "cursor", "grok", "hermes", "opencode", "antigravity"])
def test_every_host_uses_source_transport_only_for_source_classification(tmp_path, monkeypatch, host):
    provider = HostStructuredCliProvider(host_client=host, executable="fictional", timeout_seconds=30)
    seen = []
    def run(manifest, **kwargs):
        seen.append(kwargs["decision_model"])
        packet = _packet()
        if manifest["contract_version"] != DREAM_SOURCE_RECHECK_CONTRACT:
            packet["points"][0]["claim_units"] = []
        return _result(kwargs["decision_model"].model_validate(packet))
    monkeypatch.setattr(provider, "_run", run)
    result = provider.verify({"contract_version": DREAM_SOURCE_RECHECK_CONTRACT}, runtime_dir=tmp_path)
    assert isinstance(result.decision, CandidateVerificationDecision)
    assert result.decision.points[0].claim_units[0].retained_text == ""
    provider.verify({"contract_version": "final-knowledge-scope-v1"}, runtime_dir=tmp_path)
    assert seen == [SourceClassificationDecision, CandidateVerificationDecision]


def test_hermes_native_invocation_builder_accepts_source_inventory_contract(tmp_path, monkeypatch):
    from harness_mem.autonomous.executors import host_structured_cli as module
    captured = {}
    class CapturedBeforeTransport(Exception):
        pass
    def build(**kwargs):
        captured.update(kwargs)
        captured["schema"] = json.loads(kwargs["schema_path"].read_text(encoding="utf-8"))
        raise CapturedBeforeTransport
    monkeypatch.setattr(module, "_build_host_invocation", build)
    monkeypatch.setattr(module, "_assert_runtime_isolated", lambda *_args: None)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("native transport forbidden"))
    provider = HostStructuredCliProvider(host_client="hermes", executable="fictional", timeout_seconds=30)
    with pytest.raises(CapturedBeforeTransport):
        provider._run_native_body({}, runtime_dir=tmp_path / "runtime", heartbeat=None,
            decision_model=SourceClassificationDecision, prompt="Original complete classification request.",
            temporary_prefix="verification-", error_label="verification")
    assert captured["host_client"] == "hermes"
    assert captured["prompt"].startswith("Original complete classification request.")
    assert '"claim_units"' in captured["prompt"]
    assert '"source_support"' in captured["prompt"]
    assert "retained_text" not in captured["prompt"]
    assert "retained_text" not in json.dumps(captured["schema"])


def test_source_inventory_checkpoint_resumes_without_repeating_native_classification(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone
    import harness_mem.commands.dream as module
    from harness_mem.autonomous.models import AssimilationDecision
    from harness_mem.storage.local_memory_backend import LocalMemoryBackend
    from test_dream_stage4_contract import _publish

    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(module, "_now", lambda: clock[0])
    packet = _packet()
    statement = "".join(part["text"] for part in packet["points"][0]["scope_segments"])
    entry = KnowledgeEntry(id="inventory-resume", project_name="demo", title="Scoped cache", statement=statement, module_path=["cache"])
    root, _, _ = _publish(backend, entry)
    packet["points"][0]["scope_segments"][0]["text"] = entry.title + "\n" + packet["points"][0]["scope_segments"][0]["text"]
    class Provider:
        name = "inventory-resume-fixture"
        phases = []
        def verify(self, manifest, **kwargs):
            self.phases.append("verify")
            assert manifest["candidates"][0]["scope_text"] == entry.title + "\n" + entry.statement
            clock[0] += timedelta(seconds=121)
            return _result(SourceClassificationDecision.model_validate(packet).as_verification())
        def assimilate(self, manifest, **kwargs):
            self.phases.append("assimilate")
            unit = manifest["maintenance_candidates"][0]["scope_verification"]["claim_units"][0]
            assert unit["retained_text"] == "" and not unit["selected_for_retention"]
            return _result(AssimilationDecision.model_validate({"points": [{
                "candidate_id": manifest["verified_candidates"][0]["candidate_id"],
                "disposition": "no_write", "matched_truth_handles": [],
                "reason": "This fixture retains its complete source without proposing a mutation."
            }]}))
    provider = Provider()
    try:
        first = asyncio.run(module.dream_once(backend, project_name="demo", project_root=root,
            semantic_provider=provider, reflection_job_id="classification-checkpoint",
            deadline=clock[0] + timedelta(seconds=120)))
        assert first.status == "continuing" and first.items == []
        saved = first.continuation["verification"][entry.id]["point"]["claim_units"][0]
        assert saved["retained_text_present"] is False and "retained_text" not in saved
        second = asyncio.run(module.dream_once(backend, project_name="demo", project_root=root,
            semantic_provider=provider, reflection_job_id="classification-checkpoint",
            deadline=clock[0] + timedelta(seconds=120)))
        assert provider.phases == ["verify", "assimilate"]
        assert second.execution_status == "completed" and second.resolution_status == "unresolved"
        assert len(second.items) == 1 and second.items[0].final_action == "rejected"
    finally:
        asyncio.run(backend.close())
