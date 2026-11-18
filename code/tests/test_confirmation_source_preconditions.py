"""Confirmation preserves its verified source snapshot through canonical CAS."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.core.schemas import KnowledgeEntry, KnowledgeSource
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(value):
    return asyncio.run(value)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    run(backend.init())
    entry = KnowledgeEntry(id="current", project_name="demo", module_path=["entry"],
                           title="Current", statement="The source-backed statement.")
    source = KnowledgeSource(id="source", knowledge_id=entry.id, project_name="demo",
                             source_kind="repository", locator="README.md",
                             content_sha256="a" * 64, verified_at=datetime.now(timezone.utc))
    backend.structured_store.apply_canonical_payload_transaction(
        idempotency_key="fixture", mutations=[
            {"operation": "upsert", "collection": collection, "entity_id": row.id,
             "project_name": "demo", "payload": row.to_dict()}
            for collection, row in [("knowledge_entries", entry), ("knowledge_sources", source)]])
    yield backend, entry, source
    run(backend.close())


def refresh(backend, entry, source, *, expected=None, proposed=None):
    return run(backend.structured_store.knowledge_store.refresh_entry_verification(
        project_name="demo", entry_id=entry.id, verified_at=datetime.now(timezone.utc),
        refresh_id="test-confirm", expected_entry=entry,
        expected_sources=expected if expected is not None else [source],
        refreshed_sources=proposed if proposed is not None else [source]))


def test_matching_source_snapshot_refreshes_without_changing_identity(workspace):
    backend, entry, source = workspace
    refresh(backend, entry, source)
    updated = run(backend.structured_store.knowledge_store.list_sources(entry.id))[0]
    assert updated.locator == source.locator and updated.content_sha256 == source.content_sha256
    assert run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")).statement == entry.statement


@pytest.mark.parametrize("field,value", [("locator", "OTHER.md"), ("content_sha256", "b" * 64),
                                        ("knowledge_id", "other"), ("project_name", "other")])
def test_changed_source_snapshot_refuses_before_refresh(workspace, field, value):
    backend, entry, source = workspace
    with pytest.raises(CanonicalTransactionPreconditionError):
        refresh(backend, entry, source, expected=[source.model_copy(update={field: value})])
    assert run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")).to_dict() == entry.to_dict()


@pytest.mark.parametrize("shape", ["empty", "duplicate"])
def test_changed_source_set_refuses(workspace, shape):
    backend, entry, source = workspace
    with pytest.raises(CanonicalTransactionPreconditionError):
        refresh(backend, entry, source, expected=[] if shape == "empty" else [source, source])


@pytest.mark.parametrize("change", ["update", "delete", "add"])
def test_source_race_at_canonical_commit_does_not_overwrite_or_refresh(workspace, monkeypatch, change):
    backend, entry, source = workspace
    original = backend.structured_store.apply_canonical_payload_transaction
    changed = source.model_copy(update={"verified_at": source.verified_at + timedelta(seconds=1),
                                        **({"id": "new-source"} if change == "add" else {})})

    def race(**kwargs):
        mutation = {"operation": "delete" if change == "delete" else "upsert",
                    "collection": "knowledge_sources", "entity_id": changed.id, "project_name": "demo"}
        if change != "delete":
            mutation["payload"] = changed.to_dict()
        original(idempotency_key="concurrent-source-owner", mutations=[mutation])
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", race)
    with pytest.raises(CanonicalTransactionPreconditionError):
        refresh(backend, entry, source)
    assert run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")).to_dict() == entry.to_dict()
    remaining = run(backend.structured_store.knowledge_store.list_sources(entry.id))
    expected = [changed] if change == "update" else ([source, changed] if change == "add" else [])
    assert {row.id: row.to_dict() for row in remaining} == {row.id: row.to_dict() for row in expected}


def test_refresh_still_rejects_a_new_locator_even_with_matching_snapshot(workspace):
    backend, entry, source = workspace
    with pytest.raises(ValueError, match="identity changed"):
        refresh(backend, entry, source, proposed=[source.model_copy(update={"locator": "OTHER.md"})])


@pytest.mark.parametrize("bad_ids", [None, "source", ["source", "source"], [""], [1]])
def test_source_membership_precondition_requires_an_exact_id_list(workspace, bad_ids):
    backend, entry, _source = workspace
    with pytest.raises(ValueError, match="expected_source_ids"):
        backend.structured_store.apply_canonical_payload_transaction(
            idempotency_key="bad-guard", mutations=[{
                "operation": "assert", "collection": "knowledge_entries", "entity_id": entry.id,
                "project_name": "demo", "expected_sha256": backend.structured_store.record_payload_sha256(
                    "knowledge_entries", entry.id), "expected_source_ids": bad_ids}])


@pytest.mark.parametrize("scope", ["other_entry", "other_project"])
def test_source_membership_guard_ignores_other_knowledge_and_projects(workspace, monkeypatch, scope):
    backend, entry, source = workspace
    original = backend.structured_store.apply_canonical_payload_transaction
    unrelated = source.model_copy(update={"id": "unrelated-source", **(
        {"knowledge_id": "other-entry"} if scope == "other_entry" else {"project_name": "other-project"})})

    def race(**kwargs):
        original(idempotency_key="unrelated-owner", mutations=[{
            "operation": "upsert", "collection": "knowledge_sources", "entity_id": unrelated.id,
            "project_name": unrelated.project_name, "payload": unrelated.to_dict()}])
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", race)
    refresh(backend, entry, source)
