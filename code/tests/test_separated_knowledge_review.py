"""Review decisions must use the same evidence and decision boundary as Dream."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import pytest

from harness_mem.commands.knowledge_assimilation import (
    assimilation_decision_id,
    record_assimilation_result,
    resolve_separated_review,
)
from harness_mem.commands.separated_assimilation import (
    _is_session_scope_clarification,
    apply_separated_assimilation,
    create_separated_candidates,
    prepare_separated_assimilation,
    separated_job_candidate_ids,
)
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeEvidence,
    ProjectProfile,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.evidence import EvidenceRef
from harness_mem.mcp import governance_handlers
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


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


def test_apply_accepts_multiple_atomic_results_for_one_candidate(tmp_path) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="multi-result-candidate",
            project_name="demo",
            candidate_type="memory",
            statement=(
                "The session established independent ingestion and retrieval rules."
            ),
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "multi-result-evidence", project_root)
            )
        )
        points = [
            {
                "candidate_id": candidate.id,
                "answer_status": "ANSWERED",
                "disposition": "add",
                "matched_truth_ids": [],
                "knowledge_items": [
                    {
                        "title": "Ingestion rule",
                        "statement": "Ingestion uses its own current rule.",
                        "topic_path": ["Ingestion"],
                        "claim_kind": "procedure",
                    }
                ],
                "reason": "The session established an independent ingestion rule.",
            },
            {
                "candidate_id": candidate.id,
                "answer_status": "ANSWERED",
                "disposition": "add",
                "matched_truth_ids": [],
                "knowledge_items": [
                    {
                        "title": "Retrieval rule",
                        "statement": "Retrieval uses its own current rule.",
                        "topic_path": ["Retrieval"],
                        "claim_kind": "procedure",
                    }
                ],
                "reason": "The session established an independent retrieval rule.",
            },
        ]

        result = _run(
            apply_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id],
                plan={
                    "version": "separated-v1",
                    "candidate_ids": [candidate.id],
                    "point_count": 2,
                    "provider_candidate_ids": [candidate.id],
                    "points": points,
                },
            )
        )

        assert result["promoted"] == 2
        assert len(result["points"]) == 2
        assert {entry.title for entry in _run(store.list_entries("demo"))} == {
            "Ingestion rule",
            "Retrieval rule",
        }
    finally:
        _run(backend.close())


def test_missing_later_candidate_blocks_all_results_before_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidates = [
            KnowledgeCandidate(
                id=f"candidate-{index}",
                project_name="demo",
                candidate_type="memory",
                statement=f"Unverified candidate {index} stays outside current knowledge.",
            )
            for index in (1, 2)
        ]
        for candidate in candidates:
            _run(store.save_candidate(candidate))
            _run(
                store.save_evidence(
                    KnowledgeEvidence(
                        id=f"evidence-{candidate.id}",
                        project_name="demo",
                        candidate_id=candidate.id,
                        distill_job_id="missing-job",
                        evidence_basis="transcript",
                        verification_outcome="unverified",
                    )
                )
            )
        prepared = _run(
            prepare_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id for candidate in candidates],
            )
        )
        plan = {
            "version": "separated-v1",
            "candidate_ids": list(prepared.candidate_ids),
            "provider_candidate_ids": list(prepared.eligible_candidate_ids),
            "point_count": len(prepared.automatic_points),
            "points": [dict(point) for point in prepared.automatic_points],
        }
        original_get = store.get_candidate
        reads: dict[str, int] = {}

        async def disappear_after_prepare(candidate_id: str):
            reads[candidate_id] = reads.get(candidate_id, 0) + 1
            if candidate_id == candidates[1].id and reads[candidate_id] >= 2:
                return None
            return await original_get(candidate_id)

        monkeypatch.setattr(store, "get_candidate", disappear_after_prepare)
        with pytest.raises(ValueError, match="separated candidate is missing"):
            _run(
                apply_separated_assimilation(
                    backend,
                    project_name="demo",
                    project_root=str(project_root),
                    candidate_ids=[candidate.id for candidate in candidates],
                    plan=plan,
                )
            )
        for candidate in candidates:
            stored = _run(original_get(candidate.id))
            assert stored is not None
            assert stored.status == "pending"
        assert _run(store.list_entries("demo")) == []
    finally:
        _run(backend.close())


def test_apply_does_not_report_success_when_normal_search_cannot_read_write(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="search-readback-required",
            project_name="demo",
            candidate_type="memory",
            statement="A current knowledge write must be readable through normal search.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(candidate, "search-readback-evidence", project_root)
            )
        )

        async def missing_from_normal_search(*_args, **_kwargs):
            return []

        monkeypatch.setattr(
            "harness_mem.read_knowledge.search_current_knowledge",
            missing_from_normal_search,
        )
        with pytest.raises(
            RuntimeError,
            match="not readable through normal search",
        ):
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
                                        "title": "Search readback is required",
                                        "statement": candidate.statement,
                                        "topic_path": ["Memory consistency"],
                                        "claim_kind": "procedure",
                                    }
                                ],
                                "reason": "The verified write must be visible to its normal reader.",
                            }
                        ],
                    },
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
    finally:
        _run(backend.close())


def test_review_does_not_report_success_when_normal_search_cannot_read_write(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            id="review-search-readback-required",
            project_name="demo",
            candidate_type="memory",
            statement="Review writes must be readable through normal search.",
        )
        _run(store.save_candidate(candidate))
        _run(
            store.save_evidence(
                _verified_evidence(
                    candidate,
                    "review-search-readback-evidence",
                    project_root,
                )
            )
        )

        async def missing_from_normal_search(*_args, **_kwargs):
            return []

        monkeypatch.setattr(
            "harness_mem.read_knowledge.search_current_knowledge",
            missing_from_normal_search,
        )
        with pytest.raises(
            RuntimeError,
            match="not readable through normal search",
        ):
            _run(
                resolve_separated_review(
                    backend,
                    candidate_id=candidate.id,
                    disposition="add",
                    reason="Review must prove the user-visible write.",
                    knowledge_items=[
                        {
                            "title": "Review search readback",
                            "statement": candidate.statement,
                            "topic_path": ["Memory consistency"],
                            "claim_kind": "procedure",
                        }
                    ],
                    project_root=project_root,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
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
        store.apply_current_change(
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


def test_govern_memory_deletes_current_knowledge_and_sources(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="Obsolete current fact",
            statement="This fact is no longer current.",
            topic_path=["review"],
        )
        assert _run(store.list_sources(current.id))

        deleted = governance_handlers.tool_govern_memory(
            "decide",
            {
                "kind": "knowledge",
                "decision": "delete",
                "project_name": "demo",
                "target_knowledge_ids": [current.id],
            },
        )

        assert deleted == {
            "governance_action": "decide",
            "success": True,
            "deleted_knowledge_ids": [current.id],
        }
        assert _run(store.get_entry(current.id, project_name="demo")) is None
        assert _run(store.list_sources(current.id)) == []
        assert _run(
            search_current_knowledge(
                backend,
                project_name="demo",
                query="obsolete current fact",
                limit=10,
                project_root=project_root,
            )
        ) == []
    finally:
        _run(backend.close())


def test_govern_memory_delete_rejects_cross_project_and_missing_targets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
        store = backend.structured_store.knowledge_store
        current = _publish_entry(
            store,
            project_root,
            title="Project-owned fact",
            statement="Only the owning project may delete this fact.",
            topic_path=["review"],
        )

        for project_name, target_id in (
            ("other-project", current.id),
            ("demo", "missing-current-knowledge"),
        ):
            result = governance_handlers.tool_govern_memory(
                "decide",
                {
                    "kind": "knowledge",
                    "decision": "delete",
                    "project_name": project_name,
                    "target_knowledge_ids": [target_id],
                },
            )
            assert result["success"] is False
            assert "not current project knowledge" in result["error"]

        assert [entry.id for entry in _run(store.list_entries("demo"))] == [current.id]
    finally:
        _run(backend.close())


@pytest.mark.parametrize(
    "invalid_arguments",
    [
        {},
        {"target_knowledge_ids": ["one", "two"]},
        {
            "target_knowledge_ids": ["one"],
            "candidate_id": "candidate-one",
        },
        {
            "target_knowledge_ids": ["one"],
            "knowledge_items": [],
        },
    ],
)
def test_govern_memory_delete_rejects_invalid_argument_shapes(
    invalid_arguments,
) -> None:
    result = governance_handlers.tool_govern_memory(
        "decide",
        {
            "kind": "knowledge",
            "decision": "delete",
            "project_name": "demo",
            **invalid_arguments,
        },
    )

    assert result["success"] is False
    assert "exactly one target_knowledge_ids value" in result["error"]


def test_refine_assimilation_replays_after_predecessor_was_deleted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
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

        from harness_mem.read_knowledge import search_current_knowledge

        search_calls = 0

        async def fail_first_readback(*args, **kwargs):
            nonlocal search_calls
            search_calls += 1
            if search_calls == 1:
                return []
            return await search_current_knowledge(*args, **kwargs)

        monkeypatch.setattr(
            "harness_mem.read_knowledge.search_current_knowledge",
            fail_first_readback,
        )
        with pytest.raises(
            RuntimeError,
            match="not readable through normal search",
        ):
            _run(
                apply_separated_assimilation(
                    backend,
                    project_name="demo",
                    project_root=str(project_root),
                    candidate_ids=[candidate.id],
                    plan=plan,
                )
            )
        assert _run(store.get_candidate(candidate.id)).status == "pending"
        second = _run(
            apply_separated_assimilation(
                backend,
                project_name="demo",
                project_root=str(project_root),
                candidate_ids=[candidate.id],
                plan=plan,
            )
        )

        assert second["promoted"] == 1
        assert search_calls == 2
        current = _run(store.list_entries("demo", project_root=project_root))
        assert [(entry.title, entry.statement) for entry in current] == [
            ("Evidence retention", "Keep original evidence for fourteen days.")
        ]
        assert _run(store.get_entry(old.id, project_name="demo")) is None
        assert _run(store.list_sources(old.id)) == []
    finally:
        _run(backend.close())


def test_refine_retry_requires_its_committed_transaction_receipt(tmp_path) -> None:
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
            id="uncommitted-refine-candidate",
            project_name="demo",
            candidate_type="memory",
            statement="The verified retention requirement changed to fourteen days.",
        )
        _run(store.save_candidate(candidate))
        point = {
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
        identity = "\0".join(
            [
                "demo",
                "Ingestion",
                "Evidence retention",
                "Keep original evidence for fourteen days.",
            ]
        )
        replacement = KnowledgeEntry(
            id=str(uuid5(NAMESPACE_URL, f"harness-mem:knowledge:{identity}")),
            project_name="demo",
            module_path=["Ingestion"],
            title="Evidence retention",
            statement="Keep original evidence for fourteen days.",
            verified_at=VERIFIED_AT,
        )
        decision_id = assimilation_decision_id(
            candidate_id=candidate.id,
            disposition="refine",
            knowledge_ids=[replacement.id],
            predecessor_ids=[old.id],
            reason=point["reason"],
        )

        # Simulate unrelated/corrupt state that merely resembles a completed retry:
        # the predecessor disappeared and the deterministic replacement ID exists,
        # but this decision never committed its canonical transaction.
        backend.structured_store.delete_record_payload("knowledge_entries", old.id)
        backend.structured_store.write_record_payload(
            "knowledge_entries",
            replacement.id,
            replacement.to_dict(),
        )
        assert _run(store.current_change_committed(decision_id)) is False

        with pytest.raises(
            ValueError,
            match="replacement target is not current knowledge",
        ):
            _run(
                record_assimilation_result(
                    backend,
                    candidate=candidate,
                    point=point,
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
        assert _run(store.get_entry(replacement.id, project_name="demo")) == replacement
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


def test_mcp_repository_suggestion_uses_saved_project_root(tmp_path, monkeypatch) -> None:
    project_root = _project_root(tmp_path)
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        _run(
            LocalProjectProfileStore(backend.data_dir).save(
                ProjectProfile(project_name="demo", project_root=str(project_root))
            )
        )
        monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
        monkeypatch.setattr(
            governance_handlers, "_record_state_event", lambda *_args, **_kwargs: None
        )
        source = project_root / "README.md"
        suggested = governance_handlers.tool_govern_memory(
            "suggest",
            {
                "kind": "memory",
                "project_name": "demo",
                "category": "decision",
                "content": "Repository-backed maintenance can write current knowledge.",
                "source": "README.md",
                "evidence_basis": "repository",
                "verification_outcome": "verified",
                "verification_refs": [
                    {
                        "kind": "repository",
                        "locator": "README.md",
                        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ],
            },
        )
        candidate_id = suggested["entry_id"]
        evidence = _run(
            backend.structured_store.knowledge_store.list_evidence(candidate_id)
        )
        assert evidence[0].verification_outcome == "verified"

        decided = governance_handlers.tool_govern_memory(
            "decide",
            {
                "kind": "knowledge",
                "project_name": "demo",
                "decision": "confirm",
                "candidate_id": candidate_id,
                "disposition": "add",
                "reason": "Exercise the project-scoped repository maintenance path.",
                "knowledge_items": [
                    {
                        "title": "Repository-backed maintenance",
                        "statement": (
                            "Repository-backed maintenance can write current knowledge."
                        ),
                        "topic_path": ["governance"],
                        "claim_kind": "procedure",
                    }
                ],
            },
        )
        assert decided["success"] is True
        assert [
            item.statement
            for item in _run(
                search_current_knowledge(
                    backend,
                    project_name="demo",
                    project_root=project_root,
                    query="repository-backed maintenance",
                    limit=10,
                )
            )
        ] == ["Repository-backed maintenance can write current knowledge."]
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


def test_retry_reuses_terminal_candidate_from_failed_finalization(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        arguments = {
            "kind": "memory",
            "content": "A retry must finish a candidate already applied before finalization failed.",
            "evidence_basis": "transcript",
            "verification_outcome": "unverified",
            "verification_refs": [],
        }
        first = _run(
            create_separated_candidates(
                backend,
                project_name="demo",
                distill_job_id="job-terminal-retry",
                candidate_arguments=[arguments],
            )
        )
        store = backend.structured_store.knowledge_store
        candidate = _run(store.get_candidate(first[0]))
        assert candidate is not None
        _run(
            record_assimilation_result(
                backend,
                candidate=candidate,
                point={
                    "disposition": "no_write",
                    "reason": "The unverified point cannot enter current knowledge.",
                },
            )
        )
        assert _run(store.get_candidate(candidate.id)).status == "assimilated"

        replay = _run(
            create_separated_candidates(
                backend,
                project_name="demo",
                distill_job_id="job-terminal-retry",
                candidate_arguments=[arguments],
            )
        )

        assert replay == first
        assert len(_run(store.list_evidence(candidate.id))) == 1
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


def test_review_replace_splits_a_broad_current_entry_without_overlap(
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
                disposition="replace",
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
        assert result["changed"] is True
        assert len(result["canonical_truth_ids"]) == 2
        assert _run(store.list_sources(broad.id)) == []
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

        monkeypatch.setattr(store, "apply_current_change", fail_transaction)
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


def test_review_blocks_stale_confirmation_but_allows_verified_replacement(
    tmp_path,
) -> None:
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

        replacement = _run(
            resolve_separated_review(
                backend,
                candidate_id=candidate.id,
                disposition="refine",
                reason="Fresh evidence may replace truth whose old source is stale.",
                knowledge_items=[
                    {
                        "title": "Source-bound truth",
                        "statement": "Current truth now follows the fresh candidate source.",
                        "topic_path": ["review"],
                        "claim_kind": "implementation_fact",
                    }
                ],
                target_knowledge_ids=[current.id],
                project_root=project_root,
            )
        )
        assert replacement["changed"] is True
        assert len(replacement["canonical_truth_ids"]) == 1
        assert _run(store.get_entry(current.id, project_name="demo")) is None
    finally:
        _run(backend.close())
