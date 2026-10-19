"""Independent synthetic regressions for the rejected source-report candidate.

Manual caller semantic judgments remain caller-owned. These tests check replay
authority, report projections, retrieval identity and temporal labels, not a
keyword/substring substitute for semantic verification or a model's behavior.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.autonomous.models import AssimilationDecision, DistillCandidate
from harness_mem.autonomous.worker import _build_candidate_verification_manifest
from harness_mem.commands.evidence_admission import source_report_speaker_excerpt
from harness_mem.commands.knowledge_assimilation import resolve_separated_review
from harness_mem.commands.separated_assimilation import (
    admit_separated_candidate,
    apply_separated_assimilation,
    prepare_separated_assimilation,
    validate_separated_assimilation_decision,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.knowledge import KnowledgeEntry
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp import governance_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.read_knowledge import _deduplicate_current, search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

PROJECT = "source-report-regression"
CLAIM = "The user approved the production rollout."
USER = "Inspect the diagnostic only. I do not approve a production rollout."


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        "harness_mem.adapters.snapshot.load_merged_config",
        lambda *_args, **_kwargs: MergedConfig(),
    )
    root = tmp_path / "project"
    root.mkdir()
    return root, tmp_path / "data"


@contextmanager
def open_backend(data):
    backend = LocalMemoryBackend(data)
    run(backend.init())
    try:
        yield backend
    finally:
        run(backend.close())


async def capture(backend, root, session="session", *, assistant=CLAIM, two_exchanges=False,
                  session_time=None, message_time=None):
    meta = {"id": session, "cwd": str(root)}
    if session_time:
        meta["timestamp"] = session_time
    rows = [{"type": "session_meta", "payload": meta}]
    for index in range(2 if two_exchanges else 1):
        for role, text in (("user", USER), ("assistant", assistant)):
            record = {"type": "response_item", "payload": {
                "type": "message", "turn_id": f"turn-{index + 1}", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
            }}
            if role == "assistant" and message_time:
                record["timestamp"] = message_time
            rows.append(record)
    native = root / f"{session}.jsonl"
    native.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    adapter = CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive", project_root=root)
    snapshot = await adapter.sync_session(native, session, project_name=PROJECT)
    rendering = backend.transcript_store.reconstruct(snapshot.source.id, source_revision=snapshot.source.source_revision)
    windows = render_distill_exchange_windows(rendering, [1, 2] if two_exchanges else [1])
    return snapshot, windows


def refs(windows, *, basis="source_report", role="assistant"):
    return [{"kind": basis, "exchange_index": window["exchange_index"],
             "role": role, "content_sha256": window["content_sha256"]} for window in windows]


async def admit(backend, snapshot, windows, candidate_id="candidate", *, basis="source_report",
                role="assistant", statement=CLAIM, verification_refs=None):
    return await admit_separated_candidate(
        backend, candidate_id=candidate_id, project_name=PROJECT, candidate_type="memory",
        statement=statement, distill_job_id=snapshot.distill_job_id,
        evidence_basis=basis, verification_outcome="verified",
        verification_refs=refs(windows, basis=basis, role=role) if verification_refs is None else verification_refs,
        verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
    )


def knowledge_item(*, module="diagnostics", statement=CLAIM):
    return {"title": "Diagnostic source account", "statement": statement,
            "topic_path": [module], "claim_kind": "source_report"}


async def publish(backend, root, candidate, *, module="diagnostics"):
    result = await resolve_separated_review(
        backend, candidate_id=candidate.id, disposition="add",
        reason="Retain only the checked source speaker's bounded account.",
        knowledge_items=[knowledge_item(module=module)], project_root=root,
        expected_project_name=PROJECT,
    )
    return await backend.structured_store.knowledge_store.get_entry(result["canonical_truth_ids"][0], project_name=PROJECT)


@pytest.mark.parametrize("mutation", ["basis", "speaker", "source", "exchanges", "digest", "ref_kind"])
def test_sr01_pending_replay_cannot_rebind_authority_or_source(isolated, mutation):
    """Changing proposal evidence must not overwrite an existing checked report.

    The source/job mutation deliberately exercises the command identity guard;
    it is not a claim that an MCP caller controls deterministic candidate IDs.
    """
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root, two_exchanges=True))
        candidate, _ = run(admit(backend, snapshot, windows[:1]))
        original_report = candidate.source_report.model_dump(mode="json")
        store = backend.structured_store.knowledge_store
        original_evidence = run(store.list_evidence(candidate.id))[0]
        requested_snapshot = snapshot
        requested_windows = windows[:1]
        requested_basis = "source_report"
        requested_role = "assistant"
        changed_refs = None
        if mutation == "basis":
            requested_basis, requested_role = "user_statement", "user"
        elif mutation == "speaker":
            requested_role = "user"
        elif mutation == "source":
            requested_snapshot, requested_windows = run(capture(backend, root, "different-source"))
        elif mutation == "exchanges":
            requested_windows = windows
        else:
            changed_refs = refs(windows[:1])
            changed_refs[0]["content_sha256" if mutation == "digest" else "kind"] = (
                "0" * 64 if mutation == "digest" else "transcript"
            )
        try:
            run(admit(backend, requested_snapshot, requested_windows, candidate.id,
                      basis=requested_basis, role=requested_role, verification_refs=changed_refs))
        except ValueError:
            pass
        current = run(store.get_candidate(candidate.id))
        current_evidence = run(store.list_evidence(candidate.id))[0]
        assert current.source_report is not None, f"{mutation} replay stripped an existing report"
        assert current.source_report.model_dump(mode="json") == original_report
        assert current_evidence.evidence_basis == original_evidence.evidence_basis
        assert current_evidence.distill_job_id == original_evidence.distill_job_id
        assert current_evidence.verification_refs == original_evidence.verification_refs


def test_sr01_exact_pending_replay_remains_usable(isolated):
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        first, replay = run(admit(backend, snapshot, windows))
        repeated, replay_again = run(admit(backend, snapshot, windows, first.id))
        assert not replay and replay_again
        assert repeated.source_report == first.source_report
        row = run(publish(backend, root, repeated))
        assert row.source_report == first.source_report


@pytest.mark.parametrize("operation", ["replay", "prepare"])
def test_sr01_missing_source_blocks_promotion_without_erasing_identity(isolated, monkeypatch, operation):
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        candidate, _ = run(admit(backend, snapshot, windows))
        original = candidate.source_report
        monkeypatch.setattr(backend.transcript_store, "get_revision", lambda *_args, **_kwargs: None)
        if operation == "replay":
            run(admit(backend, snapshot, windows, candidate.id))
        else:
            prepared = run(prepare_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id]))
            assert candidate.id not in prepared.eligible_candidate_ids
        store = backend.structured_store.knowledge_store
        assert run(store.get_candidate(candidate.id)).source_report == original
        evidence = run(store.list_evidence(candidate.id))[0]
        assert evidence.verification_outcome != "verified"
        with pytest.raises(ValueError):
            run(publish(backend, root, candidate))


def test_sr01_public_relabel_does_not_persist_as_approval(isolated, monkeypatch, record_property):
    """Invoke the public handler locally, with real ID helper and SQLite.

    No MCP transport, service or semantic provider is involved. The only mocked
    public callbacks bind the isolated backend and suppress optional events.
    """
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        ledger = backend.transcript_store
        owner = "independent-manual-report-review"
        for chunk, _checkpoint in ledger.claim_distill_chunks(
            snapshot.distill_job_id, lease_owner=owner, limit=None, execution_source="interactive_agent",
        ):
            ledger.checkpoint_distill_chunk(
                snapshot.distill_job_id, chunk.id, lease_owner=owner,
                result={"reviewed": True, "content_sha256": chunk.content_sha256, "candidate_ids": []},
            )
        assert ledger.claim_distill_review(
            snapshot.distill_job_id, lease_owner=owner, execution_source="interactive_agent",
        ) is not None
        monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
        monkeypatch.setattr(governance_handlers, "_record_state_event", lambda *_args, **_kwargs: None)
        arguments = {"kind": "memory", "project_name": PROJECT, "category": "diagnostics",
                     "content": CLAIM, "source": "isolated native source", "distill_job_id": snapshot.distill_job_id,
                     "evidence_basis": "source_report", "verification_outcome": "verified", "verification_refs": refs(windows)}
        first = governance_handlers.tool_govern_memory("suggest", arguments)
        assert first["success"], first
        original = run(backend.structured_store.knowledge_store.get_candidate(first["entry_id"]))
        assert original.source_report is not None
        second = governance_handlers.tool_govern_memory("suggest", {
            **arguments, "evidence_basis": "user_statement", "verification_refs": refs(windows, basis="user_statement", role="user"),
        })
        decision = governance_handlers.tool_govern_memory("decide", {
            "kind": "knowledge", "project_name": PROJECT, "candidate_id": first["entry_id"],
            "decision": "confirm", "disposition": "add", "reason": "Persist only the original attributed account.",
            "knowledge_items": [{**knowledge_item(), "claim_kind": "implementation_fact"}],
        })
        record_property("first_suggest", first)
        record_property("relabel_suggest", second)
        record_property("review", decision)
    with open_backend(data) as fresh:
        rows = run(search_current_knowledge(fresh, query="production rollout", project_name=PROJECT, limit=100))
        record_property("reopened_rows", [row.to_dict() for row in rows])
        assert rows, decision
        assert all(row.source_report is not None for row in rows), "Public replay persisted an unqualified approval fact"
        assert all(row.source_report == original.source_report for row in rows)
        assert second["success"] is False, "Public replay accepted a different evidence authority"


@pytest.mark.parametrize("disposition", ["handoff", "defer", "conflict"])
def test_sr03_unfinished_report_retains_readable_and_typed_attribution(isolated, disposition):
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        candidate, _ = run(admit(backend, snapshot, windows))
        prepared = run(prepare_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id]))
        decision = AssimilationDecision.model_validate({"points": [{
            "candidate_id": candidate.id, "disposition": disposition,
            "reason": "Preserve this source account for a later bounded task.",
        }]})
        plan = validate_separated_assimilation_decision(prepared, decision)
        applied = run(apply_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id], plan=plan))
        handoff_id = applied["points"][0]["handoff_id"]
        expected = candidate.source_report
    with open_backend(data) as fresh:
        handoff = run(fresh.structured_store.get_task_handoff(handoff_id))
        assert handoff.summary == expected.render_statement()
        assert all(expected.render_statement() in step for step in handoff.next_steps)
        assert SourceReport.model_validate(handoff.context["source_report"]) == expected


def test_sr03_replay_rejects_a_legacy_unqualified_handoff(isolated):
    """A synthetic legacy TaskHandoff is trusted fixture setup, not a public write exploit."""
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        candidate, _ = run(admit(backend, snapshot, windows))
        prepared = run(prepare_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id]))
        plan = validate_separated_assimilation_decision(prepared, AssimilationDecision.model_validate({"points": [{
            "candidate_id": candidate.id, "disposition": "handoff", "reason": "Retain the scoped report as unfinished work.",
        }]}))
        applied = run(apply_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id], plan=plan))
        handoff = run(backend.structured_store.get_task_handoff(applied["points"][0]["handoff_id"]))
        legacy = handoff.model_copy(update={"summary": CLAIM, "next_steps": [CLAIM],
            "context": {"candidate_id": candidate.id, "distill_job_id": snapshot.distill_job_id}})
        run(backend.structured_store.save_task_handoff(legacy))
        with pytest.raises(ValueError):
            run(apply_separated_assimilation(backend, project_name=PROJECT, project_root=str(root), candidate_ids=[candidate.id], plan=plan))


@pytest.mark.parametrize("role,expected", [("user", USER), ("assistant", CLAIM)])
def test_sr02_verification_receives_actual_speaker_separately_from_full_context(isolated, role, expected):
    root, data = isolated
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root))
        candidate = DistillCandidate(kind="memory", category="diagnostics", content=CLAIM, confidence=0.7,
            evidence_basis="source_report", verification_refs=refs(windows, role=role))
        manifest = _build_candidate_verification_manifest(
            packet={"project_name": PROJECT, "semantic_decision_exchanges": windows},
            validated_candidates=[(candidate, {"kind": "memory", "content": CLAIM})],
            project_root=root, backend=backend, distill_job_id=snapshot.distill_job_id,
        )
        source = manifest["candidates"][0]["sources"][0]
        assert source["content"] == expected
        assert source["role"] == role
        assert source["content_sha256"] == windows[0]["content_sha256"]
        context = manifest["session_context"][0]["content"]
        assert USER in context and CLAIM in context
        assert source_report_speaker_excerpt(backend, project_name=PROJECT, job_id=snapshot.distill_job_id,
            ref=candidate.verification_refs[0].model_copy(update={"content_sha256": "0" * 64})) is None


def test_sr02_manual_checked_paraphrase_keeps_the_existing_flow(isolated):
    """A supplied semantic judgment is a fixture; passing it is not model evidence."""
    root, data = isolated
    native_text = "The diagnostic pilot succeeded; this says nothing about production."
    paraphrase = "The pilot diagnostic worked without establishing a production result."
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root, assistant=native_text))
        candidate, _ = run(admit(backend, snapshot, windows, statement=paraphrase))
        assert candidate.source_report is not None
        assert candidate.source_report.text == paraphrase
        row = run(publish(backend, root, candidate))
        entry_id = row.id
    with open_backend(data) as fresh:
        row = run(fresh.structured_store.knowledge_store.get_entry(entry_id, project_name=PROJECT))
        assert row.source_report.text == paraphrase
        assert row.statement == row.source_report.render_statement()


def test_sr04_global_search_keeps_distinct_native_source_reports(isolated):
    root, data = isolated
    with open_backend(data) as backend:
        ids = set()
        for index in range(2):
            snapshot, windows = run(capture(backend, root, f"source-{index}"))
            candidate, _ = run(admit(backend, snapshot, windows, f"candidate-{index}"))
            ids.add(run(publish(backend, root, candidate, module=f"context-{index}")).id)
    with open_backend(data) as fresh:
        stored = run(fresh.structured_store.knowledge_store.list_entries(PROJECT))
        assert len(stored) == 2
        assert len({row.source_report.source_id for row in stored}) == 2
        global_rows = run(search_current_knowledge(fresh, query="production rollout", limit=100))
        assert ids <= {row.id for row in global_rows}, "Global dedup hid one distinct source-scoped report"


def test_sr04_exact_same_report_deduplicates_without_erasing_distinct_sources():
    """Read-layer duplicates are fixtures, not a raw-database write bypass."""
    report = SourceReport(speaker="assistant", period="that session (date unknown)", session_id="one-session",
                          source_id="one-source", source_revision="one-revision", exchange_indexes=[1], text=CLAIM)
    first = KnowledgeEntry(id="first", project_name=PROJECT, module_path=["one"], title=report.render_title(),
                           statement=report.render_statement(), source_report=report)
    duplicate = first.model_copy(update={"id": "duplicate", "module_path": ["other"]})
    other_report = report.model_copy(update={"session_id": "another-session", "source_id": "another-source"})
    distinct = KnowledgeEntry(id="distinct", project_name=PROJECT, module_path=["two"], title=other_report.render_title(),
                              statement=other_report.render_statement(), source_report=other_report)
    assert len(_deduplicate_current([first, duplicate], across_projects=True)) == 1
    both = _deduplicate_current([first, duplicate, distinct], across_projects=True)
    assert len(both) == 2
    assert {row.source_report.source_id for row in both} == {"one-source", "another-source"}


def test_sr05_multi_day_report_labels_session_time_and_keeps_stated_period(isolated):
    root, data = isolated
    stated = "On 2024-06-03, the pilot route worked."
    with open_backend(data) as backend:
        snapshot, windows = run(capture(backend, root, assistant=stated,
            session_time="2024-06-01T02:03:04Z", message_time="2024-06-03T04:05:06Z"))
        candidate, _ = run(admit(backend, snapshot, windows, statement=stated))
        row = run(publish(backend, root, candidate))
        entry_id = row.id
    with open_backend(data) as fresh:
        row = run(fresh.structured_store.knowledge_store.get_entry(entry_id, project_name=PROJECT))
        assert row.source_report.period == "2024-06-01T02:03:04Z"
        assert row.source_report.text == stated
        label = row.statement.casefold()
        assert "source-session timestamp" in label, "Session creation time is displayed as an unqualified report period"
        assert "source-session timestamp" in row.title.casefold()
        assert "2024-06-03" in row.statement
