"""Fictional immutable statements may write SQLite without a repository root."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, uuid5

import pytest
from harness_mem.config.merge import MergedConfig
import pytest_asyncio

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.evidence_admission import validate_candidate_evidence
from harness_mem.commands.knowledge_assimilation import (
    record_assimilation_result,
    resolve_candidate_source_context,
    resolve_separated_review,
)
from harness_mem.core.schemas import EvidenceRef, KnowledgeCandidate, KnowledgeEvidence
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


PROJECT = "fictional-statements"
STATEMENT = "Preserve each independently verifiable fact."


@pytest_asyncio.fixture
async def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    def forbid_profile(*args, **kwargs):
        raise AssertionError("source context must not create or resolve a profile")

    def forbid_config(*args, **kwargs):
        raise AssertionError("fictional capture must not read user configuration")

    monkeypatch.setattr(LocalProjectProfileStore, "__init__", forbid_profile)
    monkeypatch.setattr("harness_mem.adapters.snapshot.load_merged_config", forbid_config)
    value = LocalMemoryBackend(tmp_path / "data")
    await value.init()
    try:
        yield value
    finally:
        await value.close()


async def _point(backend, *, name="point", root="", native_role="user"):
    rendering = f"User: {STATEMENT}\n\nAssistant: Understood."
    native = "\n".join(json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        },
    }) for role, text in [(native_role, STATEMENT), ("assistant", "Understood.")]) + "\n"
    snapshot = await persist_session_snapshot(
        backend,
        Observation(
            session_id=name, client="codex", raw_content=rendering,
            content_type="transcript", timestamp=datetime.now(timezone.utc),
            metadata={"project_name": PROJECT},
        ),
        project_name=PROJECT, project_root=root, client="codex", session_id=name,
        source_kind="jsonl", source_uri=(backend.data_dir / f"{name}.jsonl").as_uri(),
        source_text=native, parser_version="codex-jsonl-v1", capture_config=MergedConfig(),
    )
    job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert job is not None and job.project_root == root
    candidate = KnowledgeCandidate(
        id=name, project_name=PROJECT, candidate_type="memory", statement=STATEMENT,
    )
    evidence = KnowledgeEvidence(
        project_name=PROJECT, candidate_id=candidate.id,
        distill_job_id=job.id, evidence_basis="user_statement",
        verification_outcome="verified",
        verification_refs=[EvidenceRef(
            kind="user_statement", exchange_index=1,
            content_sha256=render_distill_exchange_windows(rendering, [1])[0]["content_sha256"],
        )],
        verified_at=datetime.now(timezone.utc),
    )
    store = backend.structured_store.knowledge_store
    await store.save_candidate(candidate)
    await store.save_evidence(evidence)
    return candidate, evidence


async def _validate(backend, candidate, evidence, root=None):
    subject = SimpleNamespace(id=candidate.id, **{
        key: getattr(evidence, key) for key in (
            "project_name", "distill_job_id", "evidence_basis", "verification_outcome",
            "verification_refs", "verification_reason_codes", "verified_at",
        )
    })
    return await validate_candidate_evidence(backend, subject, project_root=root)


def _decision(disposition="add", targets=(), statement=STATEMENT):
    return {
        "disposition": disposition, "matched_truth_ids": list(targets),
        "reason": "Fictional verified user decision.",
        "knowledge_items": [{
            "title": "Evidence retention", "statement": statement,
            "topic_path": ["Preferences"], "claim_kind": "durable_preference",
        }],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("root_argument", [None, ""])
@pytest.mark.parametrize("supply_refs", [False, True])
async def test_rootless_add_confirm_replace_and_replay(backend, root_argument, supply_refs):
    store = backend.structured_store.knowledge_store

    async def apply(name, point):
        candidate, evidence = await _point(backend, name=name)
        assert (await _validate(backend, candidate, evidence)).verification_outcome == "verified"
        root, refs, verified_at = await resolve_candidate_source_context(
            backend, candidate=candidate, evidence_items=[evidence],
            project_root=root_argument,
        )
        assert root is None
        assert verified_at == evidence.verified_at
        assert refs[0].kind == "user_statement"
        job = backend.transcript_store.get_distill_job(evidence.distill_job_id)
        fragment = parse_qs(urlparse(refs[0].target).fragment)
        assert fragment == {
            "source_id": [job.source_id], "source_revision": [job.source_revision],
            "exchange": ["1"],
        }
        assert refs[0].digest == evidence.verification_refs[0].content_sha256
        kwargs = {"source_refs": refs} if supply_refs else {}
        ids = await record_assimilation_result(
            backend, candidate=candidate, point=point, project_root=root_argument, **kwargs,
        )
        return candidate, ids

    _, old_ids = await apply("add", _decision())
    original = await store.get_entry(old_ids[0], project_name=PROJECT)
    _, confirmed = await apply("confirm", _decision("confirm", old_ids))
    assert confirmed == old_ids
    assert await store.get_entry(old_ids[0], project_name=PROJECT) == original
    replacement = "Keep independently verifiable facts for fourteen days."
    point = _decision("replace", old_ids, replacement)
    candidate, new_ids = await apply("replace", point)
    assert new_ids != old_ids
    assert await store.get_entry(old_ids[0], project_name=PROJECT) is None
    assert await store.list_sources(old_ids[0]) == []
    assert [entry.id for entry in await search_current_knowledge(
        backend, project_name=PROJECT, query=replacement,
    )] == new_ids
    assert old_ids[0] not in {entry.id for entry in await search_current_knowledge(
        backend, project_name=PROJECT, query=STATEMENT,
    )}
    assert await record_assimilation_result(
        backend, candidate=candidate, point=point, project_root=root_argument,
    ) == new_ids
    assert len(await store.list_entries(PROJECT)) == 1
    assert not (backend.data_dir / "profiles").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("root_location", ["job", "argument", "absent"])
async def test_historical_absolute_root_need_not_exist(backend, tmp_path, root_location):
    historical = tmp_path / "retired-project"
    assert not historical.exists()
    candidate, evidence = await _point(
        backend, root=str(historical) if root_location == "job" else "",
    )
    argument = historical if root_location == "argument" else None
    root, _, _ = await resolve_candidate_source_context(
        backend, candidate=candidate, evidence_items=[evidence], project_root=argument,
    )
    assert root == (None if root_location == "absent" else historical)
    result = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="add", reason="Verified preference.",
        knowledge_items=_decision()["knowledge_items"], project_root=argument,
    )
    assert [entry.id for entry in await search_current_knowledge(
        backend, project_name=PROJECT, query=STATEMENT,
    )] == result["canonical_truth_ids"]
    assert not historical.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unverified", "transcript", "author", "digest", "revision"])
async def test_rootless_review_preserves_evidence_gates(backend, failure):
    candidate, evidence = await _point(
        backend, native_role="assistant" if failure == "author" else "user",
    )
    if failure == "unverified":
        evidence.verification_outcome = "unverified"
    elif failure == "transcript":
        evidence.evidence_basis = "transcript"
        job = backend.transcript_store.get_distill_job(evidence.distill_job_id)
        chunk = backend.transcript_store.list_chunks(job.source_id, source_revision=job.source_revision)[0]
        evidence.verification_refs = [EvidenceRef(
            kind="transcript", chunk_index=chunk.chunk_index, content_sha256=chunk.content_sha256,
        )]
    elif failure == "digest":
        evidence.verification_refs[0].content_sha256 = "0" * 64
    elif failure == "revision":
        job = backend.transcript_store.get_distill_job(evidence.distill_job_id)
        observation = await backend.verbatim_store.get(
            str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation")),
        )
        observation.metadata["source_revision"] = "sha256:changed"
        await backend.verbatim_store.save(observation)
    store = backend.structured_store.knowledge_store
    await store.save_evidence(evidence)
    assert (await _validate(backend, candidate, evidence)).verification_outcome != "verified"
    with pytest.raises(ValueError, match="verified evidence|retained transcript revision"):
        await resolve_separated_review(
            backend, candidate_id=candidate.id, disposition="add", reason="Must fail closed.",
            knowledge_items=_decision()["knowledge_items"],
        )
    assert await store.list_entries(PROJECT) == []
    assert (await store.get_candidate(candidate.id)).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_root", "missing_directory", "relative_root", "changed_file", "outside_root"])
async def test_repository_writes_still_require_current_attributable_files(backend, tmp_path, failure):
    candidate, evidence = await _point(backend)
    repository = tmp_path / "repository"
    repository.mkdir()
    source = repository / "policy.txt"
    source.write_text(STATEMENT, encoding="utf-8")
    evidence.evidence_basis = "repository"
    evidence.verification_refs = [EvidenceRef(
        kind="repository", locator="policy.txt",
        content_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )]
    root = repository
    if failure == "missing_root":
        root = None
    elif failure == "missing_directory":
        root = tmp_path / "nonexistent"
    elif failure == "relative_root":
        root = "repository"
    elif failure == "changed_file":
        source.write_text("The policy has changed.", encoding="utf-8")
    elif failure == "outside_root":
        evidence.verification_refs[0] = EvidenceRef(
            kind="repository", locator="../repository/policy.txt",
            content_sha256=evidence.verification_refs[0].content_sha256,
        )
        root = tmp_path / "other"
        root.mkdir()
    store = backend.structured_store.knowledge_store
    await store.save_evidence(evidence)
    with pytest.raises(ValueError, match="project root|verified evidence"):
        await resolve_separated_review(
            backend, candidate_id=candidate.id, disposition="add", reason="Repository gate.",
            knowledge_items=_decision()["knowledge_items"], project_root=root,
        )
    assert await store.list_entries(PROJECT) == []
    assert (await store.get_candidate(candidate.id)).status == "pending"


@pytest.mark.asyncio
async def test_rootless_commit_cannot_skip_ordinary_search_readback(backend, monkeypatch):
    candidate, evidence = await _point(backend)
    assert (await _validate(backend, candidate, evidence)).verification_outcome == "verified"

    async def empty_search(*args, **kwargs):
        assert kwargs["project_root"] is None
        return []

    monkeypatch.setattr("harness_mem.read_knowledge.search_current_knowledge", empty_search)
    with pytest.raises(RuntimeError, match="not readable through normal search"):
        await record_assimilation_result(backend, candidate=candidate, point=_decision())
    store = backend.structured_store.knowledge_store
    assert (await store.get_candidate(candidate.id)).status == "pending"
    assert len(await store.list_entries(PROJECT)) == 1  # Commit precedes readback.
    with pytest.raises(RuntimeError, match="not readable through normal search"):
        await record_assimilation_result(backend, candidate=candidate, point=_decision())
    assert (await store.get_candidate(candidate.id)).status == "pending"
    assert len(await store.list_entries(PROJECT)) == 1


@pytest.mark.asyncio
async def test_rootless_review_can_confirm_and_correct_exact_search_text(backend):
    candidate, _ = await _point(backend, name="review-add")
    saved = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="add", reason="Verified future preference.",
        knowledge_items=_decision()["knowledge_items"],
    )
    old_id, = saved["canonical_truth_ids"]
    old = await backend.structured_store.knowledge_store.get_entry(old_id, project_name=PROJECT)
    target = {"title": old.title, "statement": old.statement, "module": old.module_path, "project_name": PROJECT}
    candidate, _ = await _point(backend, name="review-confirm")
    confirmation = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="confirm", reason="Unchanged explicit preference.",
        target_knowledge=[target],
    )
    assert confirmation["canonical_truth_ids"] == [old_id]
    candidate, _ = await _point(backend, name="review-correct")
    replacement = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="replace", reason="Verified correction.",
        target_knowledge=[target], knowledge_items=_decision(statement="Keep facts for fourteen days.")["knowledge_items"],
    )
    assert replacement["canonical_truth_ids"] != [old_id]
    assert await backend.structured_store.knowledge_store.get_entry(old_id, project_name=PROJECT) is None
