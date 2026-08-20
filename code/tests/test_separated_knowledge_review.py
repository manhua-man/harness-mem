"""Review decisions must use the same evidence and decision boundary as Dream."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from harness_mem.commands.knowledge_assimilation import (
    record_assimilation_result,
    resolve_separated_review,
    undo_separated_review,
)
from harness_mem.commands.separated_assimilation import (
    _is_session_scope_clarification,
    apply_separated_assimilation,
    create_separated_candidates,
    separated_job_candidate_ids,
)
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.evidence import EvidenceRef
from harness_mem.mcp import governance_handlers
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage import knowledge_store as knowledge_store_module


def _run(coro):
    return asyncio.run(coro)


VERIFIED_AT = datetime(2026, 8, 18, tzinfo=timezone.utc)


def _project_root(tmp_path):
    root = tmp_path / "demo"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text(
        "# Demo\n\nThis file is the verified repository source.\n",
        encoding="utf-8",
    )
    return root


def _verified_evidence(
    candidate: KnowledgeCandidate, evidence_id: str, project_root
) -> KnowledgeEvidence:
    locator = "README.md"
    content = (project_root / locator).read_bytes()
    return KnowledgeEvidence(
        id=evidence_id,
        project_name="demo",
        candidate_id=candidate.id,
        evidence_basis="repository",
        verification_outcome="verified",
        verification_refs=[
            EvidenceRef(
                kind="repository",
                locator=locator,
                locator_sha256=hashlib.sha256(locator.encode("utf-8")).hexdigest(),
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
        ],
        verified_at=VERIFIED_AT,
    )


def test_deferred_point_does_not_require_a_truth_source_reference(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        candidate = KnowledgeCandidate(
            id="incomplete-transcript-candidate",
            project_name="demo",
            candidate_type="rule",
            statement="An incomplete transcript point must remain outside current truth.",
        )
        evidence = KnowledgeEvidence(
            id="incomplete-transcript-evidence",
            project_name="demo",
            candidate_id=candidate.id,
            distill_job_id="missing-job",
            evidence_basis="transcript",
            verification_outcome="unverified",
            verification_refs=[
                EvidenceRef(
                    kind="transcript",
                    exchange_index=7,
                    role="assistant",
                    content_sha256="a" * 64,
                )
            ],
        )
        store = backend.structured_store.knowledge_store
        _run(store.save_candidate(candidate))
        _run(store.save_evidence(evidence))

        result = _run(
            apply_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id],
                plan={
                    "version": "separated-v1",
                    "candidate_ids": [candidate.id],
                    "point_count": 1,
                    "provider_candidate_ids": [],
                    "points": [
                        {
                            "candidate_id": candidate.id,
                            "answer_status": "PARTIAL",
                            "disposition": "defer",
                            "matched_truth_ids": [],
                            "knowledge_items": [],
                            "reason": "runtime evidence gate is PARTIAL",
                        }
                    ],
                },
            )
        )

        assert result["deferred"] == 1
        assert _run(store.get_candidate(candidate.id)).status == "deferred"
        assert _run(store.list_decisions(candidate.id))[0].disposition == "defer"
        assert not (
            project_root / ".harness-mem" / "session-knowledge-base.md"
        ).exists()
    finally:
        _run(backend.close())


def test_apply_revalidates_answer_gate_before_writing_current_knowledge(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="stale-before-apply",
            project_name="demo",
            candidate_type="memory",
            statement="The repository source must still support this point.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "stale-evidence", project_root)
            )
        )
        (project_root / "README.md").write_text(
            "# Demo\n\nThe previously verified source has changed.\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="eligible|ANSWERED|evidence"):
            _run(
                apply_separated_assimilation(
                    backend,
                    project_name="demo",
                    project_root=str(project_root),
                    candidate_ids=[candidate.id],
                    plan={
                        "version": "separated-v1",
                        "candidate_ids": [candidate.id],
                        "point_count": 1,
                        "provider_candidate_ids": [candidate.id],
                        "points": [
                            {
                                "candidate_id": candidate.id,
                                "answer_status": "ANSWERED",
                                "disposition": "add",
                                "matched_truth_ids": [],
                                "knowledge_items": [
                                    {
                                        "title": "Current evidence required",
                                        "statement": "Current knowledge writes require evidence that still matches its source.",
                                        "topic_path": ["Evidence admission"],
                                        "claim_kind": "procedure",
                                    }
                                ],
                                "reason": "The provider claimed the stale evidence remained valid.",
                            }
                        ],
                    },
                )
            )
        assert _run(store.list_entries("demo", project_root=project_root)) == []
    finally:
        _run(backend.close())


def test_apply_rejects_processing_labels_in_untrusted_knowledge_payload(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="invalid-module-at-apply",
            project_name="demo",
            candidate_type="memory",
            statement="The apply boundary must validate canonical knowledge.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "invalid-module-evidence", project_root)
            )
        )

        with pytest.raises(ValueError, match="processing label"):
            _run(
                apply_separated_assimilation(
                    backend,
                    project_name="demo",
                    project_root=str(project_root),
                    candidate_ids=[candidate.id],
                    plan={
                        "version": "separated-v1",
                        "candidate_ids": [candidate.id],
                        "point_count": 1,
                        "provider_candidate_ids": [candidate.id],
                        "points": [
                            {
                                "candidate_id": candidate.id,
                                "answer_status": "ANSWERED",
                                "disposition": "add",
                                "matched_truth_ids": [],
                                "knowledge_items": [
                                    {
                                        "title": "Apply validates modules",
                                        "statement": "The runtime rejects internal processing labels before truth is written.",
                                        "topic_path": ["稳定操作规则"],
                                        "claim_kind": "procedure",
                                    }
                                ],
                                "reason": "The provider supplied an internal processing label.",
                            }
                        ],
                    },
                )
            )
        assert _run(store.list_entries("demo", project_root=project_root)) == []
    finally:
        _run(backend.close())


def _publish_entry(
    store,
    project_root,
    *,
    title: str,
    statement: str,
    topic_path: list[str],
) -> KnowledgeEntry:
    source_ref = ProjectKnowledgeSourceRef(
        label="README.md",
        target=(project_root / "README.md").resolve().as_uri(),
        kind="repository",
        digest=hashlib.sha256((project_root / "README.md").read_bytes()).hexdigest(),
    )
    candidate = KnowledgeCandidate(
        id=f"seed-{title}-{statement}",
        project_name="demo",
        candidate_type="memory",
        statement=statement,
    )
    entry = KnowledgeEntry(
        project_name="demo",
        title=title,
        statement=statement,
        module_path=topic_path,
        verified_at=VERIFIED_AT,
    )
    decision = AssimilationDecision(
        id=f"seed-mutation-{entry.id}",
        project_name="demo",
        candidate_id=candidate.id,
        disposition="add",
        canonical_truth_ids=[entry.id],
        reason="Test fixture seed.",
    )
    _run(store.save_candidate(candidate))
    _run(
        store.apply_truth_mutation(
            candidate_before=candidate,
            candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision,
            added_entries=[entry],
            predecessor_entries=[],
            source_refs_by_entry={entry.id: [source_ref]},
        )
    )
    current = _run(store.list_entries("demo", project_root=project_root))
    assert len(current) == 1
    return current[0]


def test_archive_current_knowledge_keeps_a_reversible_snapshot(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="One-time migration note",
            statement="This statement belongs only to an old one-time migration.",
            topic_path=["migration"],
        )

        archived = _run(
            store.archive_current_entry(
                project_name="demo",
                entry_id=current.id,
                mutation_id="archive-one-time-migration-note",
                reason="The entry is historical task progress, not current knowledge.",
            )
        )

        assert archived["mutation_count"] > 0
        assert _run(store.list_entries("demo", project_root=project_root)) == []
        decision = _run(store.get_decision("archive-one-time-migration-note"))
        assert decision is not None
        assert decision.disposition == "archive"
        assert decision.reason == "The entry is historical task progress, not current knowledge."

        restored = _run(
            store.undo_truth_mutation(
                mutation_id="archive-one-time-migration-note",
                reversal_id="undo-archive-one-time-migration-note",
            )
        )
        assert restored["restored_knowledge_ids"] == [current.id]
        assert [entry.id for entry in _run(store.list_entries("demo"))] == [current.id]
    finally:
        _run(backend.close())


def test_refine_assimilation_replays_after_predecessor_was_retired(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        old = _publish_entry(
            store,
            project_root,
            title="Evidence retention",
            statement="Keep original evidence for seven days.",
            topic_path=["Ingestion"],
        )
        candidate = KnowledgeCandidate(
            id="retry-refine-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The verified retention requirement changed to fourteen days.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "retry-refine-evidence", project_root)
            )
        )
        plan = {
            "version": "separated-v1",
            "candidate_ids": [candidate.id],
            "point_count": 1,
            "provider_candidate_ids": [candidate.id],
            "points": [
                {
                    "candidate_id": candidate.id,
                    "answer_status": "ANSWERED",
                    "disposition": "refine",
                    "matched_truth_ids": [old.id],
                    "knowledge_items": [
                        {
                            "title": "Evidence retention",
                            "statement": "Keep original evidence for fourteen days.",
                            "topic_path": ["Ingestion"],
                            "claim_kind": "design_requirement",
                        }
                    ],
                    "reason": "The verified retention requirement changed.",
                }
            ],
        }

        first = _run(
            apply_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id],
                plan=plan,
            )
        )
        second = _run(
            apply_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id],
                plan=plan,
            )
        )

        assert second == first
        current = _run(store.list_entries("demo", project_root=project_root))
        assert [(entry.title, entry.statement) for entry in current] == [
            ("Evidence retention", "Keep original evidence for fourteen days.")
        ]
        mutations = _run(store.list_mutations("demo"))
        assert len([item for item in mutations if item.disposition == "refine"]) == 1
    finally:
        _run(backend.close())


def test_review_rejects_unverified_dream_candidate_and_writes_verified_resolution(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="review-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="Potential duplicate that requires re-verification.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                KnowledgeEvidence(
                    id="review-evidence",
                    project_name="demo",
                    candidate_id=candidate.id,
                    evidence_basis="transcript",
                    verification_outcome="unverified",
                )
            )
        )

        with pytest.raises(ValueError, match="verified evidence"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="add",
                    reason="Attempted direct truth write.",
                    knowledge_items=[
                        {
                            "title": "Must not be written",
                            "statement": "This cannot bypass verification.",
                            "topic_path": ["review"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.list_entries("demo", project_root=project_root)) == []

        _run(
            store.save_evidence(
                _verified_evidence(candidate, "review-evidence", project_root)
            )
        )
        payload = _run(
            resolve_separated_review(
                backend,
                candidate_id=candidate.id,
                disposition="add",
                reason="Verified review decision.",
                knowledge_items=[
                    {
                        "title": "Verified review output",
                        "statement": "Review writes current knowledge only after verification.",
                        "topic_path": ["governance"],
                        "claim_kind": "procedure",
                    }
                ],
                project_root=project_root,
            )
        )

        assert payload["disposition"] == "add"
        entries = _run(store.list_entries("demo", project_root=project_root))
        assert [entry.title for entry in entries] == ["Verified review output"]
        markdown = _run(store.render_markdown("demo", include_details=True))
        assert "**Verified review output**" in markdown
        assert "verified 2026-08-18" in markdown
        assert _run(store.get_candidate(candidate.id)).status == "assimilated"
    finally:
        _run(backend.close())


def test_mcp_self_reported_verified_evidence_cannot_write_separated_truth(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
        monkeypatch.setattr(
            governance_handlers, "_record_state_event", lambda *_args, **_kwargs: None
        )
        suggested = governance_handlers.tool_govern_memory(
            "suggest",
            {
                "kind": "memory",
                "project_name": "demo",
                "category": "decision",
                "content": "An MCP caller cannot self-certify this as truth.",
                "source": "manual",
                "evidence_basis": "user_statement",
                "verification_outcome": "verified",
                "verification_refs": [],
            },
        )
        assert suggested["success"] is True
        candidate_id = suggested["entry_id"]
        store = backend.structured_store.knowledge_store
        evidence = _run(store.list_evidence(candidate_id))
        assert len(evidence) == 1
        assert evidence[0].verification_outcome == "unverified"

        cross_project = governance_handlers.tool_govern_memory(
            "decide",
            {
                "kind": "knowledge",
                "project_name": "other-project",
                "decision": "reject",
                "candidate_id": candidate_id,
                "reason": "A project-scoped caller cannot govern another project.",
            },
        )
        assert cross_project["success"] is False
        assert "another project" in cross_project["error"]

        decided = governance_handlers.tool_govern_memory(
            "decide",
            {
                "kind": "knowledge",
                "project_name": "demo",
                "decision": "confirm",
                "candidate_id": candidate_id,
                "reason": "The caller attempted to bypass trusted evidence admission.",
                "knowledge_items": [
                    {
                        "title": "Must not be written",
                        "statement": "Self-reported verification is not trusted evidence.",
                        "topic_path": ["governance"],
                        "claim_kind": "procedure",
                    }
                ],
            },
        )
        assert decided["success"] is False
        assert "verified evidence" in decided["error"]
        assert _run(store.list_entries("demo", project_root=project_root)) == []
    finally:
        _run(backend.close())


def test_retry_retires_unfinalized_job_candidates_before_fresh_extraction(
    tmp_path,
) -> None:
    """A failed pre-finalize attempt cannot poison the next job-bound plan."""

    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        previous = KnowledgeCandidate(
            id="previous-attempt-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The failed attempt proposed this unfinalized point.",
        )
        _run(store.save_candidate(previous))
        _run(
            store.save_evidence(
                KnowledgeEvidence(
                    id="previous-attempt-evidence",
                    project_name="demo",
                    candidate_id=previous.id,
                    distill_job_id="job-retry",
                    evidence_basis="transcript",
                    verification_outcome="unverified",
                )
            )
        )

        # The retry receives a new extraction decision.  Retiring the old
        # pending point is audit-preserving and prevents it from being mixed
        # into the fresh finalization candidate set.
        assert (
            _run(
                create_separated_candidates(
                    backend,
                    project_name="demo",
                    distill_job_id="job-retry",
                    candidate_arguments=[],
                )
            )
            == []
        )
        retired = _run(store.get_candidate(previous.id))
        assert retired is not None and retired.status == "deferred"
        decisions = _run(store.list_decisions(previous.id))
        assert len(decisions) == 1
        assert decisions[0].disposition == "defer"

        fresh = KnowledgeCandidate(
            id="fresh-attempt-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The fresh extraction proposes this replacement point.",
        )
        _run(store.save_candidate(fresh))
        _run(
            store.save_evidence(
                KnowledgeEvidence(
                    id="fresh-attempt-evidence",
                    project_name="demo",
                    candidate_id=fresh.id,
                    distill_job_id="job-retry",
                    evidence_basis="transcript",
                    verification_outcome="unverified",
                )
            )
        )
        assert _run(
            separated_job_candidate_ids(
                backend,
                project_name="demo",
                distill_job_id="job-retry",
            )
        ) == [fresh.id]
    finally:
        _run(backend.close())


def test_scope_clarification_is_not_treated_as_durable_knowledge() -> None:
    scope = KnowledgeEvidence(
        id="scope-evidence",
        project_name="demo",
        candidate_id="scope-candidate",
        evidence_basis="user_statement",
        verification_outcome="verified",
        verification_reason_codes=[
            "explicit_scope_clarification",
            "user_statement_refs_current",
        ],
    )
    workflow = KnowledgeEvidence(
        id="workflow-evidence",
        project_name="demo",
        candidate_id="workflow-candidate",
        evidence_basis="user_statement",
        verification_outcome="verified",
        verification_reason_codes=["explicit_user_workflow"],
    )

    assert _is_session_scope_clarification(scope) is True
    assert _is_session_scope_clarification(workflow) is False


def test_review_refinement_records_lineage_and_undo_restores_only_predecessor(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        old = _publish_entry(
            store,
            project_root,
            title="Evidence retention",
            statement="Keep original evidence for seven days.",
            topic_path=["ingestion"],
        )
        candidate = KnowledgeCandidate(
            id="refinement-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The retention period changed.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "refinement-evidence", project_root)
            )
        )

        result = _run(
            resolve_separated_review(
                backend,
                candidate_id=candidate.id,
                disposition="refine",
                reason="Current repository verification changed the retention period.",
                target_knowledge_ids=[old.id],
                knowledge_items=[
                    {
                        "title": "Evidence retention",
                        "statement": "Keep original evidence for thirty days.",
                        "topic_path": ["ingestion"],
                        "claim_kind": "implementation_fact",
                    }
                ],
                project_root=project_root,
            )
        )
        replacement_id = result["canonical_truth_ids"][0]
        decision = _run(store.get_decision(result["mutation_id"]))
        assert decision is not None
        assert decision.predecessor_truth_ids == [old.id]
        assert decision.predecessor_entries[0].id == old.id
        assert decision.predecessor_entries[0].statement == old.statement
        assert (
            _run(
                store.get_entry(old.id, project_name="demo", project_root=project_root)
            )
            is None
        )
        assert (
            _run(
                store.get_entry(
                    replacement_id, project_name="demo", project_root=project_root
                )
            )
            is not None
        )
        assert [
            entry.id
            for entry in _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="evidence retention",
                    limit=10,
                    project_root=project_root,
                )
            )
        ] == [replacement_id]

        with pytest.raises(ValueError, match="belongs to another project"):
            _run(
                undo_separated_review(
                    backend,
                    decision_id=decision.id,
                    reason="A different project cannot undo this decision.",
                    project_root=project_root,
                    expected_project_name="other-project",
                )
            )

        undo = _run(
            undo_separated_review(
                backend,
                decision_id=decision.id,
                reason="Repository check was rolled back.",
                project_root=project_root,
            )
        )
        assert undo["restored_truth_ids"] == [old.id]
        assert undo["retired_truth_ids"] == [replacement_id]
        restored = _run(
            store.get_entry(old.id, project_name="demo", project_root=project_root)
        )
        assert restored is not None
        assert restored.statement == old.statement
        assert restored.revision == old.revision + 1
        assert (
            _run(
                store.get_entry(
                    replacement_id, project_name="demo", project_root=project_root
                )
            )
            is None
        )
        assert [
            entry.id
            for entry in _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    query="evidence retention",
                    limit=10,
                    project_root=project_root,
                )
            )
        ] == [old.id]
        with pytest.raises(ValueError, match="already been undone"):
            _run(
                undo_separated_review(
                    backend,
                    decision_id=decision.id,
                    reason="A duplicate undo must fail.",
                    project_root=project_root,
                )
            )
    finally:
        _run(backend.close())


def test_review_supersede_splits_a_broad_current_entry_without_overlap(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        broad = _publish_entry(
            store,
            project_root,
            title="Publish and validate",
            statement="Publish related product records transactionally and validate final API output.",
            topic_path=["publication"],
        )
        candidate = KnowledgeCandidate(
            id="split-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The broad rule should become two independently retrievable rules.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "split-evidence", project_root)
            )
        )

        result = _run(
            resolve_separated_review(
                backend,
                candidate_id=candidate.id,
                disposition="supersede",
                reason="The current entry mixes independent publication and API rules.",
                target_knowledge_ids=[broad.id],
                knowledge_items=[
                    {
                        "title": "Transactional publication",
                        "statement": "Publish related product records in one transaction.",
                        "topic_path": ["publication"],
                        "claim_kind": "procedure",
                    },
                    {
                        "title": "Final API validation",
                        "statement": "Validate final API output after product assembly.",
                        "topic_path": ["api"],
                        "claim_kind": "procedure",
                    },
                ],
                project_root=project_root,
            )
        )

        current = _run(store.list_entries("demo", project_root=project_root))
        decision = _run(store.get_decision(result["mutation_id"]))
        assert decision is not None
        assert (
            _run(
                store.get_entry(
                    broad.id, project_name="demo", project_root=project_root
                )
            )
            is None
        )
        assert {entry.title for entry in current} == {
            "Transactional publication",
            "Final API validation",
        }
        assert decision.predecessor_truth_ids == [broad.id]
        assert decision.canonical_truth_ids == result["canonical_truth_ids"]
    finally:
        _run(backend.close())


def test_review_preflights_target_and_rejects_a_second_terminal_decision(
    tmp_path,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="target-preflight-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The verified replacement must have a current target.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(
                    candidate,
                    "target-preflight-evidence",
                    project_root,
                )
            )
        )

        with pytest.raises(ValueError, match="target is not current"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="refine",
                    reason="The target was intentionally omitted by this regression test.",
                    target_knowledge_ids=["missing-target"],
                    knowledge_items=[
                        {
                            "title": "Orphan must not exist",
                            "statement": "A failed refinement must not create truth.",
                            "topic_path": ["review"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.list_entries("demo", project_root=project_root)) == []
        assert _run(store.list_decisions(candidate.id)) == []
        assert _run(store.get_candidate(candidate.id)).status == "pending"

        first = _run(
            resolve_separated_review(
                backend,
                candidate_id=candidate.id,
                disposition="add",
                reason="The verified candidate has one atomic durable outcome.",
                knowledge_items=[
                    {
                        "title": "One terminal outcome",
                        "statement": "A candidate receives one terminal assimilation decision.",
                        "topic_path": ["review"],
                        "claim_kind": "procedure",
                    }
                ],
                project_root=project_root,
            )
        )
        with pytest.raises(ValueError, match="terminal decision"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="add",
                    reason="A repeated decision must not create duplicate truth.",
                    knowledge_items=[
                        {
                            "title": "Duplicate must not exist",
                            "statement": "A terminal candidate cannot write another entry.",
                            "topic_path": ["review"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert len(_run(store.list_entries("demo", project_root=project_root))) == 1
        assert _run(store.list_decisions(candidate.id)) == []
        assert first["canonical_truth_ids"]
    finally:
        _run(backend.close())


def test_review_reopens_candidate_source_before_truth_write(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="stale-source-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="A historical verified flag must not certify changed content.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "stale-source-evidence", project_root)
            )
        )
        (project_root / "README.md").write_text(
            "# Demo\n\nThe source changed after the earlier verification.\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="current verified evidence"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="add",
                    reason="The stored verified flag is intentionally stale.",
                    knowledge_items=[
                        {
                            "title": "Must remain pending",
                            "statement": "Changed evidence cannot write current truth.",
                            "topic_path": ["review"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
        assert _run(store.list_entries("demo")) == []
    finally:
        _run(backend.close())


def test_truth_transaction_failure_keeps_candidate_retryable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="transaction-failure-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="A failed truth transaction remains retryable.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(
                    candidate,
                    "transaction-failure-evidence",
                    project_root,
                )
            )
        )

        async def fail_transaction(**_kwargs):
            raise RuntimeError("simulated SQLite failure")

        monkeypatch.setattr(store, "apply_truth_mutation", fail_transaction)
        with pytest.raises(RuntimeError, match="simulated SQLite failure"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="add",
                    reason="Exercise the commit boundary.",
                    knowledge_items=[
                        {
                            "title": "Retryable commit",
                            "statement": "Failed truth commits do not terminalize candidates.",
                            "topic_path": ["storage"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
        assert _run(store.list_entries("demo")) == []
    finally:
        _run(backend.close())


def test_confirm_missing_target_has_no_terminal_side_effect(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="missing-confirm-target-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="Confirmation must still point to current knowledge.",
        )
        _run(store.save_candidate(candidate))
        with pytest.raises(ValueError, match="no longer current"):
            _run(
                record_assimilation_result(
                    backend,
                    candidate=candidate,
                    point={
                        "disposition": "confirm",
                        "matched_truth_ids": ["deleted-knowledge"],
                        "reason": "The planned target disappeared before apply.",
                    },
                    project_root=project_root,
                    source_refs=[
                        ProjectKnowledgeSourceRef(
                            label="README.md",
                            target=(project_root / "README.md").resolve().as_uri(),
                            kind="repository",
                            digest=hashlib.sha256(
                                (project_root / "README.md").read_bytes()
                            ).hexdigest(),
                        )
                    ],
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
        assert _run(store.list_decisions(candidate.id)) == []
    finally:
        _run(backend.close())


def test_identical_refine_fails_before_duplicate_target_mutation(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="Stable rule",
            statement="Keep this exact current statement.",
            topic_path=["review"],
        )
        candidate = KnowledgeCandidate(
            id="identical-refine-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The provider proposed a no-op refinement.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "identical-refine-evidence", project_root)
            )
        )

        with pytest.raises(ValueError, match="identical.*use confirm"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="refine",
                    reason="No-op refinement must become confirmation.",
                    target_knowledge_ids=[current.id],
                    knowledge_items=[
                        {
                            "title": current.title,
                            "statement": current.statement,
                            "topic_path": list(current.module_path),
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
        assert [item.id for item in _run(store.list_entries("demo"))] == [current.id]
    finally:
        _run(backend.close())


def test_review_reopens_target_source_before_confirmation(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    candidate_path = project_root / "CURRENT.md"
    candidate_path.write_text("The candidate source remains current.\n", encoding="utf-8")
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="Source-bound truth",
            statement="Current truth remains valid only while its source is current.",
            topic_path=["review"],
        )
        candidate = KnowledgeCandidate(
            id="target-source-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="Confirm the existing source-bound truth.",
        )
        locator = "CURRENT.md"
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                KnowledgeEvidence(
                    id="target-source-evidence",
                    project_name="demo",
                    candidate_id=candidate.id,
                    evidence_basis="repository",
                    verification_outcome="verified",
                    verification_refs=[
                        EvidenceRef(
                            kind="repository",
                            locator=locator,
                            locator_sha256=hashlib.sha256(
                                locator.encode("utf-8")
                            ).hexdigest(),
                            content_sha256=hashlib.sha256(
                                candidate_path.read_bytes()
                            ).hexdigest(),
                        )
                    ],
                    verified_at=VERIFIED_AT,
                )
            )
        )
        (project_root / "README.md").write_text(
            "# Demo\n\nThe old target source is now stale.\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="target source is no longer current"):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="confirm",
                    reason="A stale target cannot be reconfirmed from old metadata.",
                    target_knowledge_ids=[current.id],
                    project_root=project_root,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
    finally:
        _run(backend.close())


def test_review_undo_history_is_bounded_with_its_version_snapshots(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        knowledge_store_module,
        "_MAX_UNDO_MUTATIONS_PER_PROJECT",
        2,
    )
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="Bounded policy",
            statement="Policy revision zero.",
            topic_path=["review"],
        )
        refinement_results = []
        oldest_version_id = None
        for index in range(1, 4):
            candidate = KnowledgeCandidate(
                id=f"bounded-candidate-{index}",
                project_name="demo",
                candidate_type="memory",
                statement=f"Policy revision {index} is now current.",
            )
            _run(store.save_candidate(candidate))
            _run(
                store.save_evidence(
                    _verified_evidence(
                        candidate,
                        f"bounded-evidence-{index}",
                        project_root,
                    )
                )
            )
            result = _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="refine",
                    reason=f"Apply bounded revision {index}.",
                    target_knowledge_ids=[current.id],
                    knowledge_items=[
                        {
                            "title": "Bounded policy",
                            "statement": f"Policy revision {index}.",
                            "topic_path": ["review"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
            refinement_results.append(result)
            if index == 1:
                oldest_mutation = _run(store.get_mutation(result["mutation_id"]))
                assert oldest_mutation is not None
                oldest_version_id = oldest_mutation.predecessor_version_ids[0]
            current = _run(
                store.get_entry(
                    result["canonical_truth_ids"][0],
                    project_name="demo",
                )
            )
            assert current is not None

        mutations = _run(store.list_mutations("demo"))
        assert [item.id for item in mutations] == [
            refinement_results[1]["mutation_id"],
            refinement_results[2]["mutation_id"],
        ]
        oldest_refinement = refinement_results[0]["mutation_id"]
        assert _run(store.get_mutation(oldest_refinement)) is None
        assert oldest_version_id is not None
        assert _run(store.get_version(oldest_version_id)) is None
    finally:
        _run(backend.close())


def test_review_undo_rejects_a_replacement_that_has_a_successor(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        original = _publish_entry(
            store,
            project_root,
            title="Current policy",
            statement="Keep the original policy.",
            topic_path=["review"],
        )

        def verified_candidate(candidate_id: str, statement: str) -> KnowledgeCandidate:
            candidate = KnowledgeCandidate(
                id=candidate_id,
                project_name="demo",
                candidate_type="memory",
                statement=statement,
            )
            _run(store.save_candidate(candidate))
            _run(
                store.save_evidence(
                    _verified_evidence(
                        candidate,
                        f"{candidate_id}-evidence",
                        project_root,
                    )
                )
            )
            return candidate

        middle_candidate = verified_candidate("undo-middle-candidate", "Middle policy.")
        middle = _run(
            resolve_separated_review(
                backend,
                candidate_id=middle_candidate.id,
                disposition="refine",
                reason="The first verified replacement is current.",
                target_knowledge_ids=[original.id],
                knowledge_items=[
                    {
                        "title": "Current policy",
                        "statement": "Keep the middle policy.",
                        "topic_path": ["review"],
                        "claim_kind": "procedure",
                    }
                ],
                project_root=project_root,
            )
        )
        newest_candidate = verified_candidate("undo-newest-candidate", "Newest policy.")
        _run(
            resolve_separated_review(
                backend,
                candidate_id=newest_candidate.id,
                disposition="refine",
                reason="The second verified replacement is current.",
                target_knowledge_ids=middle["canonical_truth_ids"],
                knowledge_items=[
                    {
                        "title": "Current policy",
                        "statement": "Keep the newest policy.",
                        "topic_path": ["review"],
                        "claim_kind": "procedure",
                    }
                ],
                project_root=project_root,
            )
        )
        first_decision = _run(store.get_decision(middle["mutation_id"]))
        assert first_decision is not None
        with pytest.raises(ValueError, match="later replacement"):
            _run(
                undo_separated_review(
                    backend,
                    decision_id=first_decision.id,
                    reason="The successor must be undone first.",
                    project_root=project_root,
                )
            )
        current = _run(store.list_entries("demo", project_root=project_root))
        assert [entry.statement for entry in current] == ["Keep the newest policy."]
    finally:
        _run(backend.close())
