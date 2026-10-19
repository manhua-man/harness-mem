"""Isolated real SQLite/source/retrieval flow; semantic proposals are fixtures."""
import asyncio
import json

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.autonomous.models import AssimilationDecision, DistillCandidate
from harness_mem.autonomous.provider import _build_verification_prompt
from harness_mem.autonomous.worker import _build_candidate_verification_manifest
from harness_mem.commands.evidence_admission import validate_knowledge_sources
from harness_mem.commands.knowledge_assimilation import resolve_separated_review
from harness_mem.commands.separated_assimilation import (
    admit_separated_candidate, prepare_separated_assimilation,
    validate_separated_assimilation_decision, apply_separated_assimilation,
)
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


REPORT_TEXT = "In the Iris investigation, the sample proves a diagnostic path, not a rollout or user approval."


def _capture(root, *, user="Review the Iris diagnostic sample.", assistant=REPORT_TEXT):
    rows = [{"type": "session_meta", "payload": {"id": "native-report", "timestamp": "2024-06-01T02:03:04Z", "cwd": str(root)}}]
    for role, text in [("user", user), ("assistant", assistant)]:
        rows.append({"type": "response_item", "payload": {
            "type": "message", "role": role, "turn_id": "turn-1",
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        }})
    path = root / "native-report.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("surface", ["separated", "review"])
def test_native_source_report_survives_write_reopen_and_ordinary_search(tmp_path, monkeypatch, surface):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    native = _capture(root)

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive", project_root=root)
            sync = await adapter.sync_session(native, "native-report", project_name="demo")
            assert sync.distill_job_id
            rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
            window = render_distill_exchange_windows(rendering, [1])[0]
            candidate, _ = await admit_separated_candidate(
                backend, candidate_id="verified-report", project_name="demo", candidate_type="memory",
                statement=REPORT_TEXT, distill_job_id=sync.distill_job_id,
                evidence_basis="source_report", verification_outcome="verified",
                verification_refs=[{"kind": "source_report", "exchange_index": 1,
                                    "role": "assistant", "content_sha256": window["content_sha256"]}],
                verification_reason_codes=["semantic_support_verified", "future_utility_verified"],
            )
            assert candidate.source_report
            from harness_mem.mcp.distill_handlers import _separated_evidence_summary
            admission, gates = await _separated_evidence_summary(backend, candidate_ids=[candidate.id])
            assert admission.get("source_report") == 1
            assert admission["legacy_or_unknown"] == 0
            assert gates["ANSWERED"] == 1 and gates["UNANSWERED"] == 0
            item = {"title": "User approved rollout", "statement": "Iris is approved for production rollout.",
                    "topic_path": ["diagnostics"], "claim_kind": "implementation_fact"}
            if surface == "review":
                result = await resolve_separated_review(
                    backend, candidate_id=candidate.id, disposition="add", reason="Retain only the scoped source account.",
                    knowledge_items=[item], project_root=root, expected_project_name="demo",
                )
                ids = result["canonical_truth_ids"]
            else:
                prepared = await prepare_separated_assimilation(backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id])
                assert prepared.eligible_candidate_ids == (candidate.id,)
                decision = AssimilationDecision.model_validate({"points": [{
                    "candidate_id": candidate.id, "disposition": "add", "knowledge_items": [item],
                    "reason": "Retain only the verified bounded source report.",
                }]})
                plan = validate_separated_assimilation_decision(prepared, decision)
                assert plan["points"][0]["knowledge_items"][0]["claim_kind"] == "source_report"
                await apply_separated_assimilation(backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id], plan=plan)
                ids = [row.id for row in await backend.structured_store.knowledge_store.list_entries("demo")]
            assert len(ids) == 1
        finally:
            await backend.close()
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            rows = await search_current_knowledge(backend, query="Iris diagnostic", project_name="demo", limit=100)
            assert len(rows) == 1 and rows[0].id == ids[0]
            row = rows[0]
            assert row.source_report is not None
            assert row.source_report.speaker == "assistant"
            assert row.source_report.period == "2024-06-01T02:03:04Z"
            assert row.source_report.text == REPORT_TEXT
            assert row.statement == row.source_report.render_statement()
            assert row.title == row.source_report.render_title()
            assert "Iris is approved" not in row.statement
            sources = await backend.structured_store.knowledge_store.list_sources(row.id)
            assert sources and all(source.source_kind == "source_report" for source in sources)
            validation = await validate_knowledge_sources(backend, project_name="demo", sources=sources, project_root=root)
            assert validation.verification_outcome == "verified"
        finally:
            await backend.close()
    asyncio.run(exercise())


def test_report_semantic_support_reads_selected_native_role_not_whole_turn_assent(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    user = "Review diagnostics only. I do not approve a production rollout."
    assistant = "The user approved the production rollout."
    native = _capture(root, user=user, assistant=assistant)

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive", project_root=root)
            sync = await adapter.sync_session(native, "native-report", project_name="demo")
            rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
            windows = render_distill_exchange_windows(rendering, [1])
            packet = {"project_name": "demo", "semantic_decision_exchanges": windows}
            candidates = []
            for role, claim in [("user", assistant), ("user", "The user limited review to diagnostics and declined rollout approval."),
                                ("assistant", "The assistant claimed rollout had user approval.")]:
                candidate = DistillCandidate(kind="memory", category="knowledge", content=claim,
                    evidence_basis="source_report", verification_refs=[{
                        "kind": "source_report", "role": role, "exchange_index": 1,
                        "content_sha256": windows[0]["content_sha256"],
                    }])
                candidates.append((candidate, {"kind": "memory", "content": claim}))
            manifest = _build_candidate_verification_manifest(
                packet=packet, validated_candidates=candidates, project_root=root,
                backend=backend, distill_job_id=sync.distill_job_id,
            )
            assert manifest["candidates"][0]["sources"][0]["content"] == user
            assert manifest["candidates"][1]["sources"][0]["content"] == user
            assert manifest["candidates"][2]["sources"][0]["content"] == assistant
            assert "do not approve" in manifest["session_context"][0]["content"]
            assert assistant in manifest["session_context"][0]["content"]
            assert manifest["candidates"][1]["statement"] == candidates[1][1]["content"]
            prompt = _build_verification_prompt(manifest)
            projected = json.loads(prompt.split("<verification_manifest>", 1)[1].split("</verification_manifest>", 1)[0])
            excerpts = {item["source_id"]: item["content"] for item in projected["source_excerpts"]}
            for index, expected in enumerate([user, user, assistant]):
                source = projected["candidates"][index]["sources"][0]
                assert excerpts[source["source_id"]] == expected
                assert source["content_sha256"] == windows[0]["content_sha256"]
            # This proves the semantic verifier's inputs, not its decision or
            # an arbitrary manual caller's requested verified assertion.
        finally:
            await backend.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("surface", ["separated", "review"])
def test_native_nondurable_report_finishes_no_write_without_pending_handoff(tmp_path, monkeypatch, surface):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    root = tmp_path / "project"
    root.mkdir()
    native = _capture(root)
    original = native.read_bytes()

    async def exercise():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive", project_root=root)
            sync = await adapter.sync_session(native, "native-report", project_name="demo")
            rendering = backend.transcript_store.reconstruct(sync.source.id, source_revision=sync.source.source_revision)
            window = render_distill_exchange_windows(rendering, [1])[0]
            candidate, _ = await admit_separated_candidate(
                backend, candidate_id="session-only-report", project_name="demo", candidate_type="memory",
                statement=REPORT_TEXT, distill_job_id=sync.distill_job_id,
                evidence_basis="source_report", verification_outcome="not_applicable",
                verification_refs=[{"kind": "source_report", "exchange_index": 1,
                                    "role": "assistant", "content_sha256": window["content_sha256"]}],
                verification_reason_codes=["semantic_support_verified", "session_only_not_durable"],
            )
            prepared = await prepare_separated_assimilation(
                backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id])
            assert prepared.answer_status_by_candidate[candidate.id] == "NOT_APPLICABLE"
            assert prepared.eligible_candidate_ids == ()
            assert prepared.automatic_points[0]["disposition"] == "no_write"
            assert prepared.automatic_points[0]["matched_truth_ids"] == []
            if surface == "review":
                result = await resolve_separated_review(
                    backend, candidate_id=candidate.id, disposition="no_write",
                    reason="This supported source report has no durable value.",
                    project_root=root, expected_project_name="demo",
                )
                assert result["canonical_truth_ids"] == []
                assert result["disposition"] == "no_write" and result["changed"] is False
            else:
                plan = validate_separated_assimilation_decision(prepared, AssimilationDecision(points=[]))
                result = await apply_separated_assimilation(
                    backend, project_name="demo", project_root=str(root), candidate_ids=[candidate.id], plan=plan)
                assert result["no_write"] == 1 and result["promoted"] == 0
                assert result["pending"] == result["handoff"] == result["deferred"] == 0
                assert result["points"][0]["handoff_id"] is None
                assert result["points"][0]["canonical_truth_ids"] == []
            store = backend.structured_store.knowledge_store
            assert await store.list_entries("demo") == []
            final = await store.get_candidate(candidate.id)
            assert final.status == "assimilated"
            # This API lists unresolved decisions only; successful no-write
            # is represented in the returned packet, never a history ledger.
            assert await store.list_decisions(candidate.id) == []
        finally:
            await backend.close()
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            assert await search_current_knowledge(backend, query="Iris", project_name="demo", limit=100) == []
            assert native.read_bytes() == original
        finally:
            await backend.close()
    asyncio.run(exercise())
