"""Atomic merges may retain a verified predecessor ID; isolated stores only."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_knowledge_context_preconditions import publish, run, workspace as workspace
from harness_mem.core.schemas.knowledge import KnowledgeSource
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError


def prepare(workspace):
    backend, store, retained, refs = workspace
    other = retained.model_copy(update={"id": "other-duplicate"})
    second = ProjectKnowledgeSourceRef(label="Other original source", kind="transcript",
                                      target=refs[0].target + "#second", digest="2" * 64)
    run(publish(store, other, [second], key="other-original"))
    output = retained.model_copy(update={"verified_at": retained.updated_at + timedelta(seconds=1),
                                         "updated_at": retained.updated_at + timedelta(seconds=1)})
    return backend, store, retained, other, output, [*refs, second]


def merge(store, retained, other, output, refs, *, key="retained-merge"):
    return run(publish(store, output, refs, key=key, context=[retained, other],
                       predecessors=[retained, other]))


def test_merge_retains_entry_and_source_ids_with_original_cas_once(workspace, monkeypatch):
    backend, store, retained, other, output, refs = prepare(workspace)
    old_sources = run(store.list_sources(retained.id))
    other_sources = run(store.list_sources(other.id))
    expected = {(collection, key): backend.structured_store.record_payload_sha256(collection, key)
                for collection, keys in [("knowledge_entries", [retained.id, other.id]),
                                         ("knowledge_sources", [s.id for s in [*old_sources, *other_sources]])]
                for key in keys}
    original = backend.structured_store.apply_canonical_payload_transaction
    seen = []

    def observed(**kwargs):
        seen.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", observed)
    merge(store, retained, other, output, refs)
    ops = seen[-1]["mutations"]
    targets = [(op["collection"], op["entity_id"]) for op in ops]
    assert len(set(targets)) == len(targets)
    for op in ops:
        key = (op["collection"], op["entity_id"])
        if key in expected:
            assert op["expected_sha256"] == expected[key]
        if op["collection"] == "knowledge_entries":
            assert op["expected_source_ids"] == sorted(s.id for s in (
                old_sources if op["entity_id"] == retained.id else other_sources))
    kept = next(op for op in ops if op["collection"] == "knowledge_entries" and op["entity_id"] == retained.id)
    assert kept["operation"] == "upsert"
    retained_source = next(op for op in ops if op["collection"] == "knowledge_sources"
                           and op["entity_id"] == old_sources[0].id)
    assert retained_source["operation"] == "upsert"
    assert run(store.get_entry(retained.id, project_name="demo")).to_dict() == output.to_dict()
    assert run(store.get_entry(other.id, project_name="demo")) is None
    assert run(store.list_sources(other.id)) == []
    assert {s.locator for s in run(store.list_sources(retained.id))} == {r.target for r in refs}
    assert run(store.current_change_committed("retained-merge")) is True


@pytest.mark.parametrize("race", ["entry", "retained_source", "source_membership"])
def test_late_change_refuses_entire_merge_and_preserves_other_predecessor(workspace, monkeypatch, race):
    backend, store, retained, other, output, refs = prepare(workspace)
    original = backend.structured_store.apply_canonical_payload_transaction
    source = run(store.list_sources(retained.id))[0]
    inserted_id = "late-new-source"

    def raced(**kwargs):
        if race == "entry":
            collection, key = "knowledge_entries", retained.id
            payload = retained.model_copy(update={"statement": "A concurrent changed decision."}).to_dict()
        elif race == "retained_source":
            collection, key = "knowledge_sources", source.id
            payload = source.model_copy(update={"content_sha256": "f" * 64}).to_dict()
        else:
            collection, key = "knowledge_sources", inserted_id
            payload = KnowledgeSource(id=key, knowledge_id=retained.id, project_name="demo",
                source_kind="transcript", locator=refs[0].target + "#late",
                content_sha256="a" * 64, verified_at=retained.updated_at).to_dict()
        original(idempotency_key="concurrent-" + race, mutations=[{
            "operation": "upsert", "collection": collection, "entity_id": key,
            "project_name": "demo", "payload": payload,
            "expected_sha256": backend.structured_store.record_payload_sha256(collection, key),
        }])
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", raced)
    with pytest.raises(CanonicalTransactionPreconditionError):
        merge(store, retained, other, output, refs)
    assert run(store.current_change_committed("retained-merge")) is False
    assert run(store.get_entry(other.id, project_name="demo")).to_dict() == other.to_dict()
    assert len(run(store.list_sources(other.id))) == 1
    current = run(store.get_entry(retained.id, project_name="demo"))
    assert current.statement == ("A concurrent changed decision." if race == "entry" else retained.statement)
    if race == "retained_source":
        assert run(store.list_sources(retained.id))[0].content_sha256 == "f" * 64
    elif race == "source_membership":
        assert inserted_id in {s.id for s in run(store.list_sources(retained.id))}


def test_successor_identity_must_be_in_the_verified_predecessor_set(workspace):
    _backend, store, retained, other, output, refs = prepare(workspace)
    # The current retained ID cannot be overwritten by a merge that only
    # verified the other row, even when its body would be identical.
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(publish(store, output, refs, key="unbound-existing-output", predecessors=[other]))
    assert run(store.get_entry(retained.id, project_name="demo")).to_dict() == retained.to_dict()
    assert run(store.get_entry(other.id, project_name="demo")).to_dict() == other.to_dict()


def test_default_new_identity_replacement_still_deletes_predecessors(workspace):
    _backend, store, retained, other, output, refs = prepare(workspace)
    output = output.model_copy(update={"id": "different-new-output"})
    merge(store, retained, other, output, refs)
    assert run(store.get_entry(retained.id, project_name="demo")) is None
    assert run(store.get_entry(other.id, project_name="demo")) is None
    assert run(store.get_entry(output.id, project_name="demo")).to_dict() == output.to_dict()
