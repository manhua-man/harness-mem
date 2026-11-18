"""Shared write core: topic judgment, final scope, commit, and batch hold.

Isolated tmp_path fixtures only. No native executor, product model, hook, or live store.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.autonomous.models import (
    CandidateScopeSegment,
    CandidateVerificationDecision,
    CandidateVerificationPoint,
    UpdateMeaningJudgment,
)
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.commands.evidence_admission import content_admission_allows_durable_write
from harness_mem.commands.knowledge_assimilation import (
    commit_shared_knowledge_change,
    delete_current_knowledge,
    record_assimilation_result,
    recover_committed_assimilation,
)
from harness_mem.autonomous.provider import ProviderResult, _build_verification_prompt
from harness_mem.autonomous.worker import _verify_final_knowledge_scope
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    bind_final_scope_judgment,
    defer_blocked_final_scope,
    describe_truth_target_discovery,
    final_scope_proof,
    prepare_separated_assimilation,
    prove_supplied_final_scope,
    target_version,
    update_meaning_block,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.evidence import EvidenceRef
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEvidence,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import ReportTopicJudgment, SourceReport, report_output_scope_text
from harness_mem.mcp import tool_handlers
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.canonical_store import CanonicalTransactionPreconditionError
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.manual_batch_store import ManualBatchStore


LIMITATION = "not independently established current fact or user approval"
OLD_BODY = "Widget cache stays at the signed sample and is not rollout approval."
NEW_BODY = "Widget cache keeps the same account and now states the thirty-day bound."
UNRELATED_BODY = "Quillonvane archive shipping was independently approved yesterday."


def _report(**updates) -> SourceReport:
    payload = {
        "speaker": "assistant",
        "period": "2024-06-01T02:03:04Z",
        "session_id": "session-1",
        "source_id": "source-1",
        "source_revision": "revision-1",
        "exchange_indexes": [1],
        "text": OLD_BODY,
    }
    payload.update(updates)
    return SourceReport(**payload)


_LIVE_REPORTS: dict[tuple, tuple[str, str, str]] = {}
_ISO_PERIOD = re.compile(r"^\d{4}-\d{2}-\d{2}T")


async def _capture_report(backend, report: SourceReport):
    """Persist one reopenable transcript revision for this report's cited text."""

    key = (str(backend.data_dir.resolve()), report.session_id, report.speaker, report.period, report.text, tuple(report.exchange_indexes))
    cached = _LIVE_REPORTS.get(key)
    if cached is not None:
        return cached
    root = Path(backend.data_dir) / "report-project"
    root.mkdir(parents=True, exist_ok=True)
    user = "Review the cited account only."
    assistant = report.text if report.speaker == "assistant" else "Noted."
    spoken = report.text if report.speaker == "user" else assistant
    if report.speaker == "user":
        user = report.text
    rows = []
    if _ISO_PERIOD.match(report.period):
        rows.append({"type": "session_meta", "payload": {"id": report.session_id, "timestamp": report.period}})
    for role, text in (("user", user), ("assistant", assistant if report.speaker == "assistant" else "Noted.")):
        rows.append({"type": "response_item", "payload": {
            "type": "message", "turn_id": "turn-1", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        }})
    native = "\n".join(json.dumps(row) for row in rows) + "\n"
    rendering = f"User: {user}\n\nAssistant: {assistant if report.speaker == 'assistant' else 'Noted.'}"
    if report.speaker == "user":
        rendering = f"User: {report.text}\n\nAssistant: Noted."
        spoken = report.text
    snapshot = await persist_session_snapshot(
        backend, Observation(
            session_id=report.session_id, client="codex", raw_content=rendering,
            content_type="transcript", timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc), metadata={},
        ),
        project_name="demo", project_root=str(root), client="codex", session_id=report.session_id,
        source_kind="jsonl", source_uri=(root / f"{report.session_id}.jsonl").as_uri(),
        source_text=rendering, raw_bytes=native.encode(), native_input_bytes=native.encode(),
        parser_version="codex-jsonl-v1",
    )
    exchange = report.exchange_indexes[0]
    window = render_distill_exchange_windows(rendering, [exchange])[0]
    stored = (snapshot.source.id, snapshot.source.source_revision, window["content_sha256"], spoken)
    _LIVE_REPORTS[key] = stored
    return stored


async def _source_for(report: SourceReport, backend=None) -> ProjectKnowledgeSourceRef:
    if backend is None:
        exchange = report.exchange_indexes[0]
        return ProjectKnowledgeSourceRef(
            label="Retained source", kind="source_report", digest="a" * 64,
            target=(
                "file:///fixture/transcripts.sqlite"
                f"#source_id={report.source_id}&source_revision={report.source_revision}"
                f"&exchange={exchange}&role={report.speaker}"
            ),
        )
    source_id, revision, digest, _spoken = await _capture_report(backend, report)
    report.source_id = source_id
    report.source_revision = revision
    exchange = report.exchange_indexes[0]
    locator = Path(backend.transcript_store.db_path).resolve().as_uri() + "#" + urlencode({
        "source_id": source_id, "source_revision": revision, "exchange": exchange, "role": report.speaker,
    })
    return ProjectKnowledgeSourceRef(
        label="Retained source", kind="source_report", digest=digest, target=locator,
    )


def _repo_ref(root) -> ProjectKnowledgeSourceRef:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "fixture.txt"
    if not path.is_file():
        path.write_text("fixture source bytes\n", encoding="utf-8")
    return ProjectKnowledgeSourceRef(
        label="fixture",
        kind="repository",
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        target=path.as_uri(),
    )


def _seal_point(point, report: SourceReport | None = None):
    """Attach the written title and body the shared final-scope owner will see."""

    items = point.get("knowledge_items") or []
    if not items or point.get("disposition") not in {"add", "refine", "replace"}:
        return point
    meaning = point.get("update_meaning_judgment")
    parsed = UpdateMeaningJudgment.model_validate(meaning) if isinstance(meaning, dict) else meaning
    points = []
    for index, item in enumerate(items):
        if report is not None and item.get("claim_kind") == "source_report" and index == 0:
            written = report.model_copy(update={"topic_title": (
                None if str(item["title"]) == report.legacy_title() else str(item["title"])
            )})
            scope = report_output_scope_text(written)
        else:
            scope = str(item["title"]) + "\n" + str(item["statement"])
        points.append(CandidateVerificationPoint(
            candidate_index=index,
            semantic_support="supported",
            future_scope="durable",
            source_use="standing_decision",
            reason="The final title and statement were checked against the source.",
            scope_segments=[CandidateScopeSegment(
                text=scope, source_use="standing_decision", future_scope="durable",
                standalone=True, content_role="claim", source_support="supported",
            )],
            update_meaning_judgment=parsed,
        ))
    point["final_scope_judgment"] = CandidateVerificationDecision(points=points).model_dump(mode="json")
    return point


def _point(title, statement, disposition="add", targets=(), claim_kind="source_report", report=None, **extra):
    point = {
        "disposition": disposition,
        "matched_truth_ids": list(targets),
        "knowledge_items": [{
            "title": title,
            "statement": statement,
            "topic_path": ["reports"],
            "claim_kind": claim_kind,
        }],
        "reason": "Retain the verified account without inventing a topic id.",
        "verified_at": datetime.now(timezone.utc),
    }
    point.update(extra)
    if report is not None or claim_kind != "source_report":
        _seal_point(point, report)
    return point


def _judgment(predecessor: str, successor: str, relationship="same_topic") -> dict:
    return ReportTopicJudgment(
        relationship=relationship,
        predecessor_title=predecessor,
        successor_title=successor,
        basis="The cited account is the same topic, not a title-string match.",
    ).model_dump(mode="json")


def _meaning(statements, conditions=(), undecided=None, relationship="preserves_applicable_meaning", predecessors=()):
    return UpdateMeaningJudgment(
        relationship=relationship,
        predecessor_conditions=list(conditions),
        undecided_state=undecided,
        successor_statements=list(statements),
        predecessor_statements=[statement for statement, _version in predecessors],
        predecessor_versions=[version for _statement, version in predecessors],
        basis="The whole replacement keeps the named condition and undecided state.",
    ).model_dump(mode="json")


def _entry_version(entry) -> str:
    report = entry.source_report.model_dump(mode="json") if entry.source_report is not None else None
    return target_version({
        "title": entry.title,
        "statement": entry.statement,
        "topic_path": list(entry.module_path),
        "source_report": report,
    })


def _scope_decision(scope_text, *, source_use="standing_decision", semantic="supported", support="supported", future="durable"):
    return CandidateVerificationDecision(points=[CandidateVerificationPoint(
        candidate_index=0,
        semantic_support=semantic,
        future_scope=future,
        source_use=source_use,
        reason="The final title and statement were checked against the source.",
        scope_segments=[CandidateScopeSegment(
            text=scope_text,
            source_use=source_use if source_use != "unclear" else "unclear",
            future_scope=future,
            standalone=True,
            content_role="claim",
            source_support=support,
        )],
    )])


async def _backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    await backend.init()
    return backend


async def _write_report(backend, root, report, title):
    source_ref = await _source_for(report, backend)
    candidate = KnowledgeCandidate(
        project_name="demo", candidate_type="memory",
        statement=report.text, source_report=report,
    )
    ids = await record_assimilation_result(
        backend, candidate=candidate,
        point=_point(title, "This lied body must not be stored.", report=report),
        project_root=root, source_refs=[source_ref],
    )
    return candidate, ids[0]


def test_legacy_title_upgrade_is_an_in_place_replacement(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            report = _report()
            _candidate, old_id = await _write_report(backend, tmp_path, report, report.legacy_title())
            stored = await store.get_entry(old_id, project_name="demo")
            assert stored.source_report.topic_title is None
            assert stored.title == report.legacy_title()

            revised = report.model_copy()
            intruder = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=revised.text, source_report=revised,
            )
            with pytest.raises(ValueError, match="topic"):
                await record_assimilation_result(
                    backend, candidate=intruder,
                    point=_point("Widget cache limit", "A lied approval body.", "replace", [old_id]),
                    project_root=tmp_path, source_refs=[await _source_for(revised)],
                )
            assert (await store.get_entry(old_id, project_name="demo")).to_dict() == stored.to_dict()

            judged = _point(
                "Widget cache limit", "A lied approval body.", "replace", [old_id],
                report=revised,
                report_topic_judgment=_judgment(report.legacy_title(), "Widget cache limit"),
                update_meaning_judgment=_meaning(
                    [stored.statement],
                    predecessors=[(stored.statement, _entry_version(stored))],
                ),
            )
            new_ids = await record_assimilation_result(
                backend, candidate=intruder, point=judged,
                project_root=tmp_path, source_refs=[await _source_for(revised, backend)],
            )
            rows = await store.list_entries("demo")
            assert len(rows) == 1
            assert rows[0].id == new_ids[0] != old_id
            assert await store.get_entry(old_id, project_name="demo") is None
            written = rows[0].source_report
            assert written.topic_title == "Widget cache limit"
            assert written.speaker == report.speaker
            assert written.period == report.period
            assert written.session_id == report.session_id
            assert written.source_id == report.source_id
            assert written.text == OLD_BODY
            assert rows[0].statement == written.render_statement()
            assert LIMITATION in rows[0].statement
            assert "lied approval" not in rows[0].statement
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_same_topic_wording_and_unrelated_body_need_a_judgment(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            report = _report(topic_title="Widget cache limit")
            _candidate, old_id = await _write_report(backend, tmp_path, report, "Widget cache limit")
            before = (await store.get_entry(old_id, project_name="demo")).to_dict()

            wording = report.model_copy()
            wording_candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=wording.text, source_report=wording,
            )
            with pytest.raises(ValueError, match="topic|verified account"):
                await record_assimilation_result(
                    backend, candidate=wording_candidate,
                    point=_point("Widget cache policy", "A lied body.", "replace", [old_id]),
                    project_root=tmp_path, source_refs=[await _source_for(wording)],
                )
            stored = await store.get_entry(old_id, project_name="demo")
            judged = _point(
                "Widget cache policy", "A lied body.", "replace", [old_id],
                report=wording,
                report_topic_judgment=_judgment("Widget cache limit", "Widget cache policy"),
                update_meaning_judgment=_meaning(
                    [stored.statement],
                    predecessors=[(stored.statement, _entry_version(stored))],
                ),
            )
            new_ids = await record_assimilation_result(
                backend, candidate=wording_candidate, point=judged,
                project_root=tmp_path, source_refs=[await _source_for(wording, backend)],
            )
            rows = await store.list_entries("demo")
            assert [row.id for row in rows] == new_ids
            assert rows[0].title == "Widget cache policy"
            assert rows[0].source_report.text == OLD_BODY
            assert "lied body" not in rows[0].statement

            same_title = rows[0].source_report.model_copy(update={"text": UNRELATED_BODY})
            same_candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=same_title.text, source_report=same_title,
            )
            current_id = rows[0].id
            current = rows[0].to_dict()
            with pytest.raises(ValueError, match="topic"):
                await record_assimilation_result(
                    backend, candidate=same_candidate,
                    point=_point("Widget cache policy", "Lied.", "replace", [current_id]),
                    project_root=tmp_path, source_refs=[await _source_for(same_title)],
                )
            unrelated = _judgment("Widget cache policy", "Widget cache policy", "unrelated")
            with pytest.raises(ValueError, match="topic"):
                await record_assimilation_result(
                    backend, candidate=same_candidate,
                    point=_point(
                        "Widget cache policy", "Lied.", "replace", [current_id],
                        report_topic_judgment=unrelated,
                    ),
                    project_root=tmp_path, source_refs=[await _source_for(same_title)],
                )
            mismatched = _judgment("Widget cache policy", "Some other successor")
            with pytest.raises(ValueError, match="topic|verified account"):
                await record_assimilation_result(
                    backend, candidate=same_candidate,
                    point=_point(
                        "Widget cache policy", "Lied.", "replace", [current_id],
                        report_topic_judgment=mismatched,
                    ),
                    project_root=tmp_path, source_refs=[await _source_for(same_title)],
                )
            assert (await store.get_entry(current_id, project_name="demo")).to_dict() == current

            other = report.model_copy(update={"speaker": "user", "topic_title": "Widget cache policy"})
            with pytest.raises(ValueError, match="source-report|speaker|topic"):
                await record_assimilation_result(
                    backend,
                    candidate=KnowledgeCandidate(
                        project_name="demo", candidate_type="memory",
                        statement=other.text, source_report=other,
                    ),
                    point=_point(
                        "Widget cache policy", other.text, "replace", [current_id],
                        report_topic_judgment=_judgment("Widget cache policy", "Widget cache policy"),
                    ),
                    project_root=tmp_path, source_refs=[await _source_for(other)],
                )
            assert (await store.get_entry(current_id, project_name="demo")).to_dict() == current
            assert before["source_report"]["text"] == OLD_BODY
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_store_rejects_same_title_unrelated_body_without_a_judgment(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            report = _report(topic_title=None)
            _candidate, old_id = await _write_report(backend, tmp_path, report, report.legacy_title())
            current = await store.get_entry(old_id, project_name="demo")
            before = current.to_dict()
            revised = report.model_copy(update={"text": UNRELATED_BODY})
            successor = current.model_copy(update={
                "id": "replacement-row",
                "statement": revised.render_statement(),
                "source_report": revised,
            })
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=revised.text, source_report=revised,
            )
            with pytest.raises(ValueError, match="topic"):
                await store.apply_current_change(
                    candidate_before=candidate,
                    candidate_after=candidate,
                    decision=AssimilationDecision(
                        project_name="demo", candidate_id=candidate.id, disposition="replace",
                        canonical_truth_ids=[successor.id], predecessor_truth_ids=[current.id],
                        reason="Same generic title must not replace an unrelated body.",
                    ),
                    added_entries=[successor], predecessor_entries=[current],
                    source_refs_by_entry={successor.id: [await _source_for(revised)]},
                )
            assert (await store.get_entry(old_id, project_name="demo")).to_dict() == before
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_authorized_same_title_body_correction_replaces_one_row(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            legacy = _report()
            _candidate, old_id = await _write_report(backend, tmp_path, legacy, legacy.legacy_title())
            revised = legacy.model_copy(update={"text": NEW_BODY})
            revised_source = await _source_for(revised, backend)
            stored = await store.get_entry(old_id, project_name="demo")
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=revised.text, source_report=revised,
            )
            point = _point(
                legacy.legacy_title(), "Lied body.", "replace", [old_id],
                report=revised,
                report_topic_judgment=_judgment(legacy.legacy_title(), legacy.legacy_title()),
                update_meaning_judgment=_meaning(
                    [revised.render_statement()],
                    predecessors=[(stored.statement, _entry_version(stored))],
                ),
            )
            from test_report_single_commit import _independent_report_final
            _independent_report_final(point, candidate_id=candidate.id, old=stored, written=revised, omissions=[])
            assert point["report_preservation_inventory"]["mode"] == "full_revision"
            assert point["update_meaning_judgment"]["report_preservation"]["inventory_complete"]
            ids = await record_assimilation_result(
                backend,
                candidate=candidate,
                point=point,
                project_root=tmp_path, source_refs=[revised_source],
            )
            rows = await store.list_entries("demo")
            assert [row.id for row in rows] == ids
            assert rows[0].id != old_id
            assert rows[0].title == legacy.legacy_title()
            assert rows[0].source_report.topic_title is None
            assert rows[0].source_report.text == NEW_BODY
            assert rows[0].statement == revised.render_statement()
            assert "Lied body" not in rows[0].statement
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_report_multi_output_stays_rejected_until_a_later_conversion(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            report = _report(topic_title="Widget cache limit")
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=report.text, source_report=report,
            )
            point = _point(report.render_title(), "Lied.", claim_kind="source_report")
            point["knowledge_items"].append({
                "title": "Second report output",
                "statement": "Another lied body.",
                "topic_path": ["reports"],
                "claim_kind": "source_report",
            })
            with pytest.raises(ValueError, match="exactly one"):
                await record_assimilation_result(
                    backend, candidate=candidate, point=point,
                    project_root=tmp_path, source_refs=[await _source_for(report)],
                )
            assert not await backend.structured_store.knowledge_store.list_entries("demo")
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_final_scope_binds_support_without_starting_an_executor():
    title = "Widget cache limit"
    statement = "The cache limit remains a standing project decision."
    scope = title + "\n" + statement
    payload = {
        "candidate_id": "candidate-1",
        "disposition": "add",
        "knowledge_items": [{
            "title": title, "statement": statement,
            "topic_path": ["cache"], "claim_kind": "implementation_fact",
        }],
        "targets": [],
    }
    rows = [{
        "candidate_index": 0, "owner_candidate_id": "candidate-1",
        "title": title, "statement": statement, "scope_text": scope,
    }]
    assert bind_final_scope_judgment(rows, _scope_decision(scope)) == {}
    proof = prove_supplied_final_scope(payload=payload, judgment=_scope_decision(scope))
    assert proof == final_scope_proof(payload)
    assert proof.startswith("fsv_")

    undecided = "The cache backend is explicitly undecided."
    undecided_scope = "Cache backend\n" + undecided
    undecided_payload = {
        "candidate_id": "candidate-2",
        "disposition": "add",
        "knowledge_items": [{
            "title": "Cache backend", "statement": undecided,
            "topic_path": ["cache"], "claim_kind": "implementation_fact",
        }],
        "targets": [],
        "undecided_state": "explicitly undecided",
        "update_meaning_judgment": _meaning([undecided], undecided="explicitly undecided"),
    }
    undecided_judgment = _scope_decision(undecided_scope, source_use="explicit_undecided")
    with pytest.raises(ValueError, match="final_update_meaning_incomplete"):
        prove_supplied_final_scope(payload=undecided_payload, judgment=undecided_judgment)
    undecided_judgment.points[0].update_meaning_judgment = UpdateMeaningJudgment.model_validate(
        _meaning([undecided], undecided="explicitly undecided")
    )
    assert prove_supplied_final_scope(
        payload=undecided_payload, judgment=undecided_judgment,
    ).startswith("fsv_")

    false_title = _scope_decision("Other title\n" + statement)
    blocked = bind_final_scope_judgment(rows, false_title)
    assert blocked["candidate-1"] == "final_source_scope_partition_mismatch"
    with pytest.raises(ValueError, match="final knowledge scope"):
        prove_supplied_final_scope(payload=payload, judgment=false_title)

    partial = bind_final_scope_judgment(rows, _scope_decision(scope, semantic="partial"))
    assert partial["candidate-1"] == "final_semantic_support_incomplete"
    inconsistent = bind_final_scope_judgment(
        rows, _scope_decision(scope, support="unsupported"),
    )
    assert inconsistent["candidate-1"] == "final_source_scope_support_inconsistent"

    first = "Keep the signed sample available."
    second = "Keep the thirty-day bound in force."
    two_rows = [
        {"candidate_index": 0, "owner_candidate_id": "point-1", "scope_text": "One\n" + first},
        {"candidate_index": 1, "owner_candidate_id": "point-1", "scope_text": "Two\n" + second},
    ]
    failing = CandidateVerificationDecision(points=[
        _scope_decision("One\n" + first).points[0],
        CandidateVerificationPoint(
            candidate_index=1, semantic_support="partial", future_scope="durable",
            source_use="standing_decision",
            reason="The second output is only partially supported.",
            scope_segments=[CandidateScopeSegment(
                text="Two\n" + second, source_use="standing_decision", future_scope="durable",
                standalone=True, content_role="claim", source_support="supported",
            )],
        ),
    ])
    blocked_point = bind_final_scope_judgment(two_rows, failing)
    deferred = defer_blocked_final_scope(
        {"points": [{
            "candidate_id": "point-1", "disposition": "replace",
            "matched_truth_ids": ["old"], "knowledge_items": [{"title": "One"}, {"title": "Two"}],
        }]},
        blocked_point,
    )
    assert deferred["points"][0]["disposition"] == "defer"
    assert deferred["points"][0]["knowledge_items"] == []
    assert deferred["points"][0]["matched_truth_ids"] == []

    preserved = {
        **payload,
        "retained_conditions": ["signed sample"],
        "knowledge_items": [{
            "title": title,
            "statement": "The cache limit keeps the signed sample available.",
            "topic_path": ["cache"], "claim_kind": "implementation_fact",
        }],
    }
    assert update_meaning_block(preserved) == "final_update_meaning_incomplete"
    with pytest.raises(ValueError, match="final knowledge scope"):
        prove_supplied_final_scope(
            payload=preserved,
            judgment=_scope_decision(title + "\n" + preserved["knowledge_items"][0]["statement"]),
        )
    omitted_replace = {
        "candidate_id": "correction",
        "disposition": "replace",
        "targets": [{
            "id": "current-rule",
            "title": "Cache policy",
            "statement": (
                "Cache TTL is 60 seconds for members; guests remain excluded "
                "and the rollout is undecided."
            ),
            "topic_path": ["cache"],
        }],
        "knowledge_items": [{
            "title": "Cache TTL",
            "statement": "Cache TTL is 120 seconds for members.",
            "topic_path": ["cache"],
            "claim_kind": "design_requirement",
        }],
    }
    assert update_meaning_block(omitted_replace) == "final_update_meaning_incomplete"
    forged = {
        **omitted_replace,
        "targets": [{**omitted_replace["targets"][0], "version": "a" * 64}],
        "update_meaning_judgment": _meaning(
            ["Cache TTL is 120 seconds for members."],
            predecessors=[(omitted_replace["targets"][0]["statement"], "a" * 64)],
        ),
    }
    assert update_meaning_block(forged) is None
    with pytest.raises(ValueError, match="final_update_meaning_incomplete"):
        prove_supplied_final_scope(
            payload=forged,
            judgment=_scope_decision("Cache TTL\nCache TTL is 120 seconds for members."),
        )
    source = inspect.getsource(bind_final_scope_judgment) + inspect.getsource(prove_supplied_final_scope)
    assert "build_semantic_executor" not in source
    assert "subprocess" not in source
    assert "DistillProvider" not in source


def test_whole_update_keeps_conditions_or_writes_nothing(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            fact = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement="The old cache rule kept the signed sample and left the backend explicitly undecided.",
            )
            old_statement = fact.statement
            old_ids = await record_assimilation_result(
                backend, candidate=fact,
                point=_point("Old cache rule", old_statement, claim_kind="implementation_fact"),
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            first = "The cache limit keeps the signed sample available."
            second = "The cache backend stays explicitly undecided."
            old = await store.get_entry(old_ids[0], project_name="demo")
            bound = [(old.statement, _entry_version(old))]
            fact = fact.model_copy(update={"id": fact.id + "-replacement", "status": "pending"})
            bare = _point("Cache limit", first, "replace", old_ids, "implementation_fact")
            bare["knowledge_items"] = [
                {"title": "Cache limit", "statement": first, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
                {"title": "Cache backend", "statement": second, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
            ]
            with pytest.raises(ValueError, match="condition or undecided"):
                await record_assimilation_result(
                    backend, candidate=fact, point=bare,
                    project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
                )
            assert [row.id for row in await store.list_entries("demo")] == old_ids
            dropped = _point(
                "Ignored", "unused", "replace", old_ids, "implementation_fact",
                retained_conditions=["signed sample"],
                undecided_state="explicitly undecided",
            )
            dropped["knowledge_items"] = [
                {"title": "Cache limit", "statement": first, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
                {"title": "Cache backend", "statement": "The backend was chosen.", "topic_path": ["cache"], "claim_kind": "implementation_fact"},
            ]
            dropped["update_meaning_judgment"] = _meaning(
                [first, "The backend was chosen."],
                ["signed sample"],
                "explicitly undecided",
                predecessors=bound,
            )
            with pytest.raises(ValueError, match="condition or undecided"):
                await record_assimilation_result(
                    backend, candidate=fact, point=dropped,
                    project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
                )
            assert [row.id for row in await store.list_entries("demo")] == old_ids

            partial_judgment = _point(
                "Ignored", "unused", "replace", old_ids, "implementation_fact",
                retained_conditions=["signed sample"],
                undecided_state="explicitly undecided",
            )
            partial_judgment["knowledge_items"] = [
                {"title": "Cache limit", "statement": first, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
                {"title": "Cache backend", "statement": second, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
            ]
            partial_judgment["update_meaning_judgment"] = _meaning(
                [first], ["signed sample"], "explicitly undecided", predecessors=bound,
            )
            with pytest.raises(ValueError, match="condition or undecided"):
                await record_assimilation_result(
                    backend, candidate=fact, point=partial_judgment,
                    project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
                )
            assert [row.id for row in await store.list_entries("demo")] == old_ids

            kept = partial_judgment
            kept["update_meaning_judgment"] = _meaning(
                [first, second], ["signed sample"], "explicitly undecided", predecessors=bound,
            )
            _seal_point(kept)
            new_ids = await record_assimilation_result(
                backend, candidate=fact, point=kept,
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            assert await store.get_entry(old_ids[0], project_name="demo") is None
            rows = await store.list_entries("demo")
            assert {row.id for row in rows} == set(new_ids)
            assert len(rows) == 2
            combined = "\n".join(row.statement for row in rows)
            assert "signed sample" in combined
            assert "explicitly undecided" in combined
        finally:
            await backend.close()

        fresh = LocalMemoryBackend(tmp_path / "data")
        await fresh.init()
        try:
            reopened = await fresh.structured_store.knowledge_store.list_entries("demo")
            assert {row.id for row in reopened} == set(new_ids)
            by_sample = await search_current_knowledge(
                fresh, query="signed sample", project_name="demo", limit=10,
            )
            by_state = await search_current_knowledge(
                fresh, query="explicitly undecided", project_name="demo", limit=10,
            )
            assert {row.id for row in by_sample} | {row.id for row in by_state} == set(new_ids)
            assert by_sample and by_state
        finally:
            await fresh.close()

    asyncio.run(exercise())


def test_predecessor_snapshot_mismatch_does_not_write(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            fact = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement="The retention window is seven days.",
            )
            ids = await record_assimilation_result(
                backend, candidate=fact,
                point=_point("Retention window", fact.statement, claim_kind="procedure"),
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            current = await store.get_entry(ids[0], project_name="demo")
            stale = current.model_copy(update={"statement": "The retention window is thirty days."})
            replacement = fact.model_copy(update={"id": fact.id + "-replacement", "status": "pending"})
            with pytest.raises(CanonicalTransactionPreconditionError):
                await record_assimilation_result(
                    backend, candidate=replacement,
                    point=_point(
                        "Retention window", "The retention window is thirty days.",
                        "replace", ids, "procedure",
                    ),
                    project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
                    expected_predecessor_entries=[stale],
                )
            assert (await store.get_entry(ids[0], project_name="demo")).statement == fact.statement
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_committed_write_is_reused_after_a_downstream_gap(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            store = backend.structured_store.knowledge_store
            fact = KnowledgeCandidate(
                id="candidate-committed", project_name="demo", candidate_type="memory",
                statement="The service keeps only verified cache entries.",
            )
            point = _point(
                "Verified cache entries", fact.statement, claim_kind="implementation_fact",
            )
            point["candidate_id"] = fact.id
            ids = await record_assimilation_result(
                backend, candidate=fact, point=point,
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            recovered = await recover_committed_assimilation(
                backend, project_name="demo", project_root=tmp_path, points=[point],
            )
            assert recovered == ids
            again = await record_assimilation_result(
                backend, candidate=fact, point=point,
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            assert again == ids
            assert [row.id for row in await store.list_entries("demo")] == ids
            shared = await commit_shared_knowledge_change(
                backend, candidate=fact, point=point,
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            assert shared["truth_ids"] == ids
            assert shared["truth_change"] == "add"
        finally:
            await backend.close()

        fresh = LocalMemoryBackend(tmp_path / "data")
        await fresh.init()
        try:
            found = await search_current_knowledge(
                fresh, query="verified cache", project_name="demo", limit=10,
            )
            assert [row.id for row in found] == ids
        finally:
            await fresh.close()

    asyncio.run(exercise())


def test_missing_source_does_not_write(tmp_path, monkeypatch):
    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            root = tmp_path / "project"
            root.mkdir()
            store = backend.structured_store.knowledge_store
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement="The service retains only verified current cache entries.",
            )
            await store.save_candidate(candidate)
            digest = hashlib.sha256(b"absent").hexdigest()
            await store.save_evidence(KnowledgeEvidence(
                project_name="demo", candidate_id=candidate.id,
                evidence_basis="repository", verification_outcome="verified",
                verification_refs=[EvidenceRef(
                    kind="repository", locator="missing-policy.md", content_sha256=digest,
                )],
                verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
            ))
            with pytest.raises(ValueError, match="source unavailable"):
                await record_assimilation_result(
                    backend, candidate=candidate,
                    point=_point(
                        "Current cache policy", candidate.statement,
                        claim_kind="implementation_fact",
                    ),
                    project_root=root, source_refs=[_repo_ref(root)],
                )
            assert not await store.list_entries("demo")
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_durable_admission_rejects_session_scope_and_keeps_explicit_unknown(tmp_path, monkeypatch):
    assert content_admission_allows_durable_write(SimpleNamespace(
        verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
    ))
    assert not content_admission_allows_durable_write(SimpleNamespace(
        verification_reason_codes=[
            "autonomous_final_scope_required", "source_use_task_context", "future_utility_verified",
        ],
    ))
    assert content_admission_allows_durable_write(SimpleNamespace(
        verification_reason_codes=[
            "autonomous_final_scope_required", "source_use_explicit_undecided",
            "future_scope_durable", "future_utility_verified",
        ],
    ))

    async def exercise():
        backend = await _backend(tmp_path, monkeypatch)
        try:
            root = tmp_path / "project"
            root.mkdir()
            text = "Adopt the explicit local cache policy for this service."
            path = root / "policy.txt"
            path.write_text(text, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            store = backend.structured_store.knowledge_store
            specs = {
                "session-only": [
                    "semantic_support_verified", "future_utility_verified",
                    "autonomous_final_scope_required", "future_scope_session_only",
                ],
                "undecided": [
                    "semantic_support_verified", "future_utility_verified",
                    "autonomous_final_scope_required", "source_use_explicit_undecided",
                    "future_scope_durable",
                ],
                "legacy": ["semantic_support_verified", "future_utility_verified"],
            }
            for name, codes in specs.items():
                candidate = KnowledgeCandidate(
                    id=name, project_name="demo", candidate_type="memory", statement=text,
                )
                await store.save_candidate(candidate)
                await store.save_evidence(KnowledgeEvidence(
                    project_name="demo", candidate_id=candidate.id, distill_job_id="job-" + name,
                    evidence_basis="repository", verification_outcome="verified",
                    verification_refs=[EvidenceRef(
                        kind="repository", locator="policy.txt", content_sha256=digest,
                    )],
                    verification_reason_codes=codes,
                ))
            prepared = await prepare_separated_assimilation(
                backend, project_name="demo", project_root=str(root),
                candidate_ids=list(specs),
            )
            automatic = {point["candidate_id"]: point for point in prepared.automatic_points}
            assert automatic["session-only"]["disposition"] == "no_write"
            assert "durable future use" in automatic["session-only"]["reason"]
            assert "undecided" in prepared.eligible_candidate_ids
            assert "legacy" in prepared.eligible_candidate_ids
            assert prepared.manifest["truth_target_discovery"]["absence_proved"] is False
            assert prepared.manifest["truth_target_discovery"]["status"] == "complete"
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_truth_target_discovery_does_not_prove_absence():
    incomplete = describe_truth_target_discovery(
        owner="demo", offered_count=1, current_count=3,
        unmatched_candidate_ids=["candidate-gap"], versions={"T1": "abc"},
    )
    assert incomplete["status"] == "incomplete"
    assert incomplete["absence_proved"] is False
    assert incomplete["unmatched_candidate_ids"] == ["candidate-gap"]
    assert incomplete["unmatched_meaning"] == "lexical_overlap_miss_is_not_proof_of_no_related_knowledge"
    complete = describe_truth_target_discovery(
        owner="demo", offered_count=3, current_count=3,
        unmatched_candidate_ids=[], versions={},
    )
    assert complete["status"] == "complete"
    assert complete["absence_proved"] is False


@pytest.fixture
def manual_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_args: MergedConfig())
    monkeypatch.setattr(
        session_inventory, "build_inspection_adapter",
        lambda client: CursorAdapter(None, projects_dir=projects),
    )
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "fixture-runtime")

    def forbidden(*_args, **_kwargs):
        pytest.fail("A native executor must never run during this isolated probe")

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.registry.build_semantic_executor", forbidden,
    )

    def write(name, text="Adopt the explicit local cache policy."):
        path = projects / "bucket" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"role": "user", "cwd": str(root), "message": {"content": [{"type": "text", "text": text}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Hello, ready to help."}]}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        return path

    yield backend, root, write
    asyncio.run(backend.close())


def _prepare(root):
    return tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root),
        batch_sessions=tool_inspect_sessions(str(root), clients=["cursor"])["sessions"],
    )


async def _repository_candidate(backend, root, job_id, statement):
    path = root / "policy.txt"
    path.write_text(statement, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    candidate = KnowledgeCandidate(
        project_name="project", candidate_type="memory", statement=statement,
    )
    store = backend.structured_store.knowledge_store
    await store.save_candidate(candidate)
    await store.save_evidence(KnowledgeEvidence(
        project_name="project", candidate_id=candidate.id, distill_job_id=job_id,
        evidence_basis="repository", verification_outcome="verified",
        verification_refs=[EvidenceRef(
            kind="repository", locator="policy.txt", content_sha256=digest,
        )],
        verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
    ))
    return candidate


def test_paused_and_stopped_batches_block_the_shared_precommit(manual_backend):
    backend, root, write = manual_backend
    write("a")
    packet = _prepare(root)
    assert packet["success"], packet
    paused = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root),
        batch_id=packet["batch_id"], pause=True,
    )
    assert paused["status"] == "paused", paused

    async def while_paused():
        unrelated = KnowledgeCandidate(
            project_name="project", candidate_type="memory",
            statement="An unrelated standalone fact stays writable.",
        )
        unrelated_ids = await record_assimilation_result(
            backend, candidate=unrelated,
            point=_point(
                "Standalone fact", unrelated.statement, claim_kind="implementation_fact",
            ),
            project_root=root, source_refs=[_repo_ref(root)],
        )
        held = await _repository_candidate(
            backend, root, packet["distill_job_id"],
            "The service retains only verified current cache entries.",
        )
        with pytest.raises(ValueError, match="batch_paused"):
            await record_assimilation_result(
                backend, candidate=held,
                point=_point(
                    "Current cache policy", held.statement, claim_kind="implementation_fact",
                ),
                project_root=root, source_refs=[_repo_ref(root)],
            )
        await delete_current_knowledge(
            backend, project_name="project", target_knowledge_ids=unrelated_ids,
        )
        assert not await backend.structured_store.knowledge_store.list_entries("project")
        return held

    held = asyncio.run(while_paused())
    continued = tool_handlers.tool_prepare_session_distill(
        project_name="project", project_root=str(root),
        batch_id=packet["batch_id"], continue_batch=True,
    )
    assert continued.get("status") != "paused", continued

    async def after_continue():
        held.status = "pending"
        ids = await record_assimilation_result(
            backend, candidate=held,
            point=_point(
                "Current cache policy", held.statement, claim_kind="implementation_fact",
            ),
            project_root=root, source_refs=[_repo_ref(root)],
        )
        rows = await backend.structured_store.knowledge_store.list_entries("project")
        assert [row.id for row in rows] == ids

    asyncio.run(after_continue())


def test_stopped_batch_blocks_the_shared_precommit(manual_backend):
    backend, root, write = manual_backend
    write("a")
    packet = _prepare(root)
    assert packet["success"], packet
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    if not job.retain_source:
        backend.transcript_store.retain_source(job.id)
    batch_store = ManualBatchStore(backend.data_dir)
    manifest = batch_store.load(packet["batch_id"], "project", str(root))
    reference = next(
        ref for ref, job_id in manifest["bindings"].items() if job_id == packet["distill_job_id"]
    )
    batch_store.record_failure(
        packet["batch_id"], "project", manifest["project_root"], reference,
        "completion_verification_failed", stop_batch=True,
    )

    async def while_stopped():
        stopped = await _repository_candidate(
            backend, root, packet["distill_job_id"],
            "A stopped batch must not publish this cache rule.",
        )
        with pytest.raises(ValueError, match="manual_batch_stopped"):
            await record_assimilation_result(
                backend, candidate=stopped,
                point=_point(
                    "Stopped cache rule", stopped.statement, claim_kind="implementation_fact",
                ),
                project_root=root, source_refs=[_repo_ref(root)],
            )
        assert not await backend.structured_store.knowledge_store.list_entries("project")

    asyncio.run(while_stopped())


def _verification_result(points):
    return ProviderResult(
        decision=CandidateVerificationDecision.model_validate({"points": points}),
        provider="fake-final-scope",
        model="deterministic-test",
        duration_seconds=0.01,
        input_sha256="a" * 64,
        response_sha256="b" * 64,
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        event_count=1,
    )


def test_verifier_receives_the_whole_update_and_a_missing_verdict_defers(tmp_path, monkeypatch):
    """The final verifier, not the assimilator, judges preservation."""

    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def seed():
        backend = await _backend(tmp_path, monkeypatch)
        root = tmp_path / "project"
        root.mkdir()
        text = "The old cache rule kept the signed sample and left the backend explicitly undecided."
        path = root / "policy.txt"
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ref = ProjectKnowledgeSourceRef(
            label="policy", kind="repository", digest=digest, target=path.as_uri(),
        )
        store = backend.structured_store.knowledge_store
        candidate = KnowledgeCandidate(
            project_name="demo", candidate_type="memory", statement=text,
        )
        old_ids = await record_assimilation_result(
            backend, candidate=candidate,
            point=_point("Old cache rule", text, claim_kind="implementation_fact"),
            project_root=root, source_refs=[ref],
        )
        refine = KnowledgeCandidate(
            id="refine-candidate", project_name="demo", candidate_type="memory",
            statement="The provider proposed a two-part replacement.",
        )
        await store.save_candidate(refine)
        await store.save_evidence(KnowledgeEvidence(
            project_name="demo", candidate_id=refine.id, evidence_basis="repository",
            verification_outcome="verified",
            verification_refs=[EvidenceRef(
                kind="repository", locator="policy.txt", content_sha256=digest,
            )],
            verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
        ))
        current = await store.get_entry(old_ids[0], project_name="demo")
        return backend, root, text, digest, current

    backend, root, text, digest, current = asyncio.run(seed())
    try:
        first = "The cache limit keeps the signed sample available."
        second = "The cache backend stays explicitly undecided."
        prepared = SeparatedPreparedAssimilation(
            project_name="demo",
            project_root=str(root),
            candidate_ids=("refine-candidate",),
            eligible_candidate_ids=("refine-candidate",),
            automatic_points=(),
            answer_status_by_candidate={"refine-candidate": "ANSWERED"},
            truth_by_handle={"T1": current.id},
            manifest={"current_truth": [{
                "handle": "T1",
                "title": current.title,
                "statement": current.statement,
                "topic_path": list(current.module_path),
                "source_report": None,
            }]},
        )
        assimilator_judgment = _meaning(
            [first],
            predecessors=[(current.statement, "f" * 64)],
        )
        plan = {"points": [{
            "candidate_id": "refine-candidate",
            "disposition": "replace",
            "matched_truth_ids": [current.id],
            "knowledge_items": [
                {"title": "Cache limit", "statement": first, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
                {"title": "Cache backend", "statement": second, "topic_path": ["cache"], "claim_kind": "implementation_fact"},
            ],
            "reason": "Replace the old cache rule with both surviving parts.",
            "update_meaning_judgment": assimilator_judgment,
            "retained_conditions": [],
        }]}
        original_manifest = {"session_context": [], "candidates": [{
            "sources": [{"kind": "repository", "content_sha256": digest, "content": text}],
        }]}

        class _Provider:
            name = "fake-final-scope"

            def __init__(self, mode: str) -> None:
                self.mode = mode
                self.manifests: list[dict] = []

            def verify(self, manifest, *, runtime_dir, heartbeat=None):
                del runtime_dir, heartbeat
                self.manifests.append(manifest)
                context = manifest["candidates"][0]["update_context"]
                judgment = None
                if self.mode != "missing":
                    relationship = {
                        "unclear": "unclear",
                        "drops": "drops_applicable_meaning",
                        "preserves": "preserves_applicable_meaning",
                    }[self.mode]
                    judgment = {
                        "relationship": relationship,
                        "predecessor_conditions": ["signed sample"] if self.mode == "preserves" else [],
                        "predecessor_statements": [item["statement"] for item in context["predecessors"]],
                        "predecessor_versions": [item["version"] for item in context["predecessors"]],
                        "successor_statements": [item["statement"] for item in context["successors"]],
                        "undecided_state": "explicitly undecided" if self.mode == "preserves" else None,
                        "basis": "The whole predecessor and successor set was judged together.",
                    }
                points = []
                for row in manifest["candidates"]:
                    point = {
                        "candidate_index": row["candidate_index"],
                        "semantic_support": "supported",
                        "future_scope": "durable",
                        "source_use": "standing_decision",
                        "reason": "Each output sentence is supported by the reopened source.",
                        "scope_segments": [{
                            "text": row["scope_text"],
                            "source_use": "standing_decision",
                            "future_scope": "durable",
                            "standalone": True,
                            "content_role": "claim",
                            "source_support": "supported",
                        }],
                    }
                    if judgment is not None:
                        point["update_meaning_judgment"] = judgment
                    points.append(point)
                return _verification_result(points)

        def run(mode: str):
            provider = _Provider(mode)
            _result, updated = _verify_final_knowledge_scope(
                provider,
                backend=backend,
                prepared=prepared,
                plan=plan,
                original_manifest=original_manifest,
                governed_candidate_ids=["refine-candidate"],
                runtime_dir=tmp_path,
                heartbeat=None,
            )
            return provider, updated

        missing, missing_plan = run("missing")
        context = missing.manifests[0]["candidates"][0]["update_context"]
        assert context["disposition"] == "replace"
        assert context["predecessors"][0]["statement"] == current.statement
        assert context["predecessors"][0]["version"]
        assert [item["statement"] for item in context["successors"]] == [first, second]
        assert context["proposed_update_meaning_judgment"] == assimilator_judgment
        assert missing.manifests[0]["update_contexts"] == [context]
        assert all(row["update_context"] == context for row in missing.manifests[0]["candidates"])
        prompt = _build_verification_prompt(missing.manifests[0])
        assert current.statement in prompt
        assert "proposed_update_meaning_judgment is untrusted input" in prompt
        assert "build_semantic_executor" not in inspect.getsource(_verify_final_knowledge_scope)
        assert missing_plan["points"][0]["disposition"] == "defer"
        assert missing_plan["points"][0]["knowledge_items"] == []
        assert "final_update_meaning_incomplete" in missing_plan["points"][0]["reason"]

        for mode in ("unclear", "drops"):
            _provider, updated = run(mode)
            assert updated["points"][0]["disposition"] == "defer"
            assert updated["points"][0]["knowledge_items"] == []
            assert "final_update_meaning_incomplete" in updated["points"][0]["reason"]

        kept_provider, kept = run("preserves")
        point = kept["points"][0]
        assert point["disposition"] == "replace"
        assert point["update_meaning_judgment"]["relationship"] == "preserves_applicable_meaning"
        assert point["update_meaning_judgment"]["successor_statements"] == [first, second]
        assert point["update_meaning_judgment"]["predecessor_statements"] == [current.statement]
        assert point["update_meaning_judgment"] != assimilator_judgment
        assert point["retained_conditions"] == ["signed sample"]
        assert point["undecided_state"] == "explicitly undecided"
        assert kept_provider.manifests[0]["candidates"][0]["update_context"]["predecessors"][0]["version"] == (
            point["update_meaning_judgment"]["predecessor_versions"][0]
        )
    finally:
        asyncio.run(backend.close())
