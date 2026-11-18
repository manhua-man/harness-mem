"""A resumed native history review must retain the actual archived-file proof."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import os
import time
from uuid import uuid4

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("ambiguous", [False, True])
def test_reviewed_native_move_refreshes_shared_source_and_cleanup(tmp_path, monkeypatch, resume, ambiguous):
    root = tmp_path / "project"
    root.mkdir()
    native_home = tmp_path / "codex"
    sessions, archive = native_home / "sessions", native_home / "archived_sessions"
    sessions.mkdir(parents=True)
    archive.mkdir()
    path = sessions / "rollout-closed.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": "closed", "cwd": str(root),
            "timestamp": "2026-10-19T08:15:13.555Z", "source": "vscode"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "hello"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello, ready to help."}]}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: CodexAdapter(
        None, sessions_dir=sessions, archive_dir=archive))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "native-rebind-fixture")
    handlers = tool_handlers.build_tool_handlers()

    def prepare(**arguments):
        return handlers["prepare_session_distill"](project_name="project", project_root=str(root), **arguments)

    try:
        synced = asyncio.run(CodexAdapter(backend, sessions_dir=sessions, archive_dir=archive).sync_session(
            path, "closed", "project"))
        original_source_id = synced.source.id
        frozen_metadata = backend.transcript_store.get_revision(
            synced.source.id, synced.source.source_revision).metadata
        if ambiguous:
            duplicate_id = str(uuid4())
            duplicate = synced.source.model_copy(update={"id": duplicate_id,
                "source_uri": (sessions / "another-closed.jsonl").as_uri()})
            chunks = [chunk.model_copy(update={"id": str(uuid4()), "source_id": duplicate_id})
                      for chunk in backend.transcript_store.list_chunks(synced.source.id)]
            backend.transcript_store.save_snapshot(duplicate, chunks,
                raw_bytes=backend.transcript_store.reconstruct_raw(synced.source.id))
        packet = None
        if resume:
            rows = handlers["inspect_sessions"](project_root=str(root), clients=["codex"])["sessions"]
            packet = prepare(batch_sessions=[row for row in rows if row["origin"] == "native"])
            assert packet["success"], packet
        moved = archive / path.name
        path.rename(moved)
        # Native operational records can append without changing the dialogue.
        with moved.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n")
        os.utime(moved, (time.time() - 120, time.time() - 120))
        sources_before = {row.id: row.to_dict() for row in backend.transcript_store.list_sources(project_name="project")}
        jobs_before = {row.id for row in backend.transcript_store.list_distill_jobs(project_name="project")}
        if resume:
            packet = prepare(batch_id=packet["batch_id"])
        else:
            rows = handlers["inspect_sessions"](project_root=str(root), clients=["codex"])["sessions"]
            packet = prepare(batch_sessions=[row for row in rows if row["origin"] == "native"])
        if ambiguous:
            assert not packet["success"] and packet["error"] == "selected_native_binding_failed", packet
            assert {row.id: row.to_dict() for row in backend.transcript_store.list_sources(project_name="project")} == sources_before
            assert {row.id for row in backend.transcript_store.list_distill_jobs(project_name="project")} == jobs_before
            assert moved.exists()
            return
        assert packet["success"], packet
        job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
        assert job.source_id == original_source_id
        assert job.id == synced.distill_job_id
        source = backend.transcript_store.get_source(job.source_id)
        revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
        assert source.metadata["native_source_uri"] == moved.as_uri()
        assert source.metadata["native_input_sha256"] == sha256(moved.read_bytes()).hexdigest()
        assert source.metadata["codex_session_origin"] == {"kind": "primary"}
        assert revision.metadata == frozen_metadata
        final = handlers["finalize_session_distill"]("project", job.id, {
            "session_summary": "The session exchanged a greeting without making durable decisions.",
            "final_user_request": "greeting", "final_outcome": "greeting answered",
            "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
            "evidence_status": "answered", "promotion_decision": "no_promotion"})
        assert final["success"], final
        applied = prepare(batch_id=packet["batch_id"], cleanup_processed=True, apply_cleanup=True)
        assert applied["success"], applied
        assert applied["counts"] == {"deleted": 1}
        assert not moved.exists()
    finally:
        asyncio.run(backend.close())
