"""Exercise concise Agent review of native attributed reports through public handlers."""
from __future__ import annotations

import asyncio
import json

import pytest

from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.mcp import tool_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


CONDITION = "only when the snapshot signature verifies"
RECOVERY = f"The cache resumes after restart {CONDITION}."
VALIDATION = "Production validation remains pending."
COMBINED = f"{RECOVERY} {VALIDATION}"
TITLE = "Cache recovery and validation report"
PERIOD = "2026-10-19T08:15:13Z"


def _exchange(prompt):
    return [
        {"type": "response_item", "payload": {"type": "message", "role": role,
            "content": [{"type": kind, "text": text}]}}
        for role, kind, text in (("user", "input_text", prompt), ("assistant", "output_text", COMBINED))
    ]


def _prepare(backend, handlers, root, session_id, exchanges):
    path = root / f"rollout-{session_id}.jsonl"
    records = [{"type": "session_meta", "payload": {
        "id": session_id, "cwd": str(root), "timestamp": PERIOD, "source": "vscode",
    }}]
    for prompt in exchanges:
        records.extend(_exchange(prompt))
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    capture = asyncio.run(CodexAdapter(backend, sessions_dir=root, archive_dir=root / "archive").sync_session(
        path, session_id, "demo"))
    packet = handlers.tool_prepare_session_distill(project_name="demo", project_root=str(root),
        distill_job_id=capture.distill_job_id, run_ingest=False)
    assert packet["success"], packet
    rendering = backend.transcript_store.reconstruct(capture.source.id)
    window, = render_distill_exchange_windows(rendering, [len(exchanges)])
    return capture, window


def _point(window, body, *, conditions, undecided_state, targets=()):
    return {
        "content": body, "canonical_title": TITLE, "topic_path": ["Reports"],
        "evidence_basis": "source_report", "verification_outcome": "verified",
        "verification_refs": [{"kind": "source_report", "exchange_index": window["exchange_index"],
            "content_sha256": window["content_sha256"], "role": "assistant"}],
        "assimilation_disposition": "replace" if targets else "add",
        "review": {"support": "supported", "use": "reusable_knowledge",
            "reason": "Keep the assistant's bounded cache recovery account and all applicable limits.",
            "conditions": conditions, "undecided_state": undecided_state,
            **({"preserves_meaning": True, "same_topic": True} if targets else {})},
        **({"target_knowledge": list(targets)} if targets else {}),
    }


def _finalize(handlers, job, points):
    review = {"session_summary": COMBINED, "final_user_request": "Review recovery and validation limits.",
        "final_outcome": "The assistant reported the bounded recovery result and pending validation.",
        "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
        "evidence_status": "answered", "promotion_decision": "promote"}
    return handlers.tool_finalize_session_distill("demo", job, review, memory_points=points)


def _entries(backend):
    return asyncio.run(backend.structured_store.knowledge_store.list_entries("demo"))


@pytest.mark.parametrize("damage", [None, "same_topic", "preserves_meaning", "missing_condition", "other_account"])
def test_concise_report_review_preserves_account_and_conditions_after_reopen(tmp_path, monkeypatch, damage):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("HARNESS_MEM_SESSION_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: backend)
    monkeypatch.setattr(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir)
    handlers = tool_handlers
    try:
        original_prompt = "Review the cache recovery and validation limits."
        original, window = _prepare(backend, handlers, root, "cache-session", [original_prompt])
        added = _finalize(handlers, original.distill_job_id, [
            _point(window, RECOVERY, conditions=[CONDITION], undecided_state=None),
            _point(window, VALIDATION, conditions=[], undecided_state=VALIDATION),
        ])
        assert added["success"] and added["readback_verified"], added
        assert [change["change"] for change in added["knowledge_changes"]] == ["added", "added"]
        old = _entries(backend)
        assert len(old) == 2
        assert {entry.source_report.text for entry in old} == {RECOVERY, VALIDATION}
        assert all(entry.source_report.source_id == original.source.id for entry in old)
        assert all(entry.statement == entry.source_report.render_statement() for entry in old)
        target_response = handlers.tool_search_memory(query=TITLE, scope="all")
        targets = [row for row in target_response["memories"] if row["title"] == TITLE]
        assert {row["statement"] for row in targets} == {entry.source_report.readable_statement() for entry in old}, target_response
        assert all(PERIOD in row["statement"] and "not independently established" in row["statement"] for row in targets)
        assert all(row["project_name"] == "demo" for row in targets)

        if damage == "other_account":
            capture, window = _prepare(backend, handlers, root, "other-cache-session", [original_prompt])
            assert capture.source.id != original.source.id
        else:
            capture, window = _prepare(backend, handlers, root, "cache-session",
                [original_prompt, "Keep the recovery result and validation limit together."])
            assert capture.source.id == original.source.id
            assert capture.source.source_revision != original.source.source_revision
        body = COMBINED if damage != "missing_condition" else f"The cache resumes after restart. {VALIDATION}"
        point = _point(window, body, conditions=[CONDITION], undecided_state=VALIDATION, targets=targets)
        if damage in {"same_topic", "preserves_meaning"}:
            del point["review"][damage]
        final = _finalize(handlers, capture.distill_job_id, [point])
        entries = _entries(backend)
        if damage:
            assert not final.get("knowledge_changes"), final
            assert {entry.id: entry.to_dict() for entry in entries} == {entry.id: entry.to_dict() for entry in old}
        else:
            assert final["success"] and final["readback_verified"], final
            successor, = entries
            assert successor.id not in {entry.id for entry in old}
            report = successor.source_report
            assert report.text == COMBINED
            assert report.speaker == "assistant" and report.period == PERIOD
            assert (report.session_id, report.source_id, report.source_revision, report.exchange_indexes) == (
                "cache-session", original.source.id, capture.source.source_revision, [2],
            )
            assert successor.statement == report.render_statement()
            assert final["knowledge_changes"] == [{"change": "replaced", "module": ["Reports"],
                "title": TITLE, "statement": report.readable_statement()}]
        expected = {entry.id: entry.to_dict() for entry in entries}
        statements = {entry.source_report.readable_statement() for entry in entries}
    finally:
        asyncio.run(backend.close())
    fresh = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(fresh.init())
    try:
        monkeypatch.setattr(tool_handlers, "_backend_provider", lambda: fresh)
        recalled = handlers.tool_search_memory(query=TITLE, scope="project", project_name="demo")
        assert {row["statement"] for row in recalled["memories"]} == statements, recalled
        assert {entry.id: entry.to_dict() for entry in _entries(fresh)} == expected
    finally:
        asyncio.run(fresh.close())
