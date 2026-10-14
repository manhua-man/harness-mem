"""Fictional device sessions use the public memory loop without directory setup."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.commands import manual_distill, session_inventory
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import distill_handlers, governance_handlers, tool_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def device(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    native = tmp_path / "native" / "sessions"
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda client: CodexAdapter(None, sessions_dir=native))
    monkeypatch.setattr(manual_distill, "runtime_fingerprint", lambda: "fictional-device-runtime")
    monkeypatch.setattr(distill_handlers, "_session_notes_dir", lambda _: backend.data_dir / "notes")

    def write(name, text, *, roots=()):
        path = native / f"rollout-{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{"type": "session_meta", "payload": {"id": name}}]
        records.extend({"type": "turn_context", "payload": {"cwd": str(root)}} for root in roots)
        for role, value in (("user", text), ("assistant", "Understood.")):
            records.append({"type": "response_item", "payload": {
                "type": "message", "role": role, "content": [{
                    "type": "input_text" if role == "user" else "output_text", "text": value,
                }],
            }})
        path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
        return path

    yield backend, write
    asyncio.run(backend.close())


def remember(backend, packet, statement, *, disposition="add", targets=None):
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    observation = asyncio.run(backend.verbatim_store.get(str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))))
    digest = render_distill_exchange_windows(observation.raw_content, [1])[0]["content_sha256"]
    result = governance_handlers.tool_govern_memory(action="suggest", arguments={
        "kind": "memory", "project_name": job.project_name, "distill_job_id": job.id,
        "category": "preference", "content": statement, "source": f"distill-job:{job.id}",
        "canonical_title": "Fictional retention preference", "topic_path": ["Preferences"],
        "evidence_basis": "user_statement", "verification_outcome": "verified",
        "verification_refs": [{"kind": "user_statement", "exchange_index": 1, "content_sha256": digest}],
        "assimilation_disposition": disposition, "assimilation_reason": "Verified explicit future preference.",
        **({"target_knowledge": targets} if targets else {}),
    })
    assert result["success"], result
    final = tool_handlers.tool_finalize_session_distill(job.project_name, job.id, {
        "session_summary": "Verified an explicit future preference.", "final_user_request": statement,
        "final_outcome": "Saved the verified preference.", "last_turn_status": "answered",
        "contradictions": [], "unfinished_work": [], "evidence_status": "answered", "promotion_decision": "promote",
    })
    assert final["success"], final
    return final


@pytest.mark.parametrize("context", ["rootless", "missing", "mixed"])
def test_directory_is_not_required_to_remember_find_and_correct(device, tmp_path, context):
    backend, write = device
    roots = () if context == "rootless" else (tmp_path / "gone",) if context == "missing" else (tmp_path / "gone", tmp_path / "other")
    first = "For future collaboration, keep independently verifiable facts."
    corrected = "For future collaboration, keep independently verifiable facts for fourteen days."
    paths = [write("a-first", first, roots=roots), write("b-corrected", corrected, roots=roots)]
    originals = {path: path.read_bytes() for path in paths}
    before = tool_inspect_sessions(clients=["codex"])
    assert before["success"], before
    assert len(before["sessions"]) == 2
    assert not list(backend.transcript_store.list_distill_jobs())
    selected = before["sessions"]
    packet = tool_handlers.tool_prepare_session_distill(batch_sessions=selected, scope="all")
    assert packet["success"], packet
    assert packet["session_id"] == "a-first", packet
    assert len(list(backend.transcript_store.list_distill_jobs())) == 1
    added = remember(backend, packet, first)
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    source = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    assert source is not None
    assert source.parser_version == "codex-conversation-v3"
    assert b"Assistant: Understood." in backend.transcript_store.reconstruct_raw(job.source_id, source_revision=job.source_revision)
    assert added["knowledge_changes"], json.dumps(added, ensure_ascii=False)
    assert added["knowledge_changes"][0]["change"] == "added", added
    current = tool_handlers.tool_search_memory(query="")
    old = current["memories"][0]
    assert old["statement"] == first
    batch_id = packet["batch_id"]
    packet = tool_handlers.tool_prepare_session_distill(batch_id=batch_id)
    assert packet["success"] and packet["session_id"] == "b-corrected", packet
    replacement = remember(backend, packet, corrected, disposition="replace", targets=[old])
    assert replacement["knowledge_changes"][0]["change"] == "replaced", replacement
    complete = tool_handlers.tool_prepare_session_distill(batch_id=batch_id)
    assert complete["status"] == "completed", complete
    assert complete["progress"]["completed"] == 2
    assert complete["unfinished_work"] == []
    assert tool_handlers.tool_search_memory(query="")["memories"] == [{
        "module": ["Preferences"], "title": "Fictional retention preference", "statement": corrected,
        "project_name": "global",
    }]
    assert all(path.read_bytes() == content for path, content in originals.items())
    for result in (added, replacement):
        note = Path(result["note"]["path"])
        assert hashlib.sha256(note.read_bytes()).hexdigest() == result["note"]["sha256"]
    assert not (backend.data_dir / "profiles").exists()
    assert all(job.manual_only and job.retain_source for job in backend.transcript_store.list_distill_jobs())


@pytest.mark.parametrize("uri_root", [False, True])
def test_local_policy_changes_invalidate_cached_device_pages(device, tmp_path, monkeypatch, uri_root):
    backend, write = device
    root = tmp_path / "private-workspace"
    root.mkdir()
    policy = root / ".harness-mem.toml"
    policy.write_text("allow", encoding="utf-8")
    write("policy", "fictional-secret " * 20, roots=[root.as_uri() if uri_root else root])
    loaded = []
    def config(path):
        loaded.append(path)
        return MergedConfig(capture_enabled=path is None or policy.read_text() == "allow")
    monkeypatch.setattr(session_inventory, "load_merged_config", config)
    row, = tool_inspect_sessions(clients=["codex"])["sessions"]
    session_inventory.read_session_page(backend.data_dir, session=row, page_chars=30)
    policy.write_text("deny", encoding="utf-8")
    for cached in (True, False):
        if not cached:
            session_inventory._PAGE_CACHE.clear()
        with pytest.raises(ValueError):
            session_inventory.read_session_page(backend.data_dir, session=row, offset=30, page_chars=30)
    assert root.resolve() in loaded
    assert not list(backend.transcript_store.list_distill_jobs())


def test_ledger_device_batch_and_bound_resume_cannot_bypass_local_exclusion(device, tmp_path, monkeypatch):
    backend, write = device
    root = tmp_path / "private-workspace"
    root.mkdir()
    write("ledger-policy", "fictional-ledger-secret", roots=[root])
    rows = tool_inspect_sessions(clients=["codex"])["sessions"]
    original = tool_handlers.tool_prepare_session_distill(batch_sessions=rows, scope="all")
    assert original["success"], original
    job_before = backend.transcript_store.get_distill_job(original["distill_job_id"]).to_dict()
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: CodexAdapter(None, sessions_dir=tmp_path / "empty"))
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda path: MergedConfig(capture_enabled=path is None))
    row, = tool_inspect_sessions(clients=["codex"])["sessions"]
    assert row["origin"] == "ledger" and row["readability"] == "excluded" and row["processing"] == "skipped"
    assert not tool_inspect_sessions(action="source", session=row)["success"]
    result = tool_handlers.tool_prepare_session_distill(batch_sessions=[row], scope="all")
    assert not result.get("semantic_decision_exchanges"), result
    assert result["progress"]["states"]["skipped"] == 1
    resumed = tool_handlers.tool_prepare_session_distill(batch_id=original["batch_id"])
    assert not resumed["success"] and resumed["status"] == "stopped", resumed
    assert "fictional-ledger-secret" not in json.dumps(resumed)
    assert backend.transcript_store.get_distill_job(original["distill_job_id"]).to_dict() == job_before
    assert asyncio.run(backend.structured_store.knowledge_store.list_entries("global")) == []
