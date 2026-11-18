"""Stage 4 Dream contract: shared commit, split reports, and stop dedup.

Isolated tmp_path fixtures and fake providers only. No native program, product
model, hook, or live store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import (
    CandidateScopeSegment,
    CandidateVerificationDecision,
    CandidateVerificationPoint,
    OutputVerification,
    UpdateMeaningJudgment,
)
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.commands.dream import dream_once
from harness_mem.commands.dream_assimilation import (
    DREAM_SOURCE_RECHECK_CONTRACT,
    DreamAssimilationCandidate,
    build_dream_maintenance_plan,
    prepare_dream_assimilation,
)
from harness_mem.commands.knowledge_assimilation import (
    commit_shared_knowledge_change,
    record_assimilation_result,
)
from harness_mem.commands.separated_assimilation import _bind_report_items, target_version
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.knowledge import (
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import (
    ReportOmission,
    ReportOutputProposal,
    ReportQualifier,
    ReportScopeSegment,
    ReportTopicJudgment,
    SourceReport,
    report_output_scope_text,
    source_report_snapshot,
)
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.mcp.dream_handlers import _dream_run_summary
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

TOKEN = "UNIQUE-STATEMENT-TOKEN-991"
OLD_TEXT = "Alpha cache stays local. Beta cache stays signed."


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    value = LocalMemoryBackend(tmp_path / "data")
    _run(value.init())
    try:
        yield value
    finally:
        _run(value.close())


def _publish(backend, *entries, source_text=None):
    root = backend.data_dir / "demo-project"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "source.md"
    path.write_text(source_text if source_text is not None else "\n".join(entry.statement for entry in entries), encoding="utf-8")
    source = ProjectKnowledgeSourceRef(
        label="Stage 4 fixture", target=path.as_uri(), kind="repository",
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    store = backend.structured_store.knowledge_store
    candidate = KnowledgeCandidate(
        id="stage4-fixture-" + "-".join(entry.id for entry in entries),
        project_name="demo", candidate_type="memory", statement="Stage 4 fixture.",
    )
    from harness_mem.core.schemas.knowledge import AssimilationDecision

    decision = AssimilationDecision(
        id="stage4-mutation-" + "-".join(entry.id for entry in entries),
        project_name="demo", candidate_id=candidate.id, disposition="add",
        canonical_truth_ids=[entry.id for entry in entries], reason="Test fixture.",
    )
    _run(store.save_candidate(candidate))
    _run(store.apply_current_change(
        candidate_before=candidate,
        candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=decision, added_entries=list(entries), predecessor_entries=[],
        source_refs_by_entry={entry.id: [source] for entry in entries},
    ))
    _run(store.cleanup_candidate(candidate.id))
    return root, path, _run(store.list_entries("demo", project_root=root))


def _result(decision):
    return ProviderResult(
        decision=decision, provider="stage4", model="test-model", duration_seconds=0.01,
        input_sha256="a" * 64, response_sha256="b" * 64, input_tokens=1, output_tokens=1,
        total_tokens=2, event_count=1,
    )


class _ConfirmProvider:
    name = "stage4-confirm"

    def __init__(self, *, fail_after=None):
        self.fail_after = fail_after
        self.calls = 0
        self.manifests = []

    def verify(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir, heartbeat
        self.calls += 1
        self.manifests.append(manifest)
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("second batch failed")
        points = []
        for candidate in manifest["candidates"]:
            points.append({
                "candidate_index": int(candidate["candidate_index"]),
                "semantic_support": "supported",
                "future_scope": "durable",
                "source_use": "standing_decision",
                "reason": "The current source still supports this exact title and statement.",
                "scope_segments": [{
                    "text": candidate["scope_text"],
                    "source_use": "standing_decision",
                    "future_scope": "durable",
                    "standalone": True,
                    "content_role": "claim",
                    "source_support": "supported",
                }],
            })
        return _result(CandidateVerificationDecision.model_validate({"points": points}))


class _UnresolvedProvider:
    name = "stage4-unresolved"

    def __init__(self):
        self.calls = 0

    def verify(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir, heartbeat
        self.calls += 1
        points = [{
            "candidate_index": int(candidate["candidate_index"]),
            "semantic_support": "partial",
            "future_scope": "unclear",
            "source_use": "unclear",
            "reason": "The source does not settle this statement.",
            "scope_segments": [{
                "text": "not-the-statement",
                "source_use": "unclear",
                "future_scope": "unclear",
                "standalone": True,
                "content_role": "unclear",
                "source_support": "unclear",
            }],
        } for candidate in manifest["candidates"]]
        return _result(CandidateVerificationDecision.model_validate({"points": points}))


def _scope_point(title, statement, disposition="add", targets=(), meaning=None):
    meaning_model = UpdateMeaningJudgment.model_validate(meaning) if isinstance(meaning, dict) else meaning
    point = {
        "disposition": disposition,
        "matched_truth_ids": list(targets),
        "knowledge_items": [{
            "title": title, "statement": statement, "topic_path": ["cache"],
            "claim_kind": "implementation_fact",
        }],
        "reason": "Retain the verified project fact.",
        "verified_at": datetime.now(timezone.utc),
        "final_scope_judgment": CandidateVerificationDecision(points=[CandidateVerificationPoint(
            candidate_index=0, semantic_support="supported", future_scope="durable",
            source_use="standing_decision",
            reason="The final title and statement were checked against the source.",
            scope_segments=[CandidateScopeSegment(
                text=title + "\n" + statement, source_use="standing_decision", future_scope="durable",
                standalone=True, content_role="claim", source_support="supported",
            )],
            update_meaning_judgment=meaning_model,
        )]).model_dump(mode="json"),
    }
    if meaning is not None:
        point["update_meaning_judgment"] = meaning
    return point


def test_multislice_confirm_resume_failure_and_receipts(backend):
    entries = [
        KnowledgeEntry(
            id=f"stage4-{index}", project_name="demo", title=f"Cache rule {index}",
            statement=f"Cache rule {index} stays local. {TOKEN}", module_path=["cache"],
        )
        for index in range(5)
    ]
    root, _path, _rows = _publish(backend, *entries)
    provider = _ConfirmProvider()
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    first = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent",
        reflection_job_id="stage4-slices", deadline=deadline, semantic_provider=provider,
    ))
    assert first.status == "continuing"
    assert first.execution_status == "continuing"
    assert provider.calls == 1
    assert len(provider.manifests[0]["candidates"]) == 4
    assert {item.source_id for item in first.items} == {f"stage4-{index}" for index in range(4)}
    assert all(item.final_action == "applied" for item in first.items)

    second = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent",
        reflection_job_id="stage4-slices", deadline=deadline, semantic_provider=provider,
    ))
    assert provider.calls == 2
    assert len(provider.manifests[1]["candidates"]) == 1
    assert second.execution_status == "completed"
    assert second.resolution_status == "resolved"
    assert second.status == "completed"
    assert {item.source_id for item in second.items} == {f"stage4-{index}" for index in range(5)}
    notes = "\n".join(second.notes or [])
    assert TOKEN not in notes
    assert "dream verification receipt:" in notes
    receipt = json.loads(notes.split("dream verification receipt: ", 1)[1].split("\n", 1)[0])
    assert receipt["contract_version"]
    assert len(receipt["input_fingerprint"]) == 64
    assert receipt["target_fingerprints"]
    assert "statement" not in json.dumps(receipt["target_fingerprints"])

    failing = _ConfirmProvider(fail_after=1)
    more = [
        KnowledgeEntry(
            id=f"stage4-fail-{index}", project_name="demo", title=f"Fail rule {index}",
            statement=f"Fail rule {index} stays signed.", module_path=["other"],
        )
        for index in range(5)
    ]
    _publish(backend, *more)
    with pytest.raises(RuntimeError, match="second batch failed"):
        _run(dream_once(
            backend, project_name="demo", project_root=root, source="agent",
            semantic_provider=failing,
        ))
    failed = _run(backend.structured_store.list_dream_runs("demo", limit=1))[0]
    assert failed.status == "failed"
    assert failed.execution_status == "failed"
    assert failed.resolution_status == "failed"
    assert any(item.final_action == "applied" for item in failed.items)
    with pytest.raises(ValueError, match="not resumable"):
        _run(dream_once(
            backend, project_name="demo", project_root=root, source="agent",
            reflection_job_id="stage4-failed", resume_run_id=failed.id, semantic_provider=failing,
        ))


def test_unchanged_unresolved_stop_dedup_and_invalidation(backend):
    entry = KnowledgeEntry(
        id="stage4-open", project_name="demo", title="Open cache rule",
        statement=f"Open cache rule waits. {TOKEN}", module_path=["cache"],
    )
    root, path, rows = _publish(backend, entry)
    entry = rows[0]
    provider = _UnresolvedProvider()
    first = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 1
    assert first.status == "failed"
    assert first.execution_status == "completed"
    assert first.resolution_status == "unresolved"
    summary = _dream_run_summary(first.to_dict())
    assert summary["cleanup_complete"] is False
    assert summary["resolution_status"] == "unresolved"
    assert "not successful cleanup" in summary["message"]
    stored = _run(backend.structured_store.get_dream_run(first.id))
    assert TOKEN not in "\n".join(stored.notes or [])

    second = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 1
    assert any(item.result.get("semantic_request") is False for item in second.items)
    assert _run(backend.structured_store.knowledge_store.get_entry(entry.id, project_name="demo")).statement == entry.statement

    path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 2

    _run(record_retrieval_signal(
        backend, project_name="demo", signal_type="context_outcome", target_kind="knowledge_entry",
        target_id=entry.id, value=-1.0, context={"outcome": "misleading"},
    ))
    _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 3

    due = _run(backend.structured_store.list_dream_runs("demo", limit=1))[0]
    fingerprints = dict(due.continuation.get("unresolved_fingerprints") or {})
    assert entry.id in fingerprints
    fingerprints[entry.id]["review_after"] = "2000-01-01T00:00:00+00:00"
    due.continuation["unresolved_fingerprints"] = fingerprints
    _run(backend.structured_store.save_dream_run(due))
    _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 4


def test_missing_repository_source_stays_recallable(backend):
    entry = KnowledgeEntry(
        id="stage4-missing", project_name="demo", title="Missing source rule",
        statement="Missing source rule stays recallable.", module_path=["cache"],
    )
    root, path, rows = _publish(backend, entry)
    path.unlink()
    provider = _ConfirmProvider()
    run = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 0
    kept = _run(backend.structured_store.knowledge_store.get_entry(rows[0].id, project_name="demo"))
    assert kept is not None and kept.statement == entry.statement
    review = run.source_reviews[rows[0].id]
    assert review["automatic_deletion_authorized"] is False
    assert review["policy_version"] == "missing-source-review-v1"
    again = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=provider,
    ))
    assert provider.calls == 0
    assert again.source_reviews[rows[0].id]["automatic_deletion_authorized"] is False
    summary = _dream_run_summary(run.to_dict())
    assert summary["cleanup_complete"] is False


def test_cas_and_same_candidate_retry_do_not_double_apply(backend, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "policy.txt"
    statement = "The service keeps only verified cache entries."
    path.write_text(statement, encoding="utf-8")
    ref = ProjectKnowledgeSourceRef(
        label="policy", kind="repository", target=path.as_uri(),
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    candidate = KnowledgeCandidate(
        id="stage4-retry", project_name="demo", candidate_type="memory", statement=statement,
    )
    point = _scope_point("Verified cache", statement)
    ids = _run(record_assimilation_result(
        backend, candidate=candidate, point=point, project_root=root, source_refs=[ref],
    ))
    store = backend.structured_store.knowledge_store
    current = _run(store.get_entry(ids[0], project_name="demo"))
    stale = current.model_copy(update={"statement": "A different retention window."})
    replacement = "The service keeps only verified cache entries for thirty days."
    # A replacement is a new semantic operation, not a changed replay of add.
    candidate = KnowledgeCandidate(
        id="stage4-retry-replacement", project_name="demo", candidate_type="memory", statement=replacement,
    )
    updated_path = root / "updated-policy.txt"
    updated_path.write_text(replacement, encoding="utf-8")
    ref = ProjectKnowledgeSourceRef(
        label="updated policy", kind="repository", target=updated_path.as_uri(),
        digest=hashlib.sha256(updated_path.read_bytes()).hexdigest(),
    )
    meaning = UpdateMeaningJudgment(
        relationship="preserves_applicable_meaning", predecessor_conditions=[],
        successor_statements=[replacement], predecessor_statements=[current.statement],
        predecessor_versions=[target_version({
            "title": current.title, "statement": current.statement,
            "topic_path": list(current.module_path), "source_report": None,
        })],
        basis="The replacement keeps the verified cache condition.",
    ).model_dump(mode="json")
    with pytest.raises(CanonicalTransactionPreconditionError):
        _run(record_assimilation_result(
            backend, candidate=candidate,
            point=_scope_point("Verified cache", replacement, "replace", ids, meaning),
            project_root=root, source_refs=[ref], expected_predecessor_entries=[stale],
        ))
    assert _run(store.get_entry(ids[0], project_name="demo")).statement == statement

    replace_point = _scope_point("Verified cache", replacement, "replace", ids, meaning)
    new_ids = _run(commit_shared_knowledge_change(
        backend, candidate=candidate, point=replace_point, project_root=root, source_refs=[ref],
        expected_predecessor_entries=[current],
    ))["truth_ids"]
    assert new_ids != ids
    assert _run(store.get_entry(ids[0], project_name="demo")) is None
    replay = _run(record_assimilation_result(
        backend, candidate=candidate, point=replace_point, project_root=root, source_refs=[ref],
        expected_predecessor_entries=[current],
    ))
    assert replay == new_ids
    found = _run(search_current_knowledge(backend, project_name="demo", query="thirty days", limit=10))
    assert [row.id for row in found] == new_ids
    assert len(_run(store.list_entries("demo"))) == 1


def _capture_report(backend, text):
    root = Path(backend.data_dir) / "report-project"
    root.mkdir(parents=True, exist_ok=True)
    user = "Review the cited account only."
    rows = [
        {"type": "session_meta", "payload": {"id": "stage4-session", "timestamp": "2024-06-01T02:03:04Z"}},
        {"type": "response_item", "payload": {"type": "message", "turn_id": "turn-1", "role": "user",
            "content": [{"type": "input_text", "text": user}]}},
        {"type": "response_item", "payload": {"type": "message", "turn_id": "turn-1", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}},
    ]
    native = "\n".join(json.dumps(row) for row in rows) + "\n"
    rendering = f"User: {user}\n\nAssistant: {text}"
    snapshot = _run(persist_session_snapshot(
        backend, Observation(
            session_id="stage4-session", client="codex", raw_content=rendering,
            content_type="transcript", timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc), metadata={},
        ),
        project_name="demo", project_root=str(root), client="codex", session_id="stage4-session",
        source_kind="jsonl", source_uri=(root / "stage4-session.jsonl").as_uri(),
        source_text=rendering, raw_bytes=native.encode(), native_input_bytes=native.encode(),
        parser_version="codex-jsonl-v1",
    ))
    window = render_distill_exchange_windows(rendering, [1])[0]
    report = SourceReport(
        speaker="assistant", period="2024-06-01T02:03:04Z", session_id="stage4-session",
        source_id=snapshot.source.id, source_revision=snapshot.source.source_revision,
        exchange_indexes=[1], text=text,
    )
    ref = ProjectKnowledgeSourceRef(
        label="report", kind="source_report", digest=window["content_sha256"],
        target=Path(backend.transcript_store.db_path).resolve().as_uri() + "#" + urlencode({
            "source_id": report.source_id, "source_revision": report.source_revision,
            "exchange": 1, "role": report.speaker,
        }),
    )
    return report, ref


def _output(predecessor, title, text):
    written = predecessor.model_copy(update={"topic_title": title, "text": text, "exchange_indexes": [1]})
    judgment = ReportTopicJudgment(
        relationship="same_topic", predecessor_title=predecessor.render_title(),
        successor_title=title, basis="The cited account is this same cache topic.",
    )
    scope = report_output_scope_text(written)
    return ReportOutputProposal(
        topic_title=title, text=text, exchange_indexes=[1], source_support="supported",
        source_use="standing_decision", future_scope="durable",
        topic_judgment=judgment,
        qualifiers=[ReportQualifier(text="stays signed", source_support="unsupported", independently_useful=True)]
        if "stays signed" in text else [],
        scope_segments=[ReportScopeSegment(
            text=scope, source_use="standing_decision", future_scope="durable",
            content_role="claim", source_support="supported",
        )],
    ), written


def test_report_split_commits_once_and_rejects_partial_or_unbound_outputs(backend, tmp_path):
    report, ref = _capture_report(backend, OLD_TEXT)
    root = tmp_path / "project"
    root.mkdir()
    candidate = KnowledgeCandidate(
        id="stage4-report", project_name="demo", candidate_type="memory",
        statement=report.text, source_report=report,
    )
    add = {
        "disposition": "add",
        "knowledge_items": [{
            "title": report.legacy_title(), "statement": "lied",
            "topic_path": ["reports"], "claim_kind": "source_report",
        }],
        "reason": "Retain the cited account.",
        "final_scope_judgment": CandidateVerificationDecision(points=[CandidateVerificationPoint(
            candidate_index=0, semantic_support="supported", future_scope="durable",
            source_use="standing_decision",
            reason="The final title and rendered body were checked.",
            scope_segments=[CandidateScopeSegment(
                text=report_output_scope_text(report),
                source_use="standing_decision", future_scope="durable", standalone=True,
                content_role="claim", source_support="supported",
            )],
        )]).model_dump(mode="json"),
    }
    old_ids = _run(record_assimilation_result(
        backend, candidate=candidate, point=add, project_root=root, source_refs=[ref],
    ))
    store = backend.structured_store.knowledge_store
    current = _run(store.get_entry(old_ids[0], project_name="demo"))
    candidate = KnowledgeCandidate(
        id="stage4-report-split", project_name="demo", candidate_type="memory",
        statement=report.text, source_report=report,
    )
    first, written_first = _output(report, "Alpha cache", "Alpha cache stays local.")
    second, written_second = _output(report, "Beta cache", "Beta cache stays signed.")
    omission = ReportOmission(text=" ", classification="temporary_context")
    statements = [written_first.render_statement(), written_second.render_statement()]
    version = target_version({
        "title": current.title, "statement": current.statement,
        "topic_path": list(current.module_path),
        "source_report": source_report_snapshot(current.source_report),
    })
    meaning = UpdateMeaningJudgment(
        relationship="preserves_applicable_meaning", predecessor_conditions=[],
        successor_statements=statements, predecessor_statements=[current.statement],
        predecessor_versions=[version],
        basis="Both outputs keep the cited cache account.",
    )
    scopes = [report_output_scope_text(written_first), report_output_scope_text(written_second)]
    replace = {
        "disposition": "replace",
        "matched_truth_ids": old_ids,
        "knowledge_items": [{
            "title": item.render_title(), "statement": item.render_statement(),
            "topic_path": ["reports"], "claim_kind": "source_report",
        } for item in (written_first, written_second)],
        "reason": "Split the cited account into its two cache topics.",
        "report_split": {
            "original_support": "supported",
            "outputs": [item.model_dump(mode="json") for item in (first, second)],
            "omissions": [omission.model_dump(mode="json")],
        },
        "update_meaning_judgment": meaning.model_dump(mode="json"),
        "final_scope_judgment": CandidateVerificationDecision(points=[
            CandidateVerificationPoint(
                candidate_index=index, semantic_support="supported", future_scope="durable",
                source_use="standing_decision",
                reason="The output title, body, and attribution were checked.",
                scope_segments=[CandidateScopeSegment(
                    text=scope, source_use="standing_decision", future_scope="durable",
                    standalone=True, content_role="claim", source_support="supported",
                )],
                update_meaning_judgment=meaning,
            )
            for index, scope in enumerate(scopes)
        ]).model_dump(mode="json"),
    }
    new_ids = _run(commit_shared_knowledge_change(
        backend, candidate=candidate, point=replace, project_root=root, source_refs=[ref],
        expected_predecessor_entries=[current],
    ))["truth_ids"]
    assert _run(store.get_entry(old_ids[0], project_name="demo")) is None
    rows = _run(store.list_entries("demo"))
    assert {row.id for row in rows} == set(new_ids)
    assert len(rows) == 2
    by_title = {row.title: row for row in rows}
    assert by_title["Alpha cache"].source_report.speaker == "assistant"
    assert "stays signed" in by_title["Beta cache"].source_report.text
    alpha_found = _run(search_current_knowledge(backend, project_name="demo", query="local", limit=10))
    beta_found = _run(search_current_knowledge(backend, project_name="demo", query="signed", limit=10))
    assert {row.id for row in alpha_found} == {by_title["Alpha cache"].id}
    assert {row.id for row in beta_found} == {by_title["Beta cache"].id}
    assert old_ids[0] not in {row.id for row in alpha_found} | {row.id for row in beta_found}

    partial = current.model_copy()
    prepared = prepare_dream_assimilation(
        project_name="demo", project_root=root, run_id="split-run", signal_kind="stale",
        candidates=[DreamAssimilationCandidate(
            candidate_id="split-candidate", entry=current, sources=(), source_excerpts=(),
            semantic_support="partial", future_scope="durable",
            verification_reason="Only part of the account was supported.",
            verification_contract=DREAM_SOURCE_RECHECK_CONTRACT,
            scope_verification=CandidateVerificationPoint(
                candidate_index=0, semantic_support="partial", future_scope="unclear",
                source_use="unclear", reason="Partial support stays partial.",
                report_outputs=[first, second], report_omissions=[omission],
            ),
        )],
    )
    plan = build_dream_maintenance_plan(prepared)
    assert plan[0]["disposition"] == "no_write"
    assert "partial source support" in plan[0]["reason"]
    assert _run(store.get_entry(by_title["Alpha cache"].id, project_name="demo")) is not None

    dropped = first.model_copy(update={"qualifiers": [ReportQualifier(
        text="independently useful extra", source_support="unsupported", independently_useful=True,
    )]})
    dropped_plan = build_dream_maintenance_plan(prepare_dream_assimilation(
        project_name="demo", project_root=root, run_id="drop-run", signal_kind="stale",
        candidates=[DreamAssimilationCandidate(
            candidate_id="drop-candidate", entry=current, sources=(), source_excerpts=(),
            semantic_support="supported", future_scope="durable",
            verification_reason="A useful qualifier was left out.",
            verification_contract=DREAM_SOURCE_RECHECK_CONTRACT,
            scope_verification=CandidateVerificationPoint(
                candidate_index=0, semantic_support="supported", future_scope="durable",
                source_use="standing_decision", reason="The split dropped a useful qualifier.",
                report_outputs=[dropped, second], report_omissions=[omission],
                output_verifications=[
                    OutputVerification(
                        semantic_support="supported", future_scope="durable", source_use="standing_decision",
                        reason="Checked the written output.",
                        scope_segments=[CandidateScopeSegment(
                            text=scope, source_use="standing_decision", future_scope="durable",
                            standalone=True, content_role="claim", source_support="supported",
                        )],
                    )
                    for scope in scopes
                ],
            ),
        )],
    ))
    assert dropped_plan[0]["disposition"] == "no_write"
    assert _run(store.list_entries("demo"))
    with pytest.raises(ValueError, match="v7 literal proofs cannot carry ordinary report outputs"):
        CandidateVerificationPoint(
            candidate_index=0, semantic_support="supported", future_scope="durable",
            source_use="standing_decision", reason="A literal proof cannot admit outputs.",
            literal_edit_contract="dream-existing-literal-edit-v1", report_outputs=[first, second],
        )
    with pytest.raises(ValueError, match="exactly one"):
        _bind_report_items(
            report,
            [{"title": "One", "statement": "A", "claim_kind": "source_report"},
             {"title": "Two", "statement": "B", "claim_kind": "source_report"}],
            writes=True,
        )
    del partial


def test_new_write_rejects_missing_or_changed_source_despite_a_valid_judgment(backend, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    statement = "The cache policy is the signed local copy."
    point = _scope_point("Cache policy", statement)
    candidate = KnowledgeCandidate(project_name="demo", candidate_type="memory", statement=statement)
    with pytest.raises(ValueError, match="evidence envelope or a reopenable source"):
        _run(record_assimilation_result(
            backend, candidate=candidate, point=point, project_root=root, source_refs=[],
        ))
    missing = root / "missing.txt"
    missing_ref = ProjectKnowledgeSourceRef(
        label="missing", kind="repository", target=missing.as_uri(), digest="ab" * 32,
    )
    with pytest.raises(ValueError, match="source unavailable"):
        _run(record_assimilation_result(
            backend, candidate=candidate, point=point, project_root=root, source_refs=[missing_ref],
        ))
    present = root / "policy.txt"
    present.write_text(statement, encoding="utf-8")
    changed = ProjectKnowledgeSourceRef(
        label="changed", kind="repository", target=present.as_uri(), digest="cd" * 32,
    )
    with pytest.raises(ValueError, match="source unavailable"):
        _run(record_assimilation_result(
            backend, candidate=candidate, point=point, project_root=root, source_refs=[changed],
        ))
    assert _run(backend.structured_store.knowledge_store.list_entries("demo")) == []
    good = ProjectKnowledgeSourceRef(
        label="good", kind="repository", target=present.as_uri(),
        digest=hashlib.sha256(present.read_bytes()).hexdigest(),
    )
    ids = _run(record_assimilation_result(
        backend, candidate=candidate, point=point, project_root=root, source_refs=[good],
    ))
    assert len(ids) == 1
    assert _run(search_current_knowledge(
        backend, project_name="demo", query="signed local copy", limit=5,
    ))[0].id == ids[0]


def test_old_dream_run_loads_without_execution_fields():
    payload = {
        "id": "old-run", "project_name": "demo", "started_at": "2024-01-01T00:00:00+00:00",
        "status": "completed", "items": [],
    }
    restored = DreamRun.from_dict(payload)
    assert restored.execution_status is None
    assert restored.resolution_status is None
    assert restored.to_dict()["execution_status"] is None


def test_dream_fact_with_report_outputs_does_not_invent_a_split(backend):
    entry = KnowledgeEntry(
        id="stage4-fact", project_name="demo", title="Plain fact",
        statement="Plain fact stays one row.", module_path=["cache"],
    )
    root, _path, rows = _publish(backend, entry)
    proposal = {
        "topic_title": "Plain fact", "text": "Plain fact stays one row.", "exchange_indexes": [1],
        "source_support": "supported", "source_use": "standing_decision", "future_scope": "durable",
        "topic_judgment": {
            "relationship": "same_topic", "predecessor_title": "Plain fact",
            "successor_title": "Plain fact", "basis": "Same cited fact topic.",
        },
        "scope_segments": [{
            "text": "placeholder", "source_use": "standing_decision", "future_scope": "durable",
            "content_role": "claim", "source_support": "supported",
        }],
    }
    provider_calls = {"count": 0}

    class _Outputs:
        name = "stage4-outputs"

        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir, heartbeat
            provider_calls["count"] += 1
            points = [{
                "candidate_index": int(candidate["candidate_index"]),
                "semantic_support": "supported", "future_scope": "durable",
                "source_use": "standing_decision",
                "reason": "Outputs were proposed for a fact row.",
                "scope_segments": [{
                    "text": candidate["scope_text"], "source_use": "standing_decision",
                    "future_scope": "durable", "standalone": True, "content_role": "claim",
                    "source_support": "supported",
                }],
                "report_outputs": [proposal, {**proposal, "topic_title": "Other fact",
                    "topic_judgment": {**proposal["topic_judgment"], "successor_title": "Other fact"}}],
            } for candidate in manifest["candidates"]]
            return _result(CandidateVerificationDecision.model_validate({"points": points}))

    run = _run(dream_once(
        backend, project_name="demo", project_root=root, source="agent", semantic_provider=_Outputs(),
    ))
    assert provider_calls["count"] == 1
    assert run.items[0].final_action == "rejected"
    kept = _run(backend.structured_store.knowledge_store.get_entry(rows[0].id, project_name="demo"))
    assert kept.statement == entry.statement
    assert len(_run(backend.structured_store.knowledge_store.list_entries("demo"))) == 1
