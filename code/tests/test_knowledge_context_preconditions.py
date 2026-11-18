"""Read-only scope guards share the canonical truth transaction in fixtures."""
from __future__ import annotations

import asyncio

import pytest

from harness_mem.core.schemas.knowledge import AssimilationDecision, KnowledgeCandidate, KnowledgeEntry
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run(value):
    return asyncio.run(value)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    run(backend.init())
    store = backend.structured_store.knowledge_store
    source = tmp_path / "source.txt"
    source.write_text("Fixture source only.", encoding="utf-8")
    refs = [ProjectKnowledgeSourceRef(label="Fixture", kind="transcript", target=source.as_uri())]
    context = KnowledgeEntry(id="current-scope", project_name="demo", module_path=["entry"],
                             title="Original scope", statement="The exact current scope.")
    run(publish(store, context, refs, key="initial"))
    yield backend, store, context, refs
    run(backend.close())


async def publish(store, output, refs, *, key, context=(), predecessors=()):
    candidate = KnowledgeCandidate(id="candidate-" + key, project_name="demo",
                                  candidate_type="memory", statement=output.statement)
    return await store.apply_current_change(
        candidate_before=candidate, candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=AssimilationDecision(id=key, project_name="demo", candidate_id=candidate.id,
            disposition="refine" if predecessors else "add", canonical_truth_ids=[output.id],
            predecessor_truth_ids=[entry.id for entry in predecessors], reason="Fixture commit."),
        added_entries=[output], predecessor_entries=predecessors,
        source_refs_by_entry={output.id: refs}, expected_context_entries=context,
    )


def new_output():
    return KnowledgeEntry(id="new-output", project_name="demo", module_path=["entry"],
                          title="New scoped claim", statement="A separately proved missing claim.")


def test_add_keeps_context_unchanged_and_asserts_it_in_the_same_transaction(workspace, monkeypatch):
    backend, store, context, refs = workspace
    original = backend.structured_store.apply_canonical_payload_transaction
    calls = []

    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", observed)
    run(publish(store, new_output(), refs, key="guarded-add", context=[context]))
    guard = next(op for op in calls[-1]["mutations"] if op["entity_id"] == context.id)
    assert guard["operation"] == "assert" and guard["expected_sha256"]
    assert run(store.get_entry(context.id, project_name="demo")).to_dict() == context.to_dict()
    assert run(store.get_entry("new-output", project_name="demo")) is not None


@pytest.mark.parametrize("change", ("replace", "delete"))
def test_scope_change_between_preflight_and_transaction_refuses_the_add(workspace, monkeypatch, change):
    backend, store, context, refs = workspace
    original = backend.structured_store.apply_canonical_payload_transaction
    changed = context.model_copy(update={"statement": "A concurrent owner's changed scope."})

    def race(**kwargs):
        operation = {"operation": "upsert" if change == "replace" else "delete",
            "collection": "knowledge_entries", "entity_id": context.id, "project_name": "demo",
            "expected_sha256": backend.structured_store.record_payload_sha256("knowledge_entries", context.id)}
        if change == "replace":
            operation["payload"] = changed.to_dict()
        original(idempotency_key="concurrent-scope-change", mutations=[operation])
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", race)
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(publish(store, new_output(), refs, key="racing-add", context=[context]))
    assert run(store.get_entry("new-output", project_name="demo")) is None
    current = run(store.get_entry(context.id, project_name="demo"))
    assert current.to_dict() == changed.to_dict() if change == "replace" else current is None


def test_context_also_retired_by_this_point_uses_one_original_hash_precondition(workspace, monkeypatch):
    backend, store, context, refs = workspace
    original = backend.structured_store.apply_canonical_payload_transaction
    calls = []

    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(backend.structured_store, "apply_canonical_payload_transaction", observed)
    run(publish(store, new_output(), refs, key="guarded-refine", context=[context], predecessors=[context]))
    guarded = [op for op in calls[-1]["mutations"]
               if op["collection"] == "knowledge_entries" and op["entity_id"] == context.id]
    assert len(guarded) == 1 and guarded[0]["operation"] == "delete" and guarded[0]["expected_sha256"]
    assert run(store.get_entry(context.id, project_name="demo")) is None


@pytest.mark.parametrize("scope", ("wrong_project", "duplicate", "missing"))
def test_scope_guard_requires_exact_current_project_rows(workspace, scope):
    _backend, store, context, refs = workspace
    guards = [context.model_copy(update={"project_name": "other"})] if scope == "wrong_project" else (
        [context, context] if scope == "duplicate" else [context.model_copy(update={"id": "missing"})])
    with pytest.raises(CanonicalTransactionPreconditionError):
        run(publish(store, new_output(), refs, key="invalid-scope", context=guards))
    assert run(store.get_entry("new-output", project_name="demo")) is None
