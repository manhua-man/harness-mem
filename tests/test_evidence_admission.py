from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.auto_review import (
    auto_review_candidates,
    decide_memory_entry,
    decide_relation_fact,
    decide_rule_candidate,
)
from harness_mem.core.schemas import EvidenceRef, MemoryEntry, RelationFact, RuleCandidate
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


async def _snapshot(
    backend: LocalMemoryBackend,
    project: Path,
    *,
    session_id: str,
    rendering: str,
):
    result = await persist_session_snapshot(
        backend,
        Observation(
            session_id=session_id,
            client="codex",
            raw_content=rendering,
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": "demo"},
        ),
        project_name="demo",
        project_root=str(project),
        client="codex",
        session_id=session_id,
        source_kind="jsonl",
        source_uri=f"file:///{session_id}.jsonl",
        source_text=rendering,
    )
    assert result.observation_id is not None
    assert result.distill_job_id is not None
    return result


@pytest.fixture
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalMemoryBackend:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    value = LocalMemoryBackend(tmp_path / "data")
    _run(value.init())
    yield value
    _run(value.close())


def _repo_ref(path: Path, relative: str) -> EvidenceRef:
    return EvidenceRef(
        kind="repository",
        locator=relative,
        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _repo_memory(snapshot, ref: EvidenceRef, *, content: str) -> MemoryEntry:
    return MemoryEntry(
        project_name="demo",
        category="decision",
        content=content,
        source=str(snapshot.observation_id),
        distill_job_id=snapshot.distill_job_id,
        confidence=0.9,
        evidence_basis="repository",
        verification_outcome="verified",
        verification_refs=[ref],
    )


def test_legacy_candidate_roundtrip_does_not_reclassify() -> None:
    original = MemoryEntry(
        project_name="demo",
        category="decision",
        content="Legacy candidate remains governed by the legacy review contract.",
        source="observation:legacy",
    )
    payload = original.to_dict()
    for key in (
        "evidence_basis",
        "verification_outcome",
        "verification_reason_codes",
        "verification_refs",
        "verified_at",
    ):
        payload.pop(key)

    restored = MemoryEntry.from_dict(payload)

    assert restored.evidence_basis is None
    assert restored.verification_outcome is None
    assert restored.verification_refs == []


def test_new_public_suggestion_cannot_claim_legacy_bypass(
    backend: LocalMemoryBackend,
) -> None:
    previous_backend_provider = tool_handlers._backend_provider
    previous_observer_provider = tool_handlers._observer_data_dir_provider
    previous_cost_provider = tool_handlers._cost_surface_budgets_provider
    previous_logger = tool_handlers.logger
    try:
        tool_handlers.configure_tool_handler_dependencies(
            backend_provider=lambda: backend,
            observer_data_dir=lambda: backend.data_dir,
            cost_surface_budgets=lambda _project_name: None,
            logger_instance=logging.getLogger("test.evidence-admission"),
        )
        suggested = tool_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="A new public suggestion must enter the evidence admission contract.",
            source="manual-agent-suggestion",
            confidence=0.99,
        )
        stored = _run(
            backend.structured_store.get_memory_entry(suggested["entry_id"])
        )
    finally:
        tool_handlers.configure_tool_handler_dependencies(
            backend_provider=previous_backend_provider,
            observer_data_dir=previous_observer_provider,
            cost_surface_budgets=previous_cost_provider,
            logger_instance=previous_logger,
        )

    assert stored is not None
    assert stored.evidence_basis == "transcript"
    assert stored.verification_outcome == "unverified"
    assert stored.verification_reason_codes == ["evidence_envelope_missing"]


def test_repository_evidence_promotes_only_while_digest_is_current(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "pyproject.toml"
    contract.write_text('[project]\nname = "demo"\n', encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="repo-current",
            rendering="User: Verify the repository contract.\n\nAssistant: Verified.",
        )
    )
    candidate = _repo_memory(
        snapshot,
        _repo_ref(contract, "pyproject.toml"),
        content="The canonical project metadata is stored in pyproject.toml.",
    )
    _run(backend.structured_store.save_memory_entry(candidate))

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    stored = _run(backend.structured_store.get_memory_entry(candidate.id))

    assert summary.repository_verified == 1
    assert summary.auto_confirmed == 1
    assert stored is not None
    assert stored.status == "auto_confirmed"
    assert stored.verification_outcome == "verified"
    assert stored.verification_reason_codes == ["repository_refs_current"]


def test_repository_change_rejects_candidate_and_proposes_matching_truth_history(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "contract.txt"
    contract.write_text("storage=v2\n", encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="repo-changed",
            rendering="User: Record storage v2.\n\nAssistant: Recorded.",
        )
    )
    content = "The repository storage contract uses the canonical v2 layout."
    current_truth = MemoryEntry(
        project_name="demo",
        category="decision",
        content=content,
        source="observation:current",
        status="auto_confirmed",
    )
    candidate = _repo_memory(
        snapshot,
        _repo_ref(contract, "contract.txt"),
        content=content,
    )
    _run(backend.structured_store.save_memory_entry(current_truth))
    _run(backend.structured_store.save_memory_entry(candidate))
    contract.write_text("storage=v3\n", encoding="utf-8")

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    stored = _run(backend.structured_store.get_memory_entry(candidate.id))
    stale = _run(
        backend.structured_store.list_stale_truth_suggestion_candidates(
            "demo", status="pending"
        )
    )

    assert summary.contradicted == 1
    assert stored is not None and stored.status == "rejected"
    assert stored.verification_reason_codes == ["repository_digest_changed"]
    assert [(item.target_kind, item.target_id) for item in stale] == [
        ("memory_entry", current_truth.id)
    ]
    assert stale[0].source_candidate_id == candidate.id


def test_contradiction_proposal_failure_leaves_candidate_retryable(
    backend: LocalMemoryBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "contract.txt"
    contract.write_text("version=1\n", encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="proposal-failure",
            rendering="User: Record version one.\n\nAssistant: Recorded.",
        )
    )
    content = "The current repository contract records version one as active."
    current_truth = MemoryEntry(
        project_name="demo",
        category="decision",
        content=content,
        source="observation:current",
        status="auto_confirmed",
    )
    candidate = _repo_memory(
        snapshot,
        _repo_ref(contract, "contract.txt"),
        content=content,
    )
    _run(backend.structured_store.save_memory_entry(current_truth))
    _run(backend.structured_store.save_memory_entry(candidate))
    contract.write_text("version=2\n", encoding="utf-8")

    async def fail_proposal(_candidate) -> str:
        raise RuntimeError("injected proposal persistence failure")

    monkeypatch.setattr(
        backend.structured_store,
        "save_stale_truth_suggestion_candidate",
        fail_proposal,
    )
    with pytest.raises(RuntimeError, match="injected proposal"):
        _run(auto_review_candidates(backend, "demo", apply=True))

    stored = _run(backend.structured_store.get_memory_entry(candidate.id))
    assert stored is not None
    assert stored.status == "pending"
    assert stored.verification_outcome == "contradicted"


def test_repository_path_escape_is_blocked(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="repo-escape",
            rendering="User: Verify an unsafe path.\n\nAssistant: Refused.",
        )
    )
    candidate = _repo_memory(
        snapshot,
        _repo_ref(outside, "../outside.txt"),
        content="An outside-project file must never verify repository evidence.",
    )
    _run(backend.structured_store.save_memory_entry(candidate))

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    stored = _run(backend.structured_store.get_memory_entry(candidate.id))

    assert summary.unverified_blocked == 1
    assert stored is not None and stored.status == "rejected"
    assert stored.verification_reason_codes == ["repository_ref_outside_project"]


def test_repository_locator_digest_cannot_be_forged(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "contract.txt"
    contract.write_text("current contract", encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="repo-locator-digest",
            rendering="User: Verify locator integrity.\n\nAssistant: Verified.",
        )
    )
    ref = _repo_ref(contract, "contract.txt")
    ref.locator_sha256 = "0" * 64
    candidate = _repo_memory(
        snapshot,
        ref,
        content="Repository locator digests must agree with the transient path.",
    )
    _run(backend.structured_store.save_memory_entry(candidate))

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    stored = _run(backend.structured_store.get_memory_entry(candidate.id))

    assert summary.unverified_blocked == 1
    assert stored is not None and stored.status == "rejected"
    assert stored.verification_reason_codes == [
        "repository_locator_digest_mismatch"
    ]


def test_explicit_user_statement_can_promote_but_transcript_only_cannot(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    rendering = (
        "User: Prefer SQLite for local derived indexes.\n\n"
        "Assistant: I will preserve that project decision."
    )
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="user-statement",
            rendering=rendering,
        )
    )
    window = render_distill_exchange_windows(rendering, [1])[0]
    user_candidate = MemoryEntry(
        project_name="demo",
        category="decision",
        content="The user prefers SQLite for local derived indexes in this project.",
        source=str(snapshot.observation_id),
        distill_job_id=snapshot.distill_job_id,
        confidence=0.9,
        evidence_basis="user_statement",
        verification_outcome="verified",
        verification_refs=[
            EvidenceRef(
                kind="user_statement",
                exchange_index=1,
                role="user",
                content_sha256=window["content_sha256"],
            )
        ],
    )
    chunk = backend.transcript_store.list_chunks(
        snapshot.source.id,
        source_revision=snapshot.source.source_revision,
    )[0]
    transcript_candidate = MemoryEntry(
        project_name="demo",
        category="decision",
        content="A raw transcript alone cannot establish a durable repository fact.",
        source=str(snapshot.observation_id),
        distill_job_id=snapshot.distill_job_id,
        confidence=0.9,
        evidence_basis="transcript",
        verification_outcome="verified",
        verification_refs=[
            EvidenceRef(
                kind="transcript",
                chunk_index=chunk.chunk_index,
                content_sha256=chunk.content_sha256,
            )
        ],
    )
    _run(backend.structured_store.save_memory_entry(user_candidate))
    _run(backend.structured_store.save_memory_entry(transcript_candidate))

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    user_stored = _run(backend.structured_store.get_memory_entry(user_candidate.id))
    transcript_stored = _run(
        backend.structured_store.get_memory_entry(transcript_candidate.id)
    )

    assert summary.user_stated == 1
    assert summary.unverified_blocked == 1
    assert user_stored is not None and user_stored.status == "auto_confirmed"
    assert transcript_stored is not None and transcript_stored.status == "rejected"
    assert "transcript_cannot_verify_durable_truth" in (
        transcript_stored.verification_reason_codes
    )


def test_verified_relation_uses_same_admission_contract(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "architecture.txt"
    contract.write_text("api depends_on storage\n", encoding="utf-8")
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="relation",
            rendering="User: Verify dependency.\n\nAssistant: Verified.",
        )
    )
    relation = RelationFact(
        project_name="demo",
        source_entity="api",
        target_entity="storage",
        relation_type="depends_on",
        evidence="The repository architecture contract declares this dependency.",
        source=str(snapshot.observation_id),
        distill_job_id=snapshot.distill_job_id,
        confidence=0.9,
        evidence_basis="repository",
        verification_outcome="verified",
        verification_refs=[_repo_ref(contract, "architecture.txt")],
    )
    _run(backend.structured_store.save_relation_fact(relation))

    summary = _run(auto_review_candidates(backend, "demo", apply=True))
    stored = _run(backend.structured_store.get_relation_fact(relation.id))

    assert summary.repository_verified == 1
    assert summary.auto_provisional == 1
    assert stored is not None and stored.status == "provisional"


def test_evidence_admission_golden_policy_matrix() -> None:
    path = Path(__file__).parent / "benchmarks" / "evidence_admission_golden.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = list(payload["cases"])
    assert len(cases) == int(payload["declared_case_count"])

    for case in cases:
        common = {
            "project_name": "golden",
            "confidence": case["confidence"],
            "evidence_basis": case["basis"],
            "verification_outcome": case["outcome"],
            "verification_refs": [
                EvidenceRef(kind=case["basis"], content_sha256="a" * 64)
            ],
        }
        if case["kind"] == "memory_entry":
            candidate = MemoryEntry(
                **common,
                category="decision",
                content="Golden evidence admission decision with sufficient stable detail.",
                source="distill-job:golden",
                distill_job_id="golden",
            )
            decision = decide_memory_entry(candidate)
        elif case["kind"] == "rule_candidate":
            candidate = RuleCandidate(
                **common,
                pattern="Use the verified repository contract for all durable claims.",
                trigger="When Dream evaluates a distill candidate",
                examples=["distill-job:golden"],
                session_id="golden-session",
                distill_job_id="golden",
            )
            decision = decide_rule_candidate(candidate)
        else:
            candidate = RelationFact(
                **common,
                source_entity="api",
                target_entity="storage",
                relation_type="depends_on",
                evidence="Verified repository contract with sufficient detail.",
                source="distill-job:golden",
                distill_job_id="golden",
            )
            decision = decide_relation_fact(candidate)
        assert decision.action == case["expected_action"], case["id"]
