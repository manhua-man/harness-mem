"""The daily batch reuses real intake/evidence/CAS and current-store readback."""
import asyncio
import json

import pytest

from harness_mem.mcp import tool_handlers
from test_device_memory_flow import device as device


def review(**updates):
    return {"session_summary": "Reviewed the full fictional reading-club conversation.",
            "final_user_request": "Remember the reading-club rules.", "final_outcome": "Saved supported rules.",
            "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
            "evidence_status": "answered", "promotion_decision": "promote", **updates}


def point(packet, text, *, basis="user_statement", role="user", **updates):
    window = packet["semantic_decision_exchanges"][0]
    return {"content": text, "canonical_title": text, "topic_path": ["Reading club"],
            "evidence_basis": basis, "verification_outcome": "verified",
            "verification_refs": [{"kind": basis, "exchange_index": window["exchange_index"],
                                   "content_sha256": window["content_sha256"], "role": role}],
            "assimilation_disposition": "add", "assimilation_reason": "Retain this verified future-use point.",
            **updates}


def finish(packet, points, **updates):
    return tool_handlers.tool_finalize_session_distill(
        packet["project_name"], packet["distill_job_id"], review(**updates), memory_points=points,
    )


def test_prepare_plus_finish_preserves_suggestion_identity_and_correction_state(device):
    backend, write = device
    original = "For Iris club, use simplified Chinese and original book titles; verify pages first."
    suggestion = "For Iris club, I suggest transliterating author names; this is only my suggestion."
    native = write("iris-first", original)
    records = [json.loads(line) for line in native.read_text().splitlines()]
    records[-1]["payload"]["content"][0]["text"] = suggestion
    native.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="iris-first", include_current=True,
    )
    assert packet["success"] and packet["current_knowledge"] == []
    initial_points = [point(packet, original), point(packet, suggestion, basis="source_report", role="assistant")]
    saved = finish(packet, initial_points)
    assert saved["success"] and saved["readback_verified"], saved
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.promotion_summary["answer_packet"]["answer_status"] == "ANSWERED"
    assert job.promotion_summary["answer_gate"]["ANSWERED"] == 2
    from pathlib import Path
    note = Path(saved["note"]["path"]).read_text(encoding="utf-8")
    assert "证据不完整" not in note
    replay = finish(packet, initial_points)
    assert replay["success"] and replay["idempotent_replay"], replay
    changed_replay = finish(packet, [point(packet, "A different unsubmitted claim.")])
    assert changed_replay["success"] is False and "differs" in changed_replay["error"]
    rows = tool_handlers.tool_search_memory(query="Iris club")["memories"]
    assert len(rows) == 2
    assert any("Source-scoped report" in row["statement"] and "assistant" in row["statement"] for row in rows)

    corrected = "For Iris club, use Chinese book titles with original on first use; other rules stay. Author names are undecided."
    write("iris-corrected", corrected)
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="iris-corrected", include_current=True,
    )
    assert packet["success"] and len(packet["current_knowledge"]) == 2, packet
    old = next(row for row in packet["current_knowledge"] if row["statement"] == original)
    state = "For Iris club, author names are undecided."
    work_item = state
    saved = finish(packet, [
        point(packet, "For Iris club, use simplified Chinese, Chinese book titles with original on first use, and verified pages.",
              assimilation_disposition="replace", target_knowledge=[old]),
        point(packet, state, retained_state_item=work_item),
    ], unfinished_work=[work_item])
    assert saved["success"] and saved["readback_verified"], saved
    assert saved["organization_status"] == "completed" and saved["unfinished_work"] == [], saved
    rows = asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    assert len(rows) == 3 and any(row.source_report for row in rows)
    assert all(row.statement != original for row in rows)
    assert any(row.statement == state for row in rows)


def test_source_context_lookup_failure_preserves_prepared_job(device, monkeypatch):
    backend, write = device
    write("context-error", "For Iris club, retain original titles.")
    async def fail(*args, **kwargs):
        raise OSError("current store unavailable")
    monkeypatch.setattr("harness_mem.read_knowledge.search_current_knowledge", fail)
    result = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="context-error", include_current=True,
    )
    assert result["success"] is False and result["current_knowledge_status"] == "unavailable"
    assert "current_knowledge" not in result and "unavailable" in result["error"]
    job = backend.transcript_store.get_distill_job(result["distill_job_id"])
    assert job.status == "reviewing" and not job.output_candidate_ids
    assert result["semantic_decision_exchanges"]


def test_source_context_is_global_context_without_owner_binding(device, monkeypatch):
    from types import SimpleNamespace
    backend, write = device
    write("context-owners", "For Iris club, retain original titles.")
    calls = []
    async def lookup(unused_backend, *, project_name, query, source_context):
        assert source_context is True
        calls.append((project_name, query))
        return [SimpleNamespace(statement="Full old rule", canonical_title="Titles",
                                project_name=owner) for owner in ("one", "two")]
    monkeypatch.setattr("harness_mem.read_knowledge.search_current_knowledge", lookup)
    result = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="context-owners", include_current=True,
    )
    assert result["success"] and calls[0][0] is None
    assert "For Iris club, retain original titles." in calls[0][1]
    assert {row["project_name"] for row in result["current_knowledge"]} == {"one", "two"}
    job = backend.transcript_store.get_distill_job(result["distill_job_id"])
    assert job.project_name == result["project_name"] == "global" and not job.output_candidate_ids


def test_source_context_explicit_project_is_strict(device, monkeypatch):
    backend, write = device
    write("context-project", "For Iris club, retain original titles.")
    first = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="context-project",
    )
    calls = []
    async def lookup(unused_backend, *, project_name, query, source_context):
        assert source_context is True
        calls.append(project_name)
        return []
    monkeypatch.setattr("harness_mem.read_knowledge.search_current_knowledge", lookup)
    result = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="project", project_name=first["project_name"],
        distill_job_id=first["distill_job_id"], include_current=True,
    )
    assert result["success"], result
    assert calls == [result["project_name"]]


def test_source_context_rejects_legacy_owner_query_combination(device):
    result = tool_handlers.tool_prepare_session_distill(
        session_id="unread", include_current=True, current_query="Iris club",
    )
    assert result["success"] is False and "mutually exclusive" in result["error"]


def test_chinese_full_source_context_retains_unnamed_correction_target(device):
    _, write = device
    old = "星河读书会正文用简体中文，书名保留原文；页码须核实后再写。"
    write("chinese-context-first", old)
    first = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="chinese-context-first", include_current=True,
    )
    assert finish(first, [point(first, old)])["success"]
    write("chinese-context-change", "改一下：书名先用中文译名，首次出现附原名，正文语言和页码规则不变。作者姓名写法还没决定。")
    changed = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="chinese-context-change", include_current=True,
    )
    assert changed["success"], changed
    assert any(row["statement"] == old for row in changed["current_knowledge"]), changed


@pytest.mark.parametrize("bad_point", [
    {"topic_path": "bad/string"}, {"unknown_field": True}, {"project_name": "elsewhere"},
    {"verification_refs": []},
])
def test_invalid_batch_never_writes_truth(device, bad_point):
    backend, write = device
    text = "For Iris club, author names are undecided."
    write("invalid-batch", text)
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="invalid-batch")
    result = finish(packet, [point(packet, text), point(packet, text, **bad_point)])
    assert result["success"] is False
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))


def test_stale_digest_batch_cannot_promote_or_hide_work(device):
    backend, write = device
    text = "For Iris club, author names are undecided."
    write("stale-batch", text)
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="stale-batch")
    p = point(packet, text, retained_state_item=text)
    p["verification_refs"][0]["content_sha256"] = "0" * 64
    result = finish(packet, [p], unfinished_work=[text])
    assert not result.get("readback_verified"), result
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))


def test_prepare_query_rejects_empty_or_unselected_source(device):
    assert not tool_handlers.tool_prepare_session_distill(current_query="Iris")["success"]
    assert not tool_handlers.tool_prepare_session_distill(current_query="", session_id="missing")["success"]


@pytest.mark.parametrize("unsupported", [
    {"locator": "An assistant's literal recommendation."},
    {"locator_sha256": "1" * 64},
    {"chunk_index": 0},
])
def test_source_report_locator_is_rejected_before_staging_and_same_job_can_retry(device, unsupported):
    backend, write = device
    user = "For Iris club, use simplified Chinese."
    assistant = "For Iris club, I suggest transliterating author names; this is only my suggestion."
    native = write("source-ref-retry", user)
    records = [json.loads(line) for line in native.read_text().splitlines()]
    records[-1]["payload"]["content"][0]["text"] = assistant
    native.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="source-ref-retry",
    )
    report = point(packet, assistant, basis="source_report", role="assistant")
    report["verification_refs"][0].update(unsupported)
    failed = finish(packet, [point(packet, user), report])
    assert failed["success"] is False and "No candidates were staged" in failed["error"], failed
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.status == "reviewing" and job.output_candidate_ids == []
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    correct_report = point(packet, assistant, basis="source_report", role="assistant")
    saved = finish(packet, [point(packet, user), correct_report])
    assert saved["success"] and saved["readback_verified"], saved
    assert saved["organization_status"] == "completed" and saved["unfinished_work"] == []
    rows = asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    assert len(rows) == 2 and sum(bool(row.source_report) for row in rows) == 1


@pytest.mark.parametrize("shape", ["object", "content_alias"])
def test_wrong_target_shape_never_stages_earlier_points_and_can_retry_same_job(device, shape):
    backend, write = device
    original = "For Iris club, retain original book titles."
    write("target-shape-initial", original)
    first = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="target-shape-initial",
    )
    assert finish(first, [point(first, original)])["success"]
    old = tool_handlers.tool_search_memory(query="Iris club")["memories"][0]
    corrected = "For Iris club, use translated titles with original on first use."
    write("target-shape-correction", corrected)
    packet = tool_handlers.tool_prepare_session_distill(
        client="codex", scope="all", session_id="target-shape-correction",
    )
    bad = dict(old) if shape == "object" else [{
        "title": old["title"], "content": old["statement"], "project_name": old["project_name"],
    }]
    replacing = point(packet, corrected, assimilation_disposition="replace", target_knowledge=bad)
    failed = finish(packet, [point(packet, corrected), replacing])
    assert failed["success"] is False and "target_knowledge must be an array" in failed["error"], failed
    assert "statement" in failed["error"] and "No candidates were staged" in failed["error"]
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.status == "reviewing" and job.output_candidate_ids == []
    rows = asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    assert len(rows) == 1 and rows[0].statement == original
    minimal_old = {key: old[key] for key in ("title", "statement", "project_name")}
    saved = finish(packet, [point(packet, corrected, assimilation_disposition="replace", target_knowledge=[minimal_old])])
    assert saved["success"] and saved["readback_verified"], saved
    rows = asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    assert len(rows) == 1 and rows[0].statement == corrected


def test_unrelated_action_cannot_be_bound_to_a_saved_rule(device):
    backend, write = device
    text = "For Iris club, use simplified Chinese."
    action = "Send the draft tomorrow."
    write("bad-state-binding", text + " " + action)
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="bad-state-binding")
    result = finish(packet, [point(packet, text, retained_state_item=action)], unfinished_work=[action])
    assert result["success"] is False and "exactly match" in result["error"]
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))


@pytest.mark.parametrize("outcome", ["not_applicable", "unverified", "contradicted"])
def test_inconsistent_write_decision_keeps_job_open_for_same_source_retry(device, outcome):
    backend, write = device
    text = "For Iris club, use simplified Chinese."
    write("inconsistent-outcome", text)
    packet = tool_handlers.tool_prepare_session_distill(client="codex", scope="all", session_id="inconsistent-outcome")
    bad = finish(packet, [point(packet, text, verification_outcome=outcome)])
    assert bad["success"] is False and "No candidates were staged" in bad["error"], bad
    job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
    assert job.status == "reviewing" and not job.output_candidate_ids
    assert not asyncio.run(backend.structured_store.knowledge_store.list_entries("global"))
    good = finish(packet, [point(packet, text)])
    assert good["success"] and good["readback_verified"] and good["knowledge_changes"], good
