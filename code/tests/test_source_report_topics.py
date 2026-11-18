"""Topic titles stay independent inside one source account.

Isolated SQLite and fakes only. No provider, hook, or live store.
"""

import asyncio
import json
from copy import deepcopy

import pytest
from test_report_account_identity import report_judgment
from test_shared_write_core import _source_for as native_source_for, _point as judged_point, _repo_ref

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.provider import _assimilation_manifest_packet
from harness_mem.commands.dream_assimilation import dream_scope_text
from harness_mem.commands.knowledge_assimilation import (
    record_assimilation_result,
    resolve_separated_review,
)
from harness_mem.commands.separated_assimilation import (
    admit_separated_candidate,
    apply_separated_assimilation,
    final_scope_payload,
    final_scope_proof,
    prepare_separated_assimilation,
    validate_separated_assimilation_decision,
)
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision as StoreDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


QUALIFIER = "only when the signed sample remains available"
ZEPHYR = (
    "Zephyrlattice stays diagnostic " + QUALIFIER + ", and it is not production approval."
)
QUILLON = (
    "Quillonvane keeps the archive boundary " + QUALIFIER + ", without granting rollout."
)
LIMITATION = "not independently established current fact or user approval"


def _legacy_report(**updates):
    payload = {
        "speaker": "assistant",
        "period": "that session (date unknown)",
        "session_id": "discussion-1",
        "source_id": "source-1",
        "source_revision": "revision-1",
        "exchange_indexes": [1],
        "text": "In the Iris discussion, the observed sample was not rollout evidence.",
    }
    payload.update(updates)
    return SourceReport(**payload)


def _source_for(report: SourceReport) -> ProjectKnowledgeSourceRef:
    exchange = report.exchange_indexes[0]
    return ProjectKnowledgeSourceRef(
        label="Retained source",
        kind="source_report",
        digest="a" * 64,
        target=(
            "file:///fixture/transcripts.sqlite"
            f"#source_id={report.source_id}&source_revision={report.source_revision}"
            f"&exchange={exchange}&role={report.speaker}"
        ),
    )


def _point(title, statement, disposition="add", targets=(), claim_kind="source_report"):
    return {
        "disposition": disposition,
        "matched_truth_ids": list(targets),
        "knowledge_items": [{
            "title": title,
            "statement": statement,
            "topic_path": ["reports"],
            "claim_kind": claim_kind,
        }],
        "reason": "Retain the attributed report and its qualifier.",
    }


def test_old_report_format_roundtrips_and_keeps_the_generic_title():
    raw = {
        "speaker": "user",
        "period": "that session (date unknown)",
        "session_id": "old-session",
        "source_id": "old-source",
        "source_revision": "old-revision",
        "exchange_indexes": [2, 1],
        "text": "The old account kept its qualifier and no topic title.",
    }
    report = SourceReport.model_validate(raw)
    assert report.topic_title is None
    assert "topic_title" not in report.model_dump(mode="json")
    assert report.render_title() == report.legacy_title()
    assert "source-session timestamp" in report.render_title()
    assert report.exchange_indexes == [1, 2]
    entry = KnowledgeEntry(
        project_name="demo",
        module_path=["reports"],
        title=report.render_title(),
        statement=report.render_statement(),
        source_report=report,
    )
    payload = entry.to_dict()
    assert "topic_title" not in payload["source_report"]
    restored = KnowledgeEntry.from_dict(payload)
    assert restored.to_dict() == payload
    assert restored.title == report.legacy_title()
    assert restored.statement == report.render_statement()
    assert dream_scope_text(restored) == report.text

    titled = report.model_copy(update={"topic_title": "Old account qualifier"})
    titled_entry = KnowledgeEntry(
        project_name="demo",
        module_path=["reports"],
        title=titled.render_title(),
        statement=titled.render_statement(),
        source_report=titled,
    )
    assert titled_entry.title == "Old account qualifier"
    assert dream_scope_text(titled_entry) == titled.text
    assert LIMITATION in titled_entry.statement


def test_legacy_write_omits_topic_title(tmp_path):
    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            report = _legacy_report()
            source = await native_source_for(report, backend)
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=report.text, source_report=report,
            )
            ids = await record_assimilation_result(
                backend, candidate=candidate,
                point=judged_point(report.legacy_title(), "Unchecked replacement body.", report=report),
                project_root=tmp_path, source_refs=[source],
            )
            row = await backend.structured_store.knowledge_store.get_entry(ids[0], project_name="demo")
            assert row.source_report == report
            assert "topic_title" not in row.to_dict()["source_report"]
            assert row.title == report.legacy_title()
            assert "Unchecked replacement body" not in row.statement
            assert LIMITATION in row.statement
            return row.id
        finally:
            await backend.close()

    entry_id = asyncio.run(exercise())
    async def reopen():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            row = await backend.structured_store.knowledge_store.get_entry(entry_id, project_name="demo")
            assert row.title.startswith("Source report — ")
            assert row.source_report.topic_title is None
            assert row.source_report.speaker == "assistant"
            assert row.source_report.period == "that session (date unknown)"
        finally:
            await backend.close()
    asyncio.run(reopen())


def _capture(root, assistant):
    rows = [{"type": "session_meta", "payload": {
        "id": "native-report", "timestamp": "2024-06-01T02:03:04Z", "cwd": str(root),
    }}]
    for role, text in [("user", "Review the diagnostic sample only."), ("assistant", assistant)]:
        rows.append({"type": "response_item", "payload": {
            "type": "message", "role": role, "turn_id": "turn-1",
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        }})
    path = root / "native-report.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


async def _admit(backend, root, candidate_id, statement):
    native = root / "native-report.jsonl"
    adapter = CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive", project_root=root)
    sync = await adapter.sync_session(native, "native-report", project_name="demo")
    rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
    window = render_distill_exchange_windows(rendering, [1])[0]
    candidate, _replay = await admit_separated_candidate(
        backend, candidate_id=candidate_id, project_name="demo", candidate_type="memory",
        statement=statement, distill_job_id=sync.distill_job_id,
        evidence_basis="source_report", verification_outcome="verified",
        verification_refs=[{"kind": "source_report", "exchange_index": 1, "role": "assistant",
                            "content_sha256": window["content_sha256"]}],
        verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
    )
    return candidate


def test_same_session_topics_stay_independent_after_reopen(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    _capture(root, ZEPHYR)

    async def publish(backend, candidate, title):
        result = await resolve_separated_review(
            backend, candidate_id=candidate.id, disposition="add",
            reason="Retain this source topic without replacing the other one.",
            knowledge_items=[{
                "title": title, "statement": "This unchecked body must not replace the report.",
                "topic_path": ["reports"], "claim_kind": "implementation_fact",
            }],
            project_root=root, expected_project_name="demo",
            final_scope_judgment=report_judgment(candidate.source_report, title),
        )
        return result["canonical_truth_ids"][0]

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            first = await _admit(backend, root, "zephyr-topic", ZEPHYR)
            second = await _admit(backend, root, "quillon-topic", QUILLON)
            assert first.source_report.session_id == second.source_report.session_id
            assert first.source_report.source_id == second.source_report.source_id
            zephyr_id = await publish(backend, first, "Zephyrlattice diagnostic limit")
            quillon_id = await publish(backend, second, "Quillonvane archive limit")
            intruder = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=second.statement, source_report=second.source_report,
            )
            with pytest.raises(ValueError, match="topic"):
                await record_assimilation_result(
                    backend, candidate=intruder,
                    point=_point("Quillonvane archive limit", QUILLON, "replace", [zephyr_id]),
                    project_root=root, source_refs=[_source_for(second.source_report)],
                )
            return zephyr_id, quillon_id
        finally:
            await backend.close()

    zephyr_id, quillon_id = asyncio.run(exercise())

    async def reopen():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            zephyr_rows = await search_current_knowledge(
                backend, query="Zephyrlattice", project_name="demo", limit=100,
            )
            quillon_rows = await search_current_knowledge(
                backend, query="Quillonvane", project_name="demo", limit=100,
            )
            assert [row.id for row in zephyr_rows] == [zephyr_id]
            assert [row.id for row in quillon_rows] == [quillon_id]
            for row, text, title, speaker in (
                (zephyr_rows[0], ZEPHYR, "Zephyrlattice diagnostic limit", "assistant"),
                (quillon_rows[0], QUILLON, "Quillonvane archive limit", "assistant"),
            ):
                report = row.source_report
                assert report.speaker == speaker
                assert report.period == "2024-06-01T02:03:04Z"
                assert report.session_id == zephyr_rows[0].source_report.session_id
                assert report.source_id == zephyr_rows[0].source_report.source_id
                assert report.text == text
                assert row.title == title == report.render_title()
                assert QUALIFIER in row.statement
                assert LIMITATION in row.statement
                assert "unchecked body" not in row.statement.casefold()
            assert zephyr_rows[0].source_report.source_revision == quillon_rows[0].source_report.source_revision
        finally:
            await backend.close()
    asyncio.run(reopen())


def test_cross_account_and_fact_rewrites_are_rejected(tmp_path):
    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            store = backend.structured_store.knowledge_store
            report = _legacy_report(text=ZEPHYR)
            source = await native_source_for(report, backend)
            candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=report.text, source_report=report,
            )
            ids = await record_assimilation_result(
                backend, candidate=candidate,
                point=judged_point("Zephyrlattice diagnostic limit", "A fact body that must not stick.", report=report),
                project_root=tmp_path, source_refs=[source],
            )
            current = await store.get_entry(ids[0], project_name="demo")
            before = current.to_dict()

            other_speaker = report.model_copy(update={"speaker": "user", "topic_title": None})
            intruder = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=other_speaker.text, source_report=other_speaker,
            )
            with pytest.raises(ValueError, match="source-report"):
                await record_assimilation_result(
                    backend, candidate=intruder,
                    point=_point("Zephyrlattice diagnostic limit", ZEPHYR, "replace", ids),
                    project_root=tmp_path, source_refs=[_source_for(other_speaker)],
                )

            fact = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement="The rollout was independently approved.",
            )
            fact_source = ProjectKnowledgeSourceRef(
                label="fixture", kind="repository", digest="b" * 64,
                target=(tmp_path / "fixture.txt").as_uri(),
            )
            fact_ids = await record_assimilation_result(
                backend, candidate=fact,
                point=judged_point("Approved fact", fact.statement, claim_kind="implementation_fact"),
                project_root=tmp_path, source_refs=[_repo_ref(tmp_path)],
            )
            fact = fact.model_copy(update={"id": fact.id + "-rewrite", "status": "pending"})
            candidate = candidate.model_copy(update={"id": candidate.id + "-rewrite", "status": "pending"})
            with pytest.raises(ValueError, match="source-report|authority|boundary"):
                await record_assimilation_result(
                    backend, candidate=fact,
                    point=_point("Approved fact", fact.statement, "replace", ids, "implementation_fact"),
                    project_root=tmp_path, source_refs=[fact_source],
                )
            with pytest.raises(ValueError, match="source-report|authority|boundary"):
                await record_assimilation_result(
                    backend, candidate=candidate,
                    point=_point("Zephyrlattice diagnostic limit", ZEPHYR, "replace", fact_ids),
                    project_root=tmp_path, source_refs=[_source_for(report)],
                )

            swapped = current.model_copy(update={
                "id": "other-topic",
                "title": "Quillonvane archive limit",
                "source_report": report.model_copy(update={
                    "topic_title": "Quillonvane archive limit", "text": QUILLON,
                }),
            })
            swapped = swapped.model_copy(update={
                "statement": swapped.source_report.render_statement(),
                "title": swapped.source_report.render_title(),
            })
            swapped_candidate = KnowledgeCandidate(
                project_name="demo", candidate_type="memory",
                statement=swapped.source_report.text, source_report=swapped.source_report,
            )
            with pytest.raises(ValueError, match="topic"):
                await store.apply_current_change(
                    candidate_before=swapped_candidate,
                    candidate_after=swapped_candidate,
                    decision=StoreDecision(
                        project_name="demo", candidate_id=swapped_candidate.id,
                        disposition="replace", canonical_truth_ids=[swapped.id],
                        predecessor_truth_ids=[current.id],
                        reason="Same account must not replace another topic.",
                    ),
                    added_entries=[swapped], predecessor_entries=[current],
                    source_refs_by_entry={swapped.id: [_source_for(swapped.source_report)]},
                )
            assert (await store.get_entry(ids[0], project_name="demo")).to_dict() == before
        finally:
            await backend.close()
    asyncio.run(exercise())


def test_unchecked_title_or_body_cannot_bypass_final_scope_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    _capture(root, ZEPHYR)

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            candidate = await _admit(backend, root, "verified-report", ZEPHYR)
            prepared = await prepare_separated_assimilation(
                backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id],
            )
            decision = AssimilationDecision.model_validate({"points": [{
                "candidate_id": candidate.id, "disposition": "add",
                "knowledge_items": [{
                    "title": "Zephyrlattice diagnostic limit",
                    "statement": "The user approved the production rollout.",
                    "topic_path": ["reports"], "claim_kind": "implementation_fact",
                }],
                "reason": "Keep the verified topic and its source limitation.",
            }]})
            plan = validate_separated_assimilation_decision(prepared, decision)
            plan["points"][0]["final_scope_judgment"] = report_judgment(candidate.source_report, "Zephyrlattice diagnostic limit")
            proof = final_scope_proof(final_scope_payload(prepared, plan["points"][0]))
            store = backend.structured_store.knowledge_store
            evidence = (await store.list_evidence(candidate.id))[0]
            evidence.verification_reason_codes = [
                *evidence.verification_reason_codes, "autonomous_final_scope_required", proof,
            ]
            await store.save_evidence(evidence)

            evil = deepcopy(plan)
            evil["points"][0]["knowledge_items"][0]["title"] = "Unchecked production approval"
            evil["points"][0]["knowledge_items"][0]["statement"] = "The user approved the production rollout."
            with pytest.raises(ValueError, match="final knowledge scope proof"):
                await apply_separated_assimilation(
                    backend, project_name="demo", project_root=str(root),
                    candidate_ids=[candidate.id], plan=evil,
                )
            assert not await store.list_entries("demo")

            lied = deepcopy(plan)
            lied["points"][0]["knowledge_items"][0]["statement"] = "The user approved the production rollout."
            await apply_separated_assimilation(
                backend, project_name="demo", project_root=str(root),
                candidate_ids=[candidate.id], plan=lied,
            )
            rows = await store.list_entries("demo")
            assert len(rows) == 1
            row = rows[0]
            assert row.title == "Zephyrlattice diagnostic limit"
            assert row.source_report.topic_title == row.title
            assert row.statement == row.source_report.render_statement()
            assert QUALIFIER in row.statement and LIMITATION in row.statement
            assert "approved the production rollout" not in row.statement
            assert row.source_report.speaker == "assistant"
            assert row.source_report.period == "2024-06-01T02:03:04Z"
        finally:
            await backend.close()
    asyncio.run(exercise())


def test_topic_title_is_part_of_source_title_verification():
    rows = []
    for index in range(12):
        report = SourceReport(
            speaker="assistant" if index % 2 else "user",
            period="unknown source-session timestamp",
            session_id=f"session-{index % 2}",
            source_id=f"source-{index % 2}",
            source_revision=f"sha256:revision-{index % 2}",
            exchange_indexes=[1, 3],
            text=f"Bounded account {index} kept its qualifier and was not approval. " + ("detail " * 40),
            topic_title=f"Topic {index} boundary",
        )
        rows.append({
            "handle": f"T{index}", "kind": "knowledge_entry",
            "title": report.render_title(), "statement": report.render_statement(),
            "source_report": report.model_dump(mode="json"), "topic_path": ["reports"],
        })
    manifest = {"contract_version": "separated-knowledge-assimilation-v1", "current_truth": rows}
    encoded, prose = _assimilation_manifest_packet(manifest)
    assert prose
    packet = json.loads(encoded)
    assert packet["current_truth"][0]["title"] == {"$sr_title": 0}
    group = packet["__lossless_source_reports_v1__"][0]
    assert group["render_title"] == "Topic 0 boundary"
    assert "topic_title" in group["scope"]

    mismatched = deepcopy(manifest)
    mismatched["current_truth"][0]["title"] = "Unchecked production approval"
    bad_encoded, _bad_prose = _assimilation_manifest_packet(mismatched)
    bad_packet = json.loads(bad_encoded)
    assert bad_packet["current_truth"][0]["title"] == "Unchecked production approval"
    assert "$sr_group" not in bad_packet["current_truth"][0]["source_report"]
    assert "$sr_group" in bad_packet["current_truth"][1]["source_report"]
