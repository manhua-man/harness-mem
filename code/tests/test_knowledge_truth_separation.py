"""SQLite-authoritative knowledge, source, undo, and workspace invariants."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AssimilationDecision as ProviderAssimilationDecision,
    validate_atomic_knowledge_statement,
)
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    _candidate_required_identifiers,
    _current_truth_handles,
    _validate_candidate_specificity,
    _normalize_split_knowledge_items,
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


def test_candidate_projection_exposes_exact_technical_terms() -> None:
    assert _candidate_required_identifiers(
        "Revision identity must not rely only on session_id, mtime, and size."
    ) == ["identity", "mtime", "revision", "session_id", "size"]


def test_split_knowledge_drops_enumerative_umbrella_beside_successors() -> None:
    normalized = _normalize_split_knowledge_items(
        [
            {
                "title": "Platform capability declaration",
                "statement": (
                    "Adapters must declare paths, samples, project matching, "
                    "growth, and lossless reconstruction capabilities."
                ),
            },
            {
                "title": "Path qualification",
                "statement": "Adapters must verify real paths and samples.",
            },
        ]
    )

    assert normalized == [
        {
            "title": "Path qualification",
            "statement": "Adapters must verify real paths and samples.",
        }
    ]


def test_assimilation_specificity_rejects_dropped_technical_identifiers() -> None:
    prepared = SeparatedPreparedAssimilation(
        project_name="demo",
        project_root="demo",
        candidate_ids=("candidate-1",),
        eligible_candidate_ids=("candidate-1",),
        automatic_points=(),
        answer_status_by_candidate={"candidate-1": "ANSWERED"},
        truth_by_handle={},
        manifest={
            "verified_candidates": [
                {
                    "candidate_id": "candidate-1",
                    "statement": (
                        "每个 chunk 必须保存 status、attempt、lease 和 result；"
                        "中断后从未完成 chunk resume。"
                    ),
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="attempt, lease, result, resume, status"):
        _validate_candidate_specificity(
            prepared,
            candidate_id="candidate-1",
            statements=["每个 chunk 必须保存可恢复检查点。"],
        )

    _validate_candidate_specificity(
        prepared,
        candidate_id="candidate-1",
        statements=[
            "每个 chunk 必须持久化 status、attempt、lease 和 result，"
            "并从未完成 chunk resume。"
        ],
    )


def test_atomic_statement_rejects_mixed_qualification_obligations() -> None:
    with pytest.raises(ValueError, match="independent actions"):
        validate_atomic_knowledge_statement(
            "每个支持的平台适配器必须声明 hook 与 transcript 支持，"
            "并具备真实路径、真实样本、项目匹配规则、增长测试和零丢失重建测试。"
        )


def test_atomic_statement_allows_one_completeness_obligation() -> None:
    statement = "最终 review 必须记录状态、结论、证据和验证日期。"
    assert validate_atomic_knowledge_statement(statement) == statement


def test_atomic_statement_splits_chunk_state_from_resume_behavior() -> None:
    with pytest.raises(ValueError, match="independent actions"):
        validate_atomic_knowledge_statement(
            "每个 chunk 必须持久化状态、attempt、lease 和结果，"
            "并从未完成的 chunk 继续处理。"
        )


def test_assimilation_rejects_reusing_a_truth_target_after_mutation() -> None:
    prepared = SeparatedPreparedAssimilation(
        project_name="demo",
        project_root="demo",
        candidate_ids=("candidate-refine", "candidate-confirm"),
        eligible_candidate_ids=("candidate-refine", "candidate-confirm"),
        automatic_points=(),
        answer_status_by_candidate={
            "candidate-refine": "ANSWERED",
            "candidate-confirm": "ANSWERED",
        },
        truth_by_handle={"T1": "truth-1"},
        manifest={
            "verified_candidates": [
                {
                    "candidate_id": "candidate-refine",
                    "statement": "candidate-one mechanism remains current.",
                },
                {
                    "candidate_id": "candidate-confirm",
                    "statement": "candidate-two confirms the old truth.",
                },
            ]
        },
    )
    decision = ProviderAssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": "candidate-refine",
                    "disposition": "refine",
                    "matched_truth_handles": ["T1"],
                    "knowledge_items": [
                        {
                            "title": "Current mechanism",
                            "statement": "candidate-one mechanism remains current.",
                            "topic_path": ["demo"],
                            "claim_kind": "implementation_fact",
                        }
                    ],
                    "reason": "The current truth needs this verified wording correction.",
                },
                {
                    "candidate_id": "candidate-confirm",
                    "disposition": "confirm",
                    "matched_truth_handles": ["T1"],
                    "knowledge_items": [],
                    "reason": "The existing current truth already covers this point.",
                },
            ]
        }
    )

    with pytest.raises(ValueError, match="reused across points"):
        validate_separated_assimilation_decision(prepared, decision)


def test_assimilation_rejects_non_writing_point_with_truth_handle() -> None:
    prepared = SeparatedPreparedAssimilation(
        project_name="demo",
        project_root="demo",
        candidate_ids=("candidate-1",),
        eligible_candidate_ids=("candidate-1",),
        automatic_points=(),
        answer_status_by_candidate={"candidate-1": "ANSWERED"},
        truth_by_handle={"T1": "truth-1"},
        manifest={
            "verified_candidates": [
                {"candidate_id": "candidate-1", "statement": "One verified point."}
            ]
        },
    )
    decision = ProviderAssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": "candidate-1",
                    "disposition": "no_write",
                    "matched_truth_handles": ["T1"],
                    "knowledge_items": [],
                    "reason": "This point is already covered without a new write.",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="no_write must not target"):
        validate_separated_assimilation_decision(prepared, decision)


def test_assimilation_specificity_preserves_positive_contrast_mechanism() -> None:
    prepared = SeparatedPreparedAssimilation(
        project_name="demo",
        project_root="demo",
        candidate_ids=("candidate-1",),
        eligible_candidate_ids=("candidate-1",),
        automatic_points=(),
        answer_status_by_candidate={"candidate-1": "ANSWERED"},
        truth_by_handle={},
        manifest={
            "verified_candidates": [
                {
                    "candidate_id": "candidate-1",
                    "statement": (
                        "revision 应使用内容哈希标识，而不能只依赖 session_id、"
                        "mtime 和 size。"
                    ),
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="positive mechanism"):
        _validate_candidate_specificity(
            prepared,
            candidate_id="candidate-1",
            statements=["revision 身份不得仅依赖 session_id、mtime 和 size。"],
        )

    _validate_candidate_specificity(
        prepared,
        candidate_id="candidate-1",
        statements=[
            "revision 身份应使用内容哈希标识，不得仅依赖 session_id、mtime 和 size。"
        ],
    )


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


def test_source_recheck_refreshes_verification_without_rewriting_knowledge(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = _candidate("refresh-candidate")
        entry = _entry("knowledge-refresh", "Current source-backed statement.")
        _run(store.save_candidate(candidate))
        _apply(
            store,
            candidate=candidate,
            decision=_decision("refresh-seed", candidate.id, "add", [entry]),
            added=[entry],
        )
        before = _run(store.get_entry(entry.id, project_name="demo"))
        assert before is not None
        checked_at = datetime(2026, 8, 21, tzinfo=timezone.utc)

        result = _run(
            store.refresh_entry_verification(
                project_name="demo",
                entry_id=entry.id,
                verified_at=checked_at,
                refresh_id="dream-run-refresh",
            )
        )
        after = _run(store.get_entry(entry.id, project_name="demo"))
        sources = _run(store.list_sources(entry.id))

        assert result["replayed"] is False
        assert after is not None
        assert after.statement == before.statement
        assert after.title == before.title
        assert after.module_path == before.module_path
        assert after.revision == before.revision
        assert after.created_at == before.created_at
        assert after.verified_at == checked_at
        assert sources and all(source.verified_at == checked_at for source in sources)
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


def test_truth_mutation_deduplicates_repeated_source_refs(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        candidate = _candidate("candidate-duplicate-source")
        entry = _entry("knowledge-duplicate-source", "Store one source row per locator.")
        decision = _decision("mutation-duplicate-source", candidate.id, "add", [entry])
        source = _source()
        _run(store.save_candidate(candidate))

        result = _run(
            store.apply_truth_mutation(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=decision,
                added_entries=[entry],
                predecessor_entries=[],
                source_refs_by_entry={entry.id: [source, source]},
            )
        )

        sources = _run(store.list_sources(entry.id))
        assert result["replayed"] is False
        assert len(sources) == 1
        assert sources[0].locator == source.target
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
        candidate.status = "assimilated"
        _run(store.save_candidate(candidate))
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


def test_current_truth_selection_keeps_relevant_cjk_entries_over_cap(
    tmp_path, monkeypatch
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        store = backend.structured_store.knowledge_store
        relevant = [
            KnowledgeEntry(
                id=f"adapter-{index}",
                project_name="demo",
                module_path=["平台适配器"],
                title=title,
                statement=statement,
                verified_at=VERIFIED_AT,
            )
            for index, (title, statement) in enumerate(
                [
                    ("适配器路径样本", "适配器必须声明真实路径、真实样本和项目匹配规则。"),
                    ("适配器能力声明", "Hook 支持和 transcript 支持必须分开声明。"),
                    ("适配器增长重建", "适配器必须分别通过增长测试与零丢失重建测试。"),
                ],
                1,
            )
        ]
        unrelated = [
            KnowledgeEntry(
                id=f"unrelated-{index:02d}",
                project_name="demo",
                module_path=["其他模块"],
                title=f"无关知识 {index}",
                statement=f"这是与候选无关的持久化约束 {index}。",
                verified_at=VERIFIED_AT,
            )
            for index in range(1, 13)
        ]
        async def list_entries(*args, **kwargs):
            del args, kwargs
            return [*unrelated, *relevant]

        monkeypatch.setattr(store, "list_entries", list_entries)

        handles, projection = _run(
            _current_truth_handles(
                backend,
                project_name="demo",
                project_root=str(tmp_path),
                candidates=[
                    KnowledgeCandidate(
                        id="candidate-adapter",
                        project_name="demo",
                        candidate_type="memory",
                        statement=(
                            "七个平台适配器需要真实路径、真实样本、能力分离声明，"
                            "并分别通过增长测试和零丢失重建测试。"
                        ),
                    )
                ],
            )
        )

        assert len(handles) == 12
        projected_ids = set(handles.values())
        assert {entry.id for entry in relevant} <= projected_ids
        assert [item["title"] for item in projection[:3]] == [
            "适配器增长重建",
            "适配器路径样本",
            "适配器能力声明",
        ]
    finally:
        _run(backend.close())
