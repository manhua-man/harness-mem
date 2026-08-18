"""SQLite-authoritative knowledge, source, undo, and workspace invariants."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AssimilationDecision as ProviderAssimilationDecision,
)
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    validate_separated_assimilation_decision,
)
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.storage.canonical_store import canonical_store_path
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


VERIFIED_AT = datetime(2026, 8, 18, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


def _candidate(candidate_id: str, *, status: str = "pending") -> KnowledgeCandidate:
    return KnowledgeCandidate(
        id=candidate_id,
        project_name="demo",
        candidate_type="memory",
        statement="Use one canonical SQLite knowledge row.",
        status=status,
    )


def _entry(entry_id: str, statement: str, *, revision: int = 1) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=entry_id,
        project_name="demo",
        module_path=["storage"],
        title="Canonical knowledge",
        statement=statement,
        verified_at=VERIFIED_AT,
        revision=revision,
    )


def _source(statement_digest: str = "a" * 64) -> ProjectKnowledgeSourceRef:
    return ProjectKnowledgeSourceRef(
        label="README.md",
        target="file:///demo/README.md",
        kind="repository",
        digest=statement_digest,
    )


def _decision(
    decision_id: str,
    candidate_id: str,
    disposition: str,
    current: list[KnowledgeEntry],
    predecessors: list[KnowledgeEntry] = [],
) -> AssimilationDecision:
    return AssimilationDecision(
        id=decision_id,
        project_name="demo",
        candidate_id=candidate_id,
        disposition=disposition,
        canonical_truth_ids=[entry.id for entry in current],
        predecessor_truth_ids=[entry.id for entry in predecessors],
        predecessor_entries=predecessors,
        reason="Verified durable project knowledge.",
    )


def _apply(
    store,
    *,
    candidate: KnowledgeCandidate,
    decision: AssimilationDecision,
    added: list[KnowledgeEntry],
    predecessors: list[KnowledgeEntry] = [],
):
    completed = candidate.model_copy(update={"status": "assimilated"})
    return _run(
        store.apply_truth_mutation(
            candidate_before=candidate,
            candidate_after=completed,
            decision=decision,
            added_entries=added,
            predecessor_entries=predecessors,
            source_refs_by_entry={entry.id: [_source()] for entry in added},
        )
    )


def test_sqlite_is_authority_and_processing_material_is_not_truth(tmp_path) -> None:
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = _candidate("candidate-1")
        evidence = KnowledgeEvidence(
            id="evidence-1",
            project_name="demo",
            candidate_id=candidate.id,
            distill_job_id="job-1",
            evidence_basis="user_statement",
            verification_outcome="verified",
        )
        entry = _entry("knowledge-1", "SQLite is the current knowledge authority.")
        decision = _decision("mutation-1", candidate.id, "add", [entry])
        _run(store.save_candidate(candidate))
        _run(store.save_evidence(evidence))

        result = _apply(
            store,
            candidate=candidate,
            decision=decision,
            added=[entry],
        )

        assert result["replayed"] is False
        assert _run(store.list_entries("demo")) == [entry]
        sources = _run(store.list_sources(entry.id))
        assert len(sources) == 1
        assert sources[0].knowledge_id == entry.id
        assert sources[0].project_name == "demo"
        assert sources[0].content_sha256 == "a" * 64
        assert _run(store.get_mutation(decision.id)) is not None
        assert _run(store.get_candidate(candidate.id)) == candidate
        assert not (data_dir / "knowledge_audit").exists()
        assert not list(tmp_path.rglob("session-knowledge-base.md"))

        payload = backend.structured_store.read_record_payload(
            "knowledge_entries", entry.id
        )
        assert set(payload) == {
            "id",
            "project_name",
            "module_path",
            "title",
            "statement",
            "verified_at",
            "revision",
            "created_at",
            "updated_at",
        }
        assert "source_refs" not in payload
        assert "claim_kind" not in payload
        assert "distill_job_id" not in payload

        connection = sqlite3.connect(canonical_store_path(data_dir))
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            connection.close()
        assert {
            "knowledge_entries",
            "knowledge_sources",
            "knowledge_versions",
            "knowledge_mutations",
        }.issubset(tables)
        assert not {
            "knowledge_candidates",
            "knowledge_evidence",
            "assimilation_decisions",
        }.intersection(tables)
    finally:
        _run(backend.close())


def test_truth_mutation_is_idempotent_and_keeps_database_inode(tmp_path) -> None:
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = _candidate("candidate-idempotent")
        entry = _entry("knowledge-idempotent", "Write exactly once.")
        decision = _decision("mutation-idempotent", candidate.id, "add", [entry])
        _run(store.save_candidate(candidate))
        before_inode = canonical_store_path(data_dir).stat().st_ino

        first = _apply(store, candidate=candidate, decision=decision, added=[entry])
        second = _apply(store, candidate=candidate, decision=decision, added=[entry])

        assert first["replayed"] is False
        assert second["replayed"] is True
        assert canonical_store_path(data_dir).stat().st_ino == before_inode
        assert _run(store.list_entries("demo")) == [entry]
    finally:
        _run(backend.close())


def test_refine_and_undo_use_bounded_versions(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        seed_candidate = _candidate("seed-candidate")
        old = _entry("knowledge-old", "Old current statement.", revision=1)
        _run(store.save_candidate(seed_candidate))
        _apply(
            store,
            candidate=seed_candidate,
            decision=_decision("seed-mutation", seed_candidate.id, "add", [old]),
            added=[old],
        )

        refine_candidate = _candidate("refine-candidate")
        replacement = _entry("knowledge-new", "Refined current statement.")
        refine = _decision(
            "refine-mutation",
            refine_candidate.id,
            "refine",
            [replacement],
            [old],
        )
        _run(store.save_candidate(refine_candidate))
        _apply(
            store,
            candidate=refine_candidate,
            decision=refine,
            added=[replacement],
            predecessors=[old],
        )

        mutation = _run(store.get_mutation(refine.id))
        assert mutation is not None
        assert len(mutation.predecessor_version_ids) == 1
        version = _run(store.get_version(mutation.predecessor_version_ids[0]))
        assert version is not None
        assert version.knowledge_id == old.id
        assert version.sources
        assert _run(store.list_entries("demo")) == [replacement]

        undo = _run(
            store.undo_truth_mutation(
                mutation_id=refine.id,
                reversal_id="undo-refine-mutation",
            )
        )
        restored = _run(store.list_entries("demo"))
        assert undo["restored_knowledge_ids"] == [old.id]
        assert [entry.id for entry in restored] == [old.id]
        assert restored[0].statement == old.statement
        assert restored[0].revision == 2
        assert _run(store.list_sources(old.id))
    finally:
        _run(backend.close())


def test_precondition_failure_leaves_current_truth_unchanged(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        seed = _candidate("seed")
        current = _entry("current", "Current statement.")
        _run(store.save_candidate(seed))
        _apply(
            store,
            candidate=seed,
            decision=_decision("seed", seed.id, "add", [current]),
            added=[current],
        )
        stale = current.model_copy(update={"statement": "Stale before-image."})
        replacement = _entry("replacement", "Replacement statement.")
        candidate = _candidate("replace")
        decision = _decision("replace", candidate.id, "refine", [replacement], [stale])
        _run(store.save_candidate(candidate))

        with pytest.raises(ValueError, match="changed before commit"):
            _apply(
                store,
                candidate=candidate,
                decision=decision,
                added=[replacement],
                predecessors=[stale],
            )
        assert _run(store.list_entries("demo")) == [current]
        assert _run(store.get_mutation(decision.id)) is None
    finally:
        _run(backend.close())


def test_terminal_processing_detail_is_cleaned_only_on_explicit_completion(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = _candidate("candidate-cleanup")
        evidence = KnowledgeEvidence(
            id="evidence-cleanup",
            project_name="demo",
            candidate_id=candidate.id,
            distill_job_id="job-cleanup",
            evidence_basis="user_statement",
            verification_outcome="verified",
        )
        _run(store.save_candidate(candidate))
        _run(store.save_evidence(evidence))
        decision = AssimilationDecision(
            id="no-write",
            project_name="demo",
            candidate_id=candidate.id,
            disposition="no_write",
            reason="One-off request has no durable value.",
        )
        _run(store.save_decision(decision))

        assert _run(store.get_candidate(candidate.id)) == candidate
        assert _run(store.cleanup_job("job-cleanup")) == 1
        assert _run(store.get_candidate(candidate.id)) is None
        assert _run(store.list_evidence(candidate.id)) == []
        assert _run(store.get_decision(decision.id)) is None
    finally:
        _run(backend.close())


def test_current_knowledge_schema_rejects_processing_fields() -> None:
    entry = _entry("knowledge", "One atomic statement.")
    for field, value in (
        ("distill_job_id", "job"),
        ("source_refs", []),
        ("claim_kind", "procedure"),
        ("confidence", 0.9),
        ("tier", "hot"),
    ):
        with pytest.raises(ValidationError):
            KnowledgeEntry.model_validate({**entry.to_dict(), field: value})


def test_supersede_can_split_one_broad_truth_into_atomic_successors() -> None:
    prepared = SeparatedPreparedAssimilation(
        project_name="demo",
        project_root="demo",
        candidate_ids=("candidate-1",),
        eligible_candidate_ids=("candidate-1",),
        automatic_points=(),
        answer_status_by_candidate={"candidate-1": "ANSWERED"},
        truth_by_handle={"truth-1": "broad-current"},
        manifest={},
    )
    decision = ProviderAssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": "candidate-1",
                    "disposition": "supersede",
                    "matched_truth_handles": ["truth-1"],
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "knowledge_items": [
                        {
                            "title": "Transactional publication",
                            "statement": "Publish related product records in one transaction.",
                            "topic_path": ["publication"],
                            "claim_kind": "procedure",
                        },
                        {
                            "title": "Final API validation",
                            "statement": "Validate the final public API output after assembly.",
                            "topic_path": ["api"],
                            "claim_kind": "procedure",
                        },
                    ],
                    "reason": "The broad current entry mixes two independently searchable rules.",
                }
            ]
        }
    )

    plan = validate_separated_assimilation_decision(prepared, decision)

    assert plan["points"][0]["matched_truth_ids"] == ["broad-current"]
    assert [item["title"] for item in plan["points"][0]["knowledge_items"]] == [
        "Transactional publication",
        "Final API validation",
    ]
