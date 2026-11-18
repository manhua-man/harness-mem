"""Confirmation keeps persistent source identities separate from semantic context."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from test_dream_complete_user_context import captured as captured
from test_dream_stage4_contract import _ConfirmProvider
from harness_mem.autonomous.models import CandidateVerificationPoint
from harness_mem.commands.dream import dream_once
from harness_mem.commands.dream_assimilation import (
    DREAM_SOURCE_RECHECK_CONTRACT, DreamAssimilationCandidate, apply_dream_assimilation,
    build_dream_maintenance_plan, dream_scope_text, prepare_dream_assimilation,
)
from harness_mem.commands.evidence_admission import reopen_dream_knowledge_sources
from harness_mem.core.schemas import KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.knowledge import AssimilationDecision
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef


def run(value):
    return asyncio.run(value)


def publish(backend, entry, refs):
    store = backend.structured_store.knowledge_store
    fixture = KnowledgeCandidate(id="confirm-publish", project_name="demo", candidate_type="memory", statement="Fixture.")
    run(store.save_candidate(fixture))
    run(store.apply_current_change(candidate_before=fixture,
        candidate_after=fixture.model_copy(update={"status": "assimilated"}),
        decision=AssimilationDecision(id="confirm-publish", project_name="demo", candidate_id=fixture.id,
            disposition="add", canonical_truth_ids=[entry.id], reason="Isolated source fixture."),
        added_entries=[entry], predecessor_entries=[], source_refs_by_entry={entry.id: refs}))
    run(store.cleanup_candidate(fixture.id))


@pytest.fixture
def confirmation(captured):
    backend, root, _snapshot, _rendering, sources = captured
    entry = KnowledgeEntry(id="old-knowledge", project_name="demo", title="Daily entry repair",
        statement="Repair the daily entry and preserve explicit corrections; do not add acceptance rituals.",
        module_path=["daily-entry"])
    publish(backend, entry, [ProjectKnowledgeSourceRef(label="Original user anchor", target=source.locator,
        kind="user_statement", digest=source.content_sha256) for source in sources])
    return backend, root, entry


def prepare(data, *, original_sources=True, final_scope=True):
    backend, root, entry = data
    originals = tuple(run(backend.structured_store.knowledge_store.list_sources(entry.id)))
    validation, reopened, effective = run(reopen_dream_knowledge_sources(
        backend, project_name="demo", project_root=root, sources=originals))
    assert validation.verification_outcome == "verified"
    point = CandidateVerificationPoint.model_validate({
        "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
        "source_use": "standing_decision", "reason": "Complete original evidence supports this exact scoped repair requirement.",
        "scope_segments": [{"text": dream_scope_text(entry), "source_use": "standing_decision",
            "future_scope": "durable", "standalone": True, "content_role": "claim", "source_support": "supported"}],
    })
    candidate = DreamAssimilationCandidate(candidate_id="confirm-candidate", entry=entry, sources=effective,
        semantic_support="supported", future_scope="durable", verification_reason=point.reason,
        source_excerpts=(), scope_verification=point if final_scope else None,
        verification_contract=DREAM_SOURCE_RECHECK_CONTRACT,
        original_sources=originals if original_sources else None)
    prepared = prepare_dream_assimilation(project_name="demo", project_root=root,
        run_id="source-confirmation", signal_kind="stale", candidates=[candidate])
    return prepared, candidate, originals


def apply(data, prepared):
    return run(apply_dream_assimilation(data[0], prepared=prepared,
                                      plan=build_dream_maintenance_plan(prepared)))


def test_legacy_anchor_complete_context_confirmation_keeps_stored_anchor(confirmation):
    backend, _root, entry = confirmation
    prepared, candidate, originals = prepare(confirmation)
    assert all("context" not in parse_qs(urlparse(source.locator).fragment) for source in originals)
    assert all("context" in parse_qs(urlparse(source.locator).fragment) for source in candidate.sources)
    assert apply(confirmation, prepared)[0]["truth_change"] == "verification_refreshed"
    stored = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    assert {source.id for source in stored} == {source.id for source in originals}
    for before, after in zip(originals, stored):
        assert {key: value for key, value in after.to_dict().items() if key != "verified_at"} == {
            key: value for key, value in before.to_dict().items() if key != "verified_at"}
        assert after.verified_at != before.verified_at
    current = run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo"))
    assert current.statement == entry.statement and current.verified_at is not None


def test_real_dream_builder_carries_original_descriptor_snapshot(confirmation):
    backend, root, entry = confirmation
    before = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    provider = _ConfirmProvider()
    result = run(dream_once(backend, project_name="demo", project_root=root, semantic_provider=provider))
    assert result.handling_summary["applied"] == 1
    assert result.items[0].result["truth_change"] == "verification_refreshed"
    assert all("context" not in parse_qs(urlparse(source.locator).fragment)
               for source in run(backend.structured_store.knowledge_store.list_sources(entry.id)))
    assert [source.content_sha256 for source in before] == [source.content_sha256 for source in
        run(backend.structured_store.knowledge_store.list_sources(entry.id))]


def test_already_marked_persistent_source_does_not_downgrade_to_plain_anchor(confirmation):
    backend, _root, entry = confirmation
    first, candidate, _originals = prepare(confirmation)
    for source in candidate.sources:
        backend.structured_store.write_record_payload("knowledge_sources", source.id, source.to_dict())
    prepared, _candidate, originals = prepare(confirmation)
    assert all("context" in parse_qs(urlparse(source.locator).fragment) for source in originals)
    assert apply(confirmation, prepared)[0]["truth_change"] == "verification_refreshed"
    after = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    assert [(source.locator, source.content_sha256) for source in after] == [
        (source.locator, source.content_sha256) for source in originals]


def test_expanded_source_without_original_snapshot_is_not_a_refresh_identity(confirmation):
    prepared, _candidate, _originals = prepare(confirmation, original_sources=False)
    assert apply(confirmation, prepared)[0]["status"] == "source_changed"
    current = run(confirmation[0].structured_store.knowledge_store.get_entry(confirmation[2].id, project_name="demo"))
    assert current.to_dict() == confirmation[2].to_dict()


@pytest.mark.parametrize("change", ("id", "project", "knowledge", "kind", "locator", "digest", "remove", "add", "duplicate"))
def test_source_snapshot_tamper_cannot_be_laundered_through_complete_context(confirmation, change):
    backend, _root, entry = confirmation
    prepared, candidate, originals = prepare(confirmation)
    original = originals[0]
    changes = {"id": {"id": "other-id"}, "project": {"project_name": "other-project"},
               "knowledge": {"knowledge_id": "other-entry"}, "kind": {"source_kind": "repository"},
               "locator": {"locator": original.locator + "&extra=value"}, "digest": {"content_sha256": "0" * 64}}
    if change == "remove":
        altered = originals[1:]
    elif change in {"add", "duplicate"}:
        altered = (*originals, original.model_copy(update={"id": "extra-source"}) if change == "add" else original)
    else:
        altered = (original.model_copy(update=changes[change]), *originals[1:])
    prepared = replace(prepared, candidates=(replace(candidate, original_sources=altered),))
    assert apply(confirmation, prepared)[0]["status"] == "source_changed"
    assert run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")).to_dict() == entry.to_dict()


@pytest.mark.parametrize("change", ("plain_to_marked", "digest", "remove", "add"))
def test_source_membership_or_descriptor_change_after_semantic_proof_refuses_refresh(confirmation, change):
    backend, _root, entry = confirmation
    prepared, candidate, originals = prepare(confirmation)
    structured = backend.structured_store
    if change == "plain_to_marked":
        value = candidate.sources[0]
        structured.write_record_payload("knowledge_sources", value.id, value.to_dict())
    elif change == "digest":
        value = originals[0].model_copy(update={"content_sha256": "0" * 64})
        structured.write_record_payload("knowledge_sources", value.id, value.to_dict())
    elif change == "remove":
        structured.apply_canonical_payload_transaction(idempotency_key="remove-original-source", mutations=[{
            "operation": "delete", "collection": "knowledge_sources", "entity_id": originals[0].id,
            "project_name": "demo", "expected_sha256": structured.record_payload_sha256("knowledge_sources", originals[0].id)}])
    else:
        value = originals[0].model_copy(update={"id": "independent-extra-source"})
        structured.write_record_payload("knowledge_sources", value.id, value.to_dict())
    altered = [source.to_dict() for source in run(structured.knowledge_store.list_sources(entry.id))]
    assert apply(confirmation, prepared)[0]["status"] == "source_changed"
    assert [source.to_dict() for source in run(structured.knowledge_store.list_sources(entry.id))] == altered
    assert run(structured.knowledge_store.get_entry(entry.id, project_name="demo")).to_dict() == entry.to_dict()


@pytest.mark.parametrize("change", ("digest", "remove", "add"))
def test_source_transaction_race_is_rejected_without_refreshing_entry(confirmation, monkeypatch, change):
    backend, _root, entry = confirmation
    prepared, _candidate, originals = prepare(confirmation)
    structured = backend.structured_store
    real = structured.apply_canonical_payload_transaction
    changed = []
    def race(*, idempotency_key, mutations):
        if idempotency_key.startswith("knowledge-verification-refresh:") and not changed:
            changed.append(True)
            source = originals[0]
            mutation = {"operation": "delete" if change == "remove" else "upsert",
                "collection": "knowledge_sources", "entity_id": "concurrent-extra-source" if change == "add" else source.id,
                "project_name": "demo",
                "expected_sha256": None if change == "add" else structured.record_payload_sha256("knowledge_sources", source.id)}
            if change == "digest":
                mutation["payload"] = source.model_copy(update={"content_sha256": "0" * 64}).to_dict()
            elif change == "add":
                mutation["payload"] = source.model_copy(update={"id": "concurrent-extra-source"}).to_dict()
            real(idempotency_key="concurrent-source-owner", mutations=[mutation])
        return real(idempotency_key=idempotency_key, mutations=mutations)
    monkeypatch.setattr(structured, "apply_canonical_payload_transaction", race)
    assert apply(confirmation, prepared)[0]["status"] == "source_changed"
    assert changed
    assert run(structured.knowledge_store.get_entry(entry.id, project_name="demo")).to_dict() == entry.to_dict()
    stored = run(structured.knowledge_store.list_sources(entry.id))
    if change == "remove":
        assert originals[0].id not in {value.id for value in stored}
    elif change == "add":
        assert "concurrent-extra-source" in {value.id for value in stored}
    else:
        assert any(value.id == originals[0].id and value.content_sha256 == "0" * 64 for value in stored)


def test_confirmation_still_requires_exact_final_title_and_body_proof(confirmation):
    prepared, _candidate, _originals = prepare(confirmation, final_scope=False)
    outcome = apply(confirmation, prepared)[0]
    assert outcome["status"] == "rejected"
    current = run(confirmation[0].structured_store.knowledge_store.get_entry(confirmation[2].id, project_name="demo"))
    assert current.to_dict() == confirmation[2].to_dict()


def test_repository_digest_refresh_keeps_original_identity(captured):
    backend, root, _snapshot, _rendering, _sources = captured
    path = root / "current-policy.md"
    path.write_text("Prior bytes.", encoding="utf-8")
    old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = KnowledgeEntry(id="repository-rule", project_name="demo", title="Repository policy",
                           statement="Current bytes retain the scoped rule.", module_path=["policy"])
    publish(backend, entry, [ProjectKnowledgeSourceRef(label="Repository policy", target=path.as_uri(),
                                                    kind="repository", digest=old_digest)])
    path.write_text(entry.statement, encoding="utf-8")
    prepared, candidate, originals = prepare((backend, root, entry))
    assert candidate.sources[0].content_sha256 != originals[0].content_sha256
    assert apply((backend, root, entry), prepared)[0]["truth_change"] == "verification_refreshed"
    stored = run(backend.structured_store.knowledge_store.list_sources(entry.id))[0]
    assert stored.locator == originals[0].locator and stored.id == originals[0].id
    assert stored.content_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
