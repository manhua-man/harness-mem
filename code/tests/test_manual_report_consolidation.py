"""Actual manual finalize consolidates complete attributed reports together."""
from __future__ import annotations

import asyncio
import copy
from hashlib import sha256
import json

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.commands.separated_assimilation import target_version
from harness_mem.core.schemas.source_report import (
    bind_report_preservation_inventory, bind_report_preservation_inventories,
    report_preservation_digest, source_report_snapshot,
)
from harness_mem.mcp import tool_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from test_report_account_identity import report_judgment


@pytest.mark.parametrize("damage", ["missing_inventory", "missing_vote", "changed_predecessor"])
@pytest.mark.parametrize("partial", [False, True])
def test_manual_consolidation_requires_every_original_then_commits_and_reopens(tmp_path, monkeypatch, damage, partial):
    root = tmp_path / "project"
    root.mkdir()
    native = root / "rollout-cache.jsonl"
    old_bodies = ["The cache resumes after restart.", "Production validation remains pending."]
    combined = " ".join(old_bodies)
    records = [
        {"type": "session_meta", "payload": {"id": "cache-session", "cwd": str(root),
            "timestamp": "2026-10-19T08:15:13Z", "source": "vscode"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "Review the cache recovery and validation limits."}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": combined}]}},
    ]
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    handlers = tool_handlers.build_tool_handlers()
    submitted = {}
    title = "Cache recovery and validation report"
    review = {"session_summary": "The cache resumes after restart; production validation remains pending.",
              "final_user_request": "Review cache recovery and validation limits.",
              "final_outcome": "Only the bounded recovery behavior and remaining validation were reported.",
              "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
              "evidence_status": "answered", "promotion_decision": "promote"}

    def source():
        native.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
        synced = asyncio.run(CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive").sync_session(
            native, "cache-session", "demo"))
        packet = handlers["prepare_session_distill"](project_name="demo", project_root=str(root),
            distill_job_id=synced.distill_job_id, run_ingest=False)
        assert packet["success"], packet
        text = backend.transcript_store.reconstruct(synced.source.id)
        window = render_distill_exchange_windows(text, [len(records) // 2])[0]
        return synced.distill_job_id, window

    def suggest(job, window, body, targets=()):
        arguments = {
            "kind": "memory", "project_name": "demo", "distill_job_id": job,
            "content": body, "canonical_title": title, "topic_path": ["Reports"],
            "category": "Reports", "source": "Actual complete native report",
            "evidence_basis": "source_report", "verification_outcome": "verified",
            "verification_refs": [{"kind": "source_report", "exchange_index": window["exchange_index"],
                "content_sha256": window["content_sha256"], "role": "assistant"}],
            "assimilation_disposition": "replace" if targets else "add",
            "assimilation_reason": "Preserve the complete source-supported account and every remaining limit.",
            **({"target_knowledge": [{"title": entry.title, "statement": entry.statement,
                    "project_name": entry.project_name, "module": entry.module_path} for entry in targets]} if targets else {})}
        response = handlers["govern_memory"](action="suggest", arguments=arguments)
        assert response["success"], response
        candidate = asyncio.run(backend.structured_store.knowledge_store.get_candidate(response["entry_id"]))
        submitted[candidate.id] = {key: value for key, value in arguments.items()
                                   if key not in {"kind", "project_name", "distill_job_id"}}
        return candidate.id, candidate.source_report

    try:
        job, window = source()
        first = {}
        for body in old_bodies:
            identity, report = suggest(job, window, body)
            first[identity] = report_judgment(report, title)
        if partial:
            from harness_mem.commands.knowledge_assimilation import resolve_separated_review
            first_id = next(iter(first))
            result = asyncio.run(resolve_separated_review(backend, candidate_id=first_id, disposition="add",
                reason="This first point committed before the original review failed on a later point.",
                knowledge_items=[{"title": title, "statement": old_bodies[0], "topic_path": ["Reports"],
                                  "claim_kind": "source_report"}], project_root=root, expected_project_name="demo",
                final_scope_judgment=first[first_id]))
            assert result["canonical_truth_ids"]
            committed = asyncio.run(backend.structured_store.knowledge_store.get_candidate(first_id))
            committed.assimilation_disposition = committed.assimilation_reason = committed.canonical_title = None
            committed.topic_path = []
            asyncio.run(backend.structured_store.knowledge_store.save_candidate(committed))
        else:
            final = handlers["finalize_session_distill"]("demo", job, {**review, "final_scope_judgment": first})
            assert final["success"], final
        old = asyncio.run(backend.structured_store.knowledge_store.list_entries("demo"))
        assert len(old) == (1 if partial else 2)
        if not partial:
            records.extend([
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Keep those two report meanings together."}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": combined}]}},
            ])
        job, window = source()
        identity, report = suggest(job, window, combined, old)
        written = report.model_copy(update={"topic_title": title})
        items = [{"title": title, "statement": written.render_statement(), "topic_path": ["Reports"],
                  "claim_kind": "source_report", "source_report": source_report_snapshot(written)}]
        targets, originals = [], []
        for entry in old:
            target = {"id": entry.id, "title": entry.title, "statement": entry.statement,
                "topic_path": entry.module_path, "source_report": source_report_snapshot(entry.source_report)}
            target["version"] = target_version(target)
            targets.append(target)
            classification = {"scope_segments": [{"text": entry.source_report.text,
                "source_use": "reusable_knowledge", "future_scope": "durable", "standalone": True,
                "content_role": "claim", "source_support": "supported"}], "claim_units": [{
                    "first_segment": 0, "end_segment_exclusive": 1, "standalone": True,
                    "source_support": "supported", "source_use": "reusable_knowledge", "future_scope": "durable"}]}
            originals.append(bind_report_preservation_inventory(owner=identity, target=target, items=items,
                omissions=[], classification=classification, mode="full_revision"))
        inventory = bind_report_preservation_inventories(owner=identity, targets=targets, items=items,
            inventories=originals, expected_mode="full_revision")
        judgment = report_judgment(report, title)
        point = judgment["points"][0]
        point["report_topic_judgments"] = [{"relationship": "same_topic",
            "predecessor_title": entry.title, "successor_title": title,
            "basis": "The complete source account concerns this cache's recovery and its validation limits."}
            for entry in old]
        point["report_preservation_inventory"] = inventory
        point["update_meaning_judgment"] = {
            "relationship": "preserves_applicable_meaning", "predecessor_conditions": [],
            "predecessor_statements": [row["statement"] for row in targets],
            "predecessor_versions": [row["version"] for row in targets],
            "successor_statements": [written.render_statement()], "undecided_state": None,
            "basis": "Both full original reports remain supported, including the explicit production limit.",
            "report_preservation": {"owner_candidate_id": identity, "inventory_complete": True,
                "inventory_sha256": report_preservation_digest(inventory), "units": [{
                    "unit_index": index, "unit_sha256": report_preservation_digest(unit), "verdict": "preserved",
                    "successor_spans": [{"successor_index": 0, "char_start": 0, "char_end": len(combined),
                        "text_sha256": sha256(combined.encode()).hexdigest()}]}
                    for index, unit in enumerate(inventory["units"])], "omissions": []}}
        broken = copy.deepcopy(judgment)
        if damage == "missing_inventory":
            broken["points"][0].pop("report_preservation_inventory")
        elif damage == "missing_vote":
            broken["points"][0]["update_meaning_judgment"]["report_preservation"]["units"].pop()
        else:
            original = broken["points"][0]["report_preservation_inventory"]
            if "predecessor_inventories" in original:
                original = original["predecessor_inventories"][0]
            original["predecessor_version"] = "changed"
        if partial:
            ordinary = handlers["finalize_session_distill"]("demo", job,
                {**review, "final_scope_judgment": {identity: judgment}})
            assert ordinary["error"] == "prior_review_requires_assimilation_replay", ordinary
        submission = {"memory_points": [submitted[identity]]} if partial else {}
        rejected = handlers["finalize_session_distill"]("demo", job,
            {**review, "final_scope_judgment": {identity: broken}}, **submission)
        assert not rejected["success"], rejected
        assert {entry.id: entry.to_dict() for entry in asyncio.run(backend.structured_store.knowledge_store.list_entries("demo"))} == {
            entry.id: entry.to_dict() for entry in old}
        accepted = handlers["finalize_session_distill"]("demo", job,
            {**review, "final_scope_judgment": {identity: judgment}}, **submission)
        assert accepted["success"], json.dumps(accepted, ensure_ascii=False)
        entries = asyncio.run(backend.structured_store.knowledge_store.list_entries("demo"))
        assert len(entries) == 1 and entries[0].statement == written.render_statement()
        assert all(entries[0].id != entry.id for entry in old)
        expected = entries[0].to_dict()
    finally:
        asyncio.run(backend.close())
    fresh = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(fresh.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: fresh)
        recalled = handlers["search_memory"](query=title, scope="project", project_name="demo")
        assert any(row["statement"] == written.readable_statement() for row in recalled["memories"]), recalled
        assert asyncio.run(fresh.structured_store.knowledge_store.list_entries("demo"))[0].to_dict() == expected
    finally:
        asyncio.run(fresh.close())
