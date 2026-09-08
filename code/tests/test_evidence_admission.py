from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands import evidence_admission
from harness_mem.commands.evidence_admission import answer_gate_status
from harness_mem.core.schemas import (
    EvidenceRef,
    KnowledgeSource,
    MemoryEntry,
    RelationFact,
    RuleCandidate,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.mcp import governance_handlers, tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


async def _snapshot(
    backend: LocalMemoryBackend,
    project: Path,
    *,
    session_id: str,
    rendering: str,
    parser_version: str = "transcript-v1",
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
        parser_version=parser_version,
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


def _transcript_locator(backend, source_id: str, revision: str, **fragment) -> str:
    query = urlencode(
        {"source_id": source_id, "source_revision": revision, **fragment}
    )
    return f"{Path(backend.transcript_store.db_path).resolve().as_uri()}#{query}"


def test_user_statement_knowledge_source_current_missing_and_changed(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    rendering = "User: Preserve original evidence.\n\nAssistant: Understood."
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="knowledge-user-source",
            rendering=rendering,
            parser_version="codex-conversation-v2",
        )
    )
    source = snapshot.source
    assert source is not None
    digest = render_distill_exchange_windows(rendering, [1])[0]["content_sha256"]
    current = KnowledgeSource(
        knowledge_id="knowledge-1",
        project_name="demo",
        source_kind="user_statement",
        locator=_transcript_locator(
            backend,
            source.id,
            source.source_revision,
            exchange=1,
        ),
        content_sha256=digest,
        verified_at=datetime.now(timezone.utc),
    )

    assert _run(
        evidence_admission._validate_knowledge_source(
            backend, current, project_root=project
        )
    ) == ("verified", "knowledge_source_current")
    assert snapshot.observation_id is not None
    assert _run(backend.verbatim_store.delete(snapshot.observation_id)) is True
    assert _run(backend.verbatim_store.get(snapshot.observation_id)) is None
    assert _run(
        evidence_admission._validate_knowledge_source(
            backend, current, project_root=project
        )
    ) == ("verified", "knowledge_source_current")
    assert _run(
        evidence_admission._validate_knowledge_source(
            backend,
            current.model_copy(
                update={
                    "locator": _transcript_locator(
                        backend, source.id, "sha256:missing", exchange=1
                    )
                }
            ),
            project_root=project,
        )
    ) == ("unverified", "knowledge_source_revision_missing")
    assert _run(
        evidence_admission._validate_knowledge_source(
            backend,
            current.model_copy(update={"content_sha256": "0" * 64}),
            project_root=project,
        )
    ) == ("contradicted", "knowledge_source_digest_changed")


def test_transcript_chunk_knowledge_source_current_missing_and_changed(
    backend: LocalMemoryBackend,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id="knowledge-transcript-source",
            rendering="User: Verify the complete transcript.\n\nAssistant: Verified.",
        )
    )
    source = snapshot.source
    assert source is not None
    chunk = backend.transcript_store.list_chunks(
        source.id, source_revision=source.source_revision
    )[0]
    current = KnowledgeSource(
        knowledge_id="knowledge-1",
        project_name="demo",
        source_kind="transcript",
        locator=_transcript_locator(
            backend,
            source.id,
            source.source_revision,
            chunk=chunk.chunk_index,
        ),
        content_sha256=chunk.content_sha256,
        verified_at=datetime.now(timezone.utc),
    )

    assert _run(
        evidence_admission._validate_knowledge_source(
            backend, current, project_root=project
        )
    ) == ("verified", "knowledge_source_current")
    assert _run(
        evidence_admission._validate_knowledge_source(
            backend,
            current.model_copy(
                update={
                    "locator": _transcript_locator(
                        backend,
                        source.id,
                        source.source_revision,
                        chunk=999,
                    )
                }
            ),
            project_root=project,
        )
    ) == ("unverified", "knowledge_source_chunk_missing")
    assert _run(
        evidence_admission._validate_knowledge_source(
            backend,
            current.model_copy(update={"content_sha256": "0" * 64}),
            project_root=project,
        )
    ) == ("contradicted", "knowledge_source_digest_changed")


@pytest.mark.parametrize(
    ("source_kind", "locator", "expected_reason"),
    [
        ("repository", "https://example.invalid/source", "knowledge_source_scheme_unsupported"),
        ("transcript", None, "knowledge_source_transcript_store_mismatch"),
        ("transcript", "current", "knowledge_source_locator_incomplete"),
        ("unknown", "valid", "knowledge_source_kind_unsupported"),
    ],
)
def test_knowledge_source_malformed_locators_fail_closed(
    backend: LocalMemoryBackend,
    tmp_path: Path,
    source_kind: str,
    locator: str | None,
    expected_reason: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    snapshot = _run(
        _snapshot(
            backend,
            project,
            session_id=f"malformed-{source_kind}-{expected_reason}",
            rendering="User: Validate source.\n\nAssistant: Validated.",
        )
    )
    source = snapshot.source
    assert source is not None
    if locator is None:
        locator = (tmp_path / "wrong.sqlite").resolve().as_uri()
    elif locator == "current":
        locator = Path(backend.transcript_store.db_path).resolve().as_uri()
    elif locator == "valid":
        locator = _transcript_locator(
            backend, source.id, source.source_revision, chunk=0
        )
    knowledge_source = KnowledgeSource(
        knowledge_id="knowledge-1",
        project_name="demo",
        source_kind=source_kind,
        locator=locator,
        content_sha256="0" * 64,
        verified_at=datetime.now(timezone.utc),
    )

    status, reason = _run(
        evidence_admission._validate_knowledge_source(
            backend, knowledge_source, project_root=project
        )
    )
    assert status == "unverified"
    assert reason == expected_reason


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
        suggested = governance_handlers.tool_suggest_memory_entry(
            project_name="demo",
            category="decision",
            content="A new public suggestion must enter the evidence admission contract.",
            source="manual-agent-suggestion",
            confidence=0.99,
        )
        stored = _run(
            backend.structured_store.knowledge_store.get_candidate(
                suggested["entry_id"]
            )
        )
        evidence = _run(
            backend.structured_store.knowledge_store.list_evidence(
                suggested["entry_id"]
            )
        )
        compatibility = _run(
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
    assert compatibility is None
    assert len(evidence) == 1
    assert evidence[0].evidence_basis == "transcript"
    assert evidence[0].verification_outcome == "unverified"
    assert "evidence_envelope_missing" in evidence[0].verification_reason_codes

@pytest.mark.parametrize(
    ("basis", "outcome", "reason_codes", "with_ref", "expected"),
    [
        ("repository", "verified", ["repository_refs_current"], True, "ANSWERED"),
        ("user_statement", "verified", ["user_statement_refs_current"], True, "ANSWERED"),
        ("user_statement", "not_applicable", [], False, "NOT_APPLICABLE"),
        ("repository", "unverified", ["repository_ref_incomplete"], True, "PARTIAL"),
        ("repository", "unverified", ["evidence_envelope_missing"], False, "UNANSWERED"),
        ("repository", "contradicted", ["claim_conflicts"], True, "CONTRADICTED"),
        ("repository", "contradicted", ["repository_digest_changed"], True, "STALE"),
        ("repository", "not_applicable", [], False, "NOT_APPLICABLE"),
    ],
)
def test_answer_gate_status_is_runtime_derived(
    basis: str,
    outcome: str,
    reason_codes: list[str],
    with_ref: bool,
    expected: str,
) -> None:
    candidate = MemoryEntry(
        project_name="demo",
        category="decision",
        content="A candidate with an explicitly classified verification question.",
        source="distill-job:test",
        distill_job_id="test",
        evidence_basis=basis,
        verification_outcome=outcome,
        verification_reason_codes=reason_codes,
        verification_refs=(
            [EvidenceRef(kind=basis, content_sha256="a" * 64)] if with_ref else []
        ),
    )

    assert answer_gate_status(candidate) == expected
