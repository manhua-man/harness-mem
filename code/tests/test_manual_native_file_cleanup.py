"""Exercise the public history flow against isolated native source files."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import pytest

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.source_inspection import InspectedSource
from harness_mem.commands import session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _native_file(tmp_path, root, client, statement, task):
    user = f"Keep this project policy: {statement} Also {task}"
    if client == "hermes":
        sessions = tmp_path / "hermes" / "sessions"
        path = sessions / "session_policy.json"
        adapter = HermesAdapter(None, sessions_dir=sessions)
        body = json.dumps({
            "session_id": path.stem, "cwd": str(root),
            "messages": [
                {"role": "user", "content": user},
                {"role": "assistant", "content": "I recorded the policy. The follow-up is pending."},
            ],
        })
    else:
        brain = tmp_path / "antigravity" / "brain"
        path = brain / "session-policy" / ".system_generated" / "logs" / "transcript.jsonl"
        adapter = AntigravityAdapter(None, brain_dir=brain)
        body = "\n".join(json.dumps(row) for row in [
            {"type": "USER_INPUT", "cwd": str(root), "content": user},
            {"type": "PLANNER_RESPONSE", "content": "The policy is recorded. The follow-up is pending."},
        ])
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    os.utime(path, (time.time() - 180, time.time() - 180))
    return path, adapter


@pytest.mark.parametrize("client", ["hermes", "antigravity"])
@pytest.mark.parametrize("case", ["fresh", "legacy", "changed", "legacy_changed"])
def test_hm_native_file_cleanup_and_readback(tmp_path, monkeypatch, client, case):
    root = tmp_path / "project"
    root.mkdir()
    statement = "Each retention run saves a separate verification receipt."
    title = "Retention verification receipts"
    task = "Check the rollback copy before the next release."
    evidence = root / "policy.txt"
    evidence.write_text(statement, encoding="utf-8")
    path, adapter = _native_file(tmp_path, root, client, statement, task)
    native_bytes = path.read_bytes()
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(tool_handlers, "_cost_surface_budgets_provider", lambda _: None)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda *_: adapter)
    prepare = tool_handlers.tool_prepare_session_distill
    scope = {"project_name": "project", "project_root": str(root)}
    try:
        inventory = tool_handlers.tool_inspect_sessions(project_root=str(root), clients=[client])
        selected, = inventory["sessions"]
        with monkeypatch.context() as capture:
            if case.startswith("legacy"):
                capture.setattr(InspectedSource, "native_cleanup_file_kind", property(lambda _: None))
            packet = prepare(**scope, batch_sessions=[selected])
        assert packet["success"], packet
        job_id, batch_id = packet["distill_job_id"], packet["batch_id"]
        candidate = tool_handlers.tool_govern_memory(action="suggest", arguments={
            "kind": "memory", "project_name": "project", "category": "decision",
            "content": statement, "source": evidence.name, "distill_job_id": job_id,
            "evidence_basis": "repository", "verification_outcome": "verified",
            "verification_refs": [{"kind": "repository", "locator": evidence.name,
                                   "content_sha256": sha256(evidence.read_bytes()).hexdigest()}],
            "assimilation_disposition": "add", "assimilation_reason": "The current retention policy is durable.",
            "canonical_title": title, "topic_path": ["Retention"],
        })
        assert candidate["success"], candidate
        final = tool_handlers.tool_finalize_session_distill(project_name="project", job_id=job_id, semantic_review={
            "session_summary": "The policy was verified and the original rollback task is saved for later.",
            "final_user_request": "Retain the project policy and follow-up task.",
            "final_outcome": "Verified the policy. The rollback check remains open.",
            "last_turn_status": "unfinished", "contradictions": [], "unfinished_work": [task],
            "evidence_status": "answered", "promotion_decision": "partial",
            "final_scope_judgment": {candidate["entry_id"]: {"points": [{
                "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
                "source_use": "reusable_knowledge", "reason": "The repository confirms the current policy.",
                "scope_segments": [{"text": title + "\n" + statement, "source_use": "reusable_knowledge",
                                    "future_scope": "durable", "standalone": True, "content_role": "claim",
                                    "source_support": "supported"}],
            }]}},
        })
        assert final["success"], final
        note = Path(final["note"]["path"])
        note_bytes = note.read_bytes()
        handoffs = backend.structured_store.list_record_payloads("task_handoffs", strict=True)
        assert [item["next_steps"] for item in handoffs] == [[task]]
        preview = prepare(**scope, batch_id=batch_id, cleanup_processed=True)
        assert preview["counts"] == {"ready": 1}, preview
        assert path.read_bytes() == native_bytes
        assert backend.transcript_store.list_deletion_audit(project_name="project") == []
        if case.endswith("changed"):
            path.write_bytes(native_bytes + b" ")
            os.utime(path, (time.time() - 180, time.time() - 180))
        applied = prepare(**scope, batch_id=batch_id, cleanup_processed=True, apply_cleanup=True)
        if case.endswith("changed"):
            assert applied["counts"] == {"retained": 1}, applied
            assert path.read_bytes() == native_bytes + b" "
            return
        assert applied["counts"] == {"deleted": 1}, applied
        assert not path.exists()
        assert backend.transcript_store.verify_completed_distill_evidence_pruned(job_id)["raw_bytes"] == 0
        assert evidence.exists()
    finally:
        asyncio.run(backend.close())

    reopened = LocalMemoryBackend(backend.data_dir)
    asyncio.run(reopened.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: reopened)
        found = tool_handlers.tool_search_memory(query=title, scope="project", project_name="project", detail="full")
        assert found["memories"] == [{"title": title, "statement": statement}]
        assert note.read_bytes() == note_bytes
        assert reopened.structured_store.list_record_payloads("task_handoffs", strict=True) == handoffs
        inspected = tool_handlers.tool_inspect_sessions(**scope, batch_id=batch_id)
        assert inspected["progress"]["completed"] == 1 and inspected["unfinished_work"] == [task]
        replay = prepare(**scope, batch_id=batch_id, cleanup_processed=True, apply_cleanup=True)
        assert replay["counts"] == {"already_deleted": 1}, replay
    finally:
        asyncio.run(reopened.close())
