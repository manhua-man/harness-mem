"""Historical candidate evidence uses immutable bytes, without projection writes."""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from test_dream_complete_user_context import captured as _captured_fixture
from harness_mem.commands import evidence_admission as admission
from harness_mem.core.schemas import EvidenceRef, MemoryEntry
from harness_mem.mcp.distill_projection import render_distill_exchange_windows

captured = _captured_fixture


def run(value):
    return asyncio.run(value)


def candidate_and_job(captured, monkeypatch):
    backend, _project, snapshot, rendering, _sources = captured
    job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    completed = job.model_copy(update={"status": "completed"})
    monkeypatch.setattr(backend.transcript_store, "get_distill_job", lambda _identity: completed)
    digest = render_distill_exchange_windows(rendering, [47])[0]["content_sha256"]
    candidate = MemoryEntry(
        project_name="demo", category="decision", content="Preserve the original scoped correction.",
        source=snapshot.observation_id, distill_job_id=job.id, confidence=0.9,
        evidence_basis="user_statement", verification_outcome="verified",
        verification_refs=[EvidenceRef(kind="user_statement", exchange_index=47,
                                      content_sha256=digest)],
    )
    return backend, snapshot, candidate, completed


@pytest.mark.parametrize("projection", ("missing", "newer"))
def test_complete_historical_candidate_reopens_without_writing_shared_projection(captured, monkeypatch, projection):
    backend, snapshot, candidate, _job = candidate_and_job(captured, monkeypatch)
    if projection == "missing":
        run(backend.verbatim_store.delete(snapshot.observation_id))
    else:
        observation = run(backend.verbatim_store.get(snapshot.observation_id))
        observation.metadata["source_revision"] = "sha256:" + "1" * 64
        observation.raw_content = "User: A later source must stay untouched."
        run(backend.verbatim_store.save(observation))
    before = run(backend.verbatim_store.get(snapshot.observation_id))
    validated = run(admission.validate_candidate_evidence(backend, candidate))
    after = run(backend.verbatim_store.get(snapshot.observation_id))
    assert validated.verification_outcome == "verified", validated.reason_codes
    assert validated.reason_codes == ("user_statement_refs_current",)
    assert (before.model_dump() if before else None) == (after.model_dump() if after else None)


@pytest.mark.parametrize("change", ("raw", "chunks", "session", "project", "root", "role", "digest", "not_completed"))
def test_historical_projection_cannot_waive_original_source_or_reference_checks(captured, monkeypatch, change):
    backend, snapshot, candidate, job = candidate_and_job(captured, monkeypatch)
    run(backend.verbatim_store.delete(snapshot.observation_id))
    if change == "raw":
        original = backend.transcript_store.reconstruct_raw
        monkeypatch.setattr(backend.transcript_store, "reconstruct_raw", lambda *a, **k: original(*a, **k) + b"changed")
    elif change == "chunks":
        monkeypatch.setattr(backend.transcript_store, "list_chunks", lambda *a, **k: [])
    elif change in {"session", "project", "root", "not_completed"}:
        fields = {"session_id": "other"} if change == "session" else {"project_name": "other"} if change == "project" else {"project_root": "other"} if change == "root" else {"status": "reviewing"}
        monkeypatch.setattr(backend.transcript_store, "get_distill_job", lambda _identity: job.model_copy(update=fields))
    elif change == "role":
        candidate.verification_refs[0].role = "assistant"
    else:
        candidate.verification_refs[0].content_sha256 = hashlib.sha256(b"wrong").hexdigest()
    assert run(admission.validate_candidate_evidence(backend, candidate)).verification_outcome != "verified"
    assert run(backend.verbatim_store.get(snapshot.observation_id)) is None


@pytest.mark.parametrize("captured", ("unproved_plaintext", "wrong_native_session", "wrong_native_project", "assistant_spoof"), indirect=True)
def test_historical_projection_requires_strict_native_authorship(captured, monkeypatch):
    backend, snapshot, candidate, _job = candidate_and_job(captured, monkeypatch)
    run(backend.verbatim_store.delete(snapshot.observation_id))
    assert run(admission.validate_candidate_evidence(backend, candidate)).verification_outcome != "verified"


def test_retained_user_capture_does_not_require_assistant_report_authority(captured, monkeypatch):
    from harness_mem.adapters.snapshot import persist_session_snapshot
    from harness_mem.config.merge import MergedConfig
    from harness_mem.core.schemas.observation import Observation

    backend, project, original, rendering, sources = captured
    native = backend.transcript_store.reconstruct_raw(
        original.source.id, source_revision=original.source.source_revision,
    )
    snapshot = run(persist_session_snapshot(
        backend, Observation(session_id=original.source.session_id, client="codex",
                             raw_content=rendering, content_type="transcript"),
        project_name="demo", project_root=str(project), client="codex",
        session_id=original.source.session_id, source_kind="jsonl",
        source_uri=(project / "retained-user.jsonl").as_uri(), source_text=rendering,
        raw_bytes=rendering.encode(), native_input_bytes=native,
        parser_version="codex-conversation-v3", capture_config=MergedConfig(),
    ))
    original_get_revision = backend.transcript_store.get_revision

    def retained_revision(*args, **kwargs):
        revision = original_get_revision(*args, **kwargs)
        metadata = {**revision.metadata, "authored_assistant_text_sha256": None,
                    "authored_source_report_native_sha256": None}
        return revision.model_copy(update={"metadata": metadata})

    monkeypatch.setattr(backend.transcript_store, "get_revision", retained_revision)
    backend, snapshot, candidate, _job = candidate_and_job(
        (backend, project, snapshot, rendering, sources), monkeypatch,
    )
    run(backend.verbatim_store.delete(snapshot.observation_id))
    assert run(admission.validate_candidate_evidence(backend, candidate)).verification_outcome == "verified"
    assert run(backend.verbatim_store.get(snapshot.observation_id)) is None
