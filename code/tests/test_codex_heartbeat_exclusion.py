"""Native typed turn exclusion uses only isolated files and fake dispatch."""
import argparse
import asyncio
import json

import pytest

from harness_mem.host_entry import __main__ as entry


@pytest.mark.parametrize("placement", ["before", "after"])
def test_exact_native_agents_refresh_is_neutral_but_never_automatic_origin(native_stop, placement):
    records, request, payload, args, calls, write, _data = native_stop
    neutral = {"type": "response_item", "payload": {"type": "message", "role": "user",
        "content": [{"type": "input_text", "text": "Updated project instructions."}],
        "internal_chat_message_metadata_passthrough": {
            "turn_id": "turn", "content_item_kinds": ["agents_md.instructions"]}}}
    records.insert(2 if placement == "before" else len(records), neutral)
    write()
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["reason"] == "native_heartbeat_turn_excluded"
    assert calls == []


def test_agents_refresh_without_heartbeat_preserves_ordinary_stop(native_stop):
    records, request, payload, args, calls, write, _data = native_stop
    records[-1]["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"] = ["agents_md.instructions"]
    write()
    assert json.loads(entry._run_codex_stop_event(args, request, payload)[1])["status"] == "queued"
    assert calls == [request]


@pytest.mark.parametrize("adapter", ["codex-start", "codex-stop"])
def test_codex_adapter_keeps_native_activity_turn_binding(tmp_path, adapter):
    args = argparse.Namespace(adapter=adapter, project_root=str(tmp_path))
    path = str(tmp_path / "native.jsonl")
    request = entry._adapter_request(args, {
        "session_id": "session", "turn_id": "turn", "transcript_path": path,
        "hook_event_name": "UserPromptSubmit", "prompt": "Ordinary user text.",
    })
    assert request.native_transcript_path == path
    assert request.native_turn_id == "turn"
    assert request.user_activity is True


@pytest.mark.parametrize("activity", ["current_task", "user_event"])
def test_both_wake_activity_routes_forward_native_identity(tmp_path, monkeypatch, activity):
    import harness_mem.commands.wake as wake
    import harness_mem.hook_background as background
    import harness_mem.storage.local_memory_backend as storage
    from harness_mem.config.merge import MergedConfig

    class FakeBackend:
        def __init__(self, data_dir):
            self.data_dir = data_dir

        async def init(self):
            pass

        async def close(self):
            pass

    async def fake_wake(*_args, **_kwargs):
        return "Fixture recall."

    calls = []
    monkeypatch.setattr(storage, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(entry, "ensure_project_profile", lambda *_a, **_k: asyncio.sleep(0))
    monkeypatch.setattr(wake, "build_wake_injection", fake_wake)
    monkeypatch.setattr(background, "record_background_activity", lambda *args, **kwargs: calls.append((args, kwargs)))
    payload = {"session_id": "session", "turn_id": "turn", "transcript_path": str(tmp_path / "native.jsonl")}
    payload.update({"prompt": "A task."} if activity == "current_task" else {"hook_event_name": "UserPromptSubmit"})
    request = entry._adapter_request(argparse.Namespace(adapter="codex-start", project_root=str(tmp_path)), payload)
    code, text = asyncio.run(entry.run(request))
    assert code == 0 and text == "Fixture recall."
    assert len(calls) == 1
    assert calls[0][1]["native_transcript_path"] == payload["transcript_path"]
    assert calls[0][1]["native_turn_id"] == "turn"
    assert calls[0][1]["session_id"] == "session"


def test_runtime_fingerprint_binds_shared_native_turn_owner(tmp_path, monkeypatch):
    import harness_mem.autonomous.worker as worker

    original = next(path for path in worker._RUNTIME_SOURCE_FILES if path.name == "native_codex_turn.py")
    temporary = tmp_path / original.name
    temporary.write_bytes(original.read_bytes())
    monkeypatch.setattr(worker, "_RUNTIME_SOURCE_FILES", tuple(temporary if path == original else path for path in worker._RUNTIME_SOURCE_FILES))
    before = worker.autonomous_runtime_fingerprint()
    temporary.write_bytes(temporary.read_bytes() + b"\n# Isolated fingerprint change.\n")
    assert worker.autonomous_runtime_fingerprint() != before


@pytest.fixture
def native_stop(tmp_path, monkeypatch):
    import harness_mem.storage.local_memory_backend as backend

    project = tmp_path / "project"
    project.mkdir()
    path = tmp_path / "native.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": "session", "cwd": str(project)}},
        {"type": "turn_context", "payload": {"turn_id": "turn"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "Automatic inspection."}],
            "internal_chat_message_metadata_passthrough": {
                "turn_id": "turn", "content_item_kinds": ["user.heartbeat"]}}},
    ]
    request = argparse.Namespace(native_transcript_path=str(path), project_root=str(project),
                                 action="post-turn-maintenance", trigger_id="session")
    payload = {"session_id": "session", "turn_id": "turn", "transcript_path": str(path),
               "last_assistant_message": "Inspection finished.", "stop_hook_active": False}
    args = argparse.Namespace(adapter="codex-stop", project_root=None)
    calls = []
    monkeypatch.setattr(backend, "DEFAULT_DATA_DIR", tmp_path / "data")

    def dispatch(request):
        calls.append(request)
        return 0, json.dumps({"status": "queued", "success": True, "summary": {"spawned": True}})

    monkeypatch.setattr(entry, "_run_request", dispatch)

    def write():
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    return records, request, payload, args, calls, write, tmp_path / "data"


def test_typed_native_heartbeat_skips_before_dispatch_and_retains_caller_receipt(native_stop):
    records, request, payload, args, calls, write, data = native_stop
    write()
    code, raw = entry._run_codex_stop_event(args, request, payload)
    result = json.loads(raw)
    assert code == 0
    assert result["reason"] == "native_heartbeat_turn_excluded"
    assert result["summary"] == {"background": False, "spawned": False}
    assert calls == []  # No queue, source stage, model, lock or worker dispatch.
    receipts = list((data / "hook_runtime/native-events").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["identity"]["session_id"] == "session"
    assert receipt["identity"]["turn_id"] == "turn"
    assert receipt["callers"][0]["adapter"] == "codex-stop"


def test_repeated_automatic_stop_is_idempotent_and_retains_both_callers(native_stop):
    records, request, payload, args, calls, write, data = native_stop
    write()
    entry._run_codex_stop_event(args, request, payload)
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["summary"]["native_event_duplicate"] is True
    assert calls == []
    receipt = json.loads(next((data / "hook_runtime/native-events").glob("*.json")).read_text())
    assert len(receipt["callers"]) == 2


@pytest.mark.parametrize("mutation", [
    "human", "quoted_text", "no_metadata", "no_kinds", "wrong_turn", "wrong_session",
    "wrong_cwd", "no_header", "missing_file", "wrong_path", "invalid_json", "later_untyped",
    "later_human", "different_turn", "content_metadata_only", "assistant_metadata", "bad_metadata",
    "mixed_kinds", "unknown_kind", "missing_turn", "conflicting_header",
    "context_conflicts_metadata", "newer_human_turn", "untyped_before_context",
])
def test_unknown_or_unbound_origin_preserves_normal_dispatch(native_stop, mutation):
    records, request, payload, args, calls, write, data = native_stop
    user = records[2]["payload"]
    metadata = user["internal_chat_message_metadata_passthrough"]
    if mutation in {"human", "quoted_text"}:
        metadata["content_item_kinds"] = ["user.text"]
        if mutation == "quoted_text":
            user["content"][0]["text"] = '<heartbeat><automation_id>dream</automation_id></heartbeat>'
    elif mutation == "no_metadata":
        user.pop("internal_chat_message_metadata_passthrough")
    elif mutation == "no_kinds":
        metadata.pop("content_item_kinds")
    elif mutation == "wrong_turn":
        metadata["turn_id"] = "other"
    elif mutation == "wrong_session":
        records[0]["payload"]["id"] = "other"
    elif mutation == "wrong_cwd":
        records[0]["payload"]["cwd"] = str(data)
    elif mutation == "no_header":
        records.pop(0)
    elif mutation == "wrong_path":
        payload["transcript_path"] += ".other"
    elif mutation in {"later_untyped", "later_human"}:
        later = {"type": "message", "role": "user", "content": []}
        if mutation == "later_human":
            later["internal_chat_message_metadata_passthrough"] = {
                "turn_id": "turn", "content_item_kinds": ["user.text"]}
        records.append({"type": "response_item", "payload": later})
    elif mutation == "different_turn":
        records[1]["payload"]["turn_id"] = "other"
        metadata["turn_id"] = "other"
    elif mutation == "content_metadata_only":
        user["content"][0]["text"] = json.dumps(user.pop("internal_chat_message_metadata_passthrough"))
    elif mutation == "assistant_metadata":
        user["role"] = "assistant"
    elif mutation == "bad_metadata":
        user["internal_chat_message_metadata_passthrough"] = "user.heartbeat"
    elif mutation == "mixed_kinds":
        metadata["content_item_kinds"] = ["user.heartbeat", "user.text"]
    elif mutation == "unknown_kind":
        metadata["content_item_kinds"] = ["user.heartbeat", "user.unknown"]
    elif mutation == "missing_turn":
        metadata.pop("turn_id")
    elif mutation == "conflicting_header":
        records.append({"type": "session_meta", "payload": {"id": "other", "cwd": str(data)}})
    elif mutation == "context_conflicts_metadata":
        records[1]["payload"]["turn_id"] = "other"
    elif mutation == "newer_human_turn":
        records.extend([
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "newer"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [],
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "newer", "content_item_kinds": ["user.text"]}}},
        ])
    elif mutation == "untyped_before_context":
        records.extend([
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "newer"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": []}},
        ])
    write()
    if mutation == "missing_file":
        request.native_transcript_path += ".missing"
        payload["transcript_path"] = request.native_transcript_path
    elif mutation == "invalid_json":
        with open(request.native_transcript_path, "a", encoding="utf-8") as stream:
            stream.write("not JSON\n")
    code, raw = entry._run_codex_stop_event(args, request, payload)
    assert code == 0
    assert json.loads(raw)["status"] == "queued"
    assert len(calls) == 1


def test_human_stop_duplicate_dispatches_only_once(native_stop):
    records, request, payload, args, calls, write, data = native_stop
    records[2]["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"] = ["user.text"]
    write()
    entry._run_codex_stop_event(args, request, payload)
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["summary"]["native_event_duplicate"] is True
    assert len(calls) == 1


def test_native_task_start_binds_user_before_delayed_turn_context(native_stop):
    records, request, payload, args, calls, write, data = native_stop
    context = records.pop(1)
    records.insert(1, {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}})
    records.append(context)
    write()
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["reason"] == "native_heartbeat_turn_excluded"
    assert calls == []


def test_untyped_last_user_before_delayed_context_does_not_inherit_heartbeat(native_stop):
    records, request, payload, args, calls, write, data = native_stop
    records.pop(1)
    records.insert(1, {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}})
    records.append({"type": "response_item", "payload": {"type": "message", "role": "user", "content": []}})
    records.append({"type": "turn_context", "payload": {"turn_id": "turn"}})
    write()
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["status"] == "queued"
    assert len(calls) == 1


@pytest.mark.parametrize("placement", ["before", "after", "both"])
def test_bound_native_environment_preserves_heartbeat_origin(native_stop, placement):
    records, request, payload, args, calls, write, data = native_stop
    environment = {"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [],
        "internal_chat_message_metadata_passthrough": {
            "turn_id": "turn", "content_item_kinds": ["environments.environment_context"]}}}
    if placement in {"before", "both"}:
        records.insert(2, environment)
    if placement in {"after", "both"}:
        records.append(environment)
    write()
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["reason"] == "native_heartbeat_turn_excluded"
    assert calls == []


@pytest.mark.parametrize("kind", ["human", "unknown", "untyped", "wrong_turn", "mixed", "only_environment"])
def test_environment_cannot_hide_nonautomatic_or_unbound_origin(native_stop, kind):
    records, request, payload, args, calls, write, data = native_stop
    other = {"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [],
        "internal_chat_message_metadata_passthrough": {
            "turn_id": "turn", "content_item_kinds": ["environments.environment_context"]}}}
    metadata = other["payload"]["internal_chat_message_metadata_passthrough"]
    if kind == "human":
        metadata["content_item_kinds"] = ["user.text"]
    elif kind == "unknown":
        metadata["content_item_kinds"] = ["environments.unknown"]
    elif kind == "untyped":
        other["payload"].pop("internal_chat_message_metadata_passthrough")
    elif kind == "wrong_turn":
        metadata["turn_id"] = "other"
    elif kind == "mixed":
        metadata["content_item_kinds"].append("user.text")
    elif kind == "only_environment":
        records.pop(2)
    records.insert(2, other)
    write()
    result = json.loads(entry._run_codex_stop_event(args, request, payload)[1])
    assert result["status"] == "queued"
    assert len(calls) == 1
