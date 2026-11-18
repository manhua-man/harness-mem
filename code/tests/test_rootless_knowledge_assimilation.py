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
from harness_mem.commands.separated_assimilation import target_version
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


async def _point(backend, *, name="point", root="", native_role="user", statement=STATEMENT):
    rendering = f"User: {statement}\n\nAssistant: Understood."
    native = "\n".join(json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        },
    }) for role, text in [(native_role, statement), ("assistant", "Understood.")]) + "\n"
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
        id=name, project_name=PROJECT, candidate_type="memory", statement=statement,
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
        "knowledge_items": [] if disposition == "confirm" else [{
            "title": "Evidence retention", "statement": statement,
            "topic_path": ["Preferences"], "claim_kind": "durable_preference",
        }],
    }


def _judgment(item, *, predecessors=()):
    statement = item["statement"]
    verdict = {
        "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
        "source_use": "standing_decision", "reason": "The immutable user statement establishes the whole preference.",
        "scope_segments": [{
            "text": f"{item['title']}\n{statement}", "source_use": "standing_decision",
            "future_scope": "durable", "standalone": True, "content_role": "claim",
            "source_support": "supported",
        }],
    }
    if predecessors:
        verdict["update_meaning_judgment"] = {
            "relationship": "preserves_applicable_meaning",
            "predecessor_conditions": [],
            "predecessor_statements": [entry.statement for entry in predecessors],
            "predecessor_versions": [target_version({
                "title": entry.title, "statement": entry.statement,
                "topic_path": entry.module_path, "source_report": None,
            }) for entry in predecessors],
            "successor_statements": [statement],
            "undecided_state": None,
            "basis": "The correction retains independent verification and sets a retention period.",
        }
    return {"points": [verdict]}


@pytest.mark.asyncio
@pytest.mark.parametrize("root_argument", [None, ""])
@pytest.mark.parametrize("supply_refs", [False, True])
async def test_rootless_add_confirm_replace_and_replay(backend, root_argument, supply_refs):
    store = backend.structured_store.knowledge_store

    async def apply(name, point):
        knowledge, = point["knowledge_items"] or _decision()["knowledge_items"]
        candidate, evidence = await _point(backend, name=name, statement=knowledge["statement"])
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
        predecessors = [await store.get_entry(identity, project_name=PROJECT)
                        for identity in point["matched_truth_ids"]] if name == "replace" else []
        point["final_scope_judgment"] = _judgment(knowledge, predecessors=predecessors)
        if predecessors:
            point["update_meaning_judgment"] = (
                point["final_scope_judgment"]["points"][0]["update_meaning_judgment"]
            )
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
        final_scope_judgment=_judgment(_decision()["knowledge_items"][0]),
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
    with pytest.raises(ValueError, match="project root|verified evidence|repository evidence unavailable"):
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
    point = _decision()
    point["final_scope_judgment"] = _judgment(point["knowledge_items"][0])
    with pytest.raises(RuntimeError, match="not readable through normal search"):
        await record_assimilation_result(backend, candidate=candidate, point=point)
    store = backend.structured_store.knowledge_store
    assert (await store.get_candidate(candidate.id)).status == "pending"
    assert len(await store.list_entries(PROJECT)) == 1  # Commit precedes readback.
    with pytest.raises(RuntimeError, match="not readable through normal search"):
        await record_assimilation_result(backend, candidate=candidate, point=point)
    assert (await store.get_candidate(candidate.id)).status == "pending"
    assert len(await store.list_entries(PROJECT)) == 1


@pytest.mark.asyncio
async def test_rootless_review_can_confirm_and_correct_exact_search_text(backend):
    candidate, _ = await _point(backend, name="review-add")
    saved = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="add", reason="Verified future preference.",
        knowledge_items=_decision()["knowledge_items"],
        final_scope_judgment=_judgment(_decision()["knowledge_items"][0]),
    )
    old_id, = saved["canonical_truth_ids"]
    old = await backend.structured_store.knowledge_store.get_entry(old_id, project_name=PROJECT)
    target = {"title": old.title, "statement": old.statement, "module": old.module_path, "project_name": PROJECT}
    candidate, _ = await _point(backend, name="review-confirm")
    confirmation = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="confirm", reason="Unchanged explicit preference.",
        target_knowledge=[target],
        final_scope_judgment=_judgment(_decision()["knowledge_items"][0]),
    )
    assert confirmation["canonical_truth_ids"] == [old_id]
    text = "Keep independently verifiable facts for fourteen days."
    candidate, _ = await _point(backend, name="review-correct", statement=text)
    knowledge = _decision(statement=text)["knowledge_items"]
    replacement = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="replace", reason="Verified correction.",
        target_knowledge=[target], knowledge_items=knowledge,
        final_scope_judgment=_judgment(knowledge[0], predecessors=[old]),
    )
    assert replacement["canonical_truth_ids"] != [old_id]
    assert await backend.structured_store.knowledge_store.get_entry(old_id, project_name=PROJECT) is None
