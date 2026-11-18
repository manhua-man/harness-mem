"""Native append races and idle selection, isolated files and fake dispatch only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace

import pytest

from harness_mem import hook_background as background
from harness_mem.native_codex_turn import read_native_codex_turn


def user(kind, *, turn="automatic-turn", role="user", metadata=True):
    payload = {"type": "message", "role": role,
               "content": [{"type": "input_text", "text": "Fixture content; not an origin marker."}]}
    if metadata:
        payload["internal_chat_message_metadata_passthrough"] = {
            "turn_id": turn, "content_item_kinds": kind if isinstance(kind, list) else [kind],
        }
    return {"type": "response_item", "payload": payload,
            "timestamp": datetime.fromtimestamp(115.0, timezone.utc).isoformat()}


@pytest.fixture
def activity(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    path = tmp_path / "native.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": "session", "cwd": str(project)}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "automatic-turn"}},
        user("agents_md.instructions"),
    ]
    data = tmp_path / "data"
    dispatch = background.dispatch_post_turn(data, project_root=project, client="codex",
        source="ide_hook", trigger_id="session", now=100.0, popen=lambda *_a, **_k: object())
    request = background.BackgroundRequest(dispatch.generation, str(project), "codex", "ide_hook", "session", 100.0)

    def write():
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def mark(now=110.0, **kwargs):
        background.record_background_activity(data, project_root=project, client="codex",
            session_id="session", now=now, native_transcript_path=str(path), **kwargs)

    def ready(now):
        return background.load_background_request(data, project_root=project, client="codex",
            ready_only=True, now=now)

    write()
    return data, project, path, records, request, write, mark, ready


def test_native_heartbeat_appended_after_hook_preserves_original_human_stop(activity):
    data, project, path, records, request, write, mark, ready = activity
    mark()
    prefix = read_native_codex_turn(path, session_id="session", project_root=project)
    assert prefix.status == "pending"
    assert ready(131.0) is None  # Old request's idle elapsed, but origin has not landed.
    assert not background.background_request_cancelled(data, request, now=131.0)
    records.append(user("user.heartbeat"))
    write()
    complete = read_native_codex_turn(path, session_id="session", project_root=project)
    assert complete.status == "heartbeat"
    assert complete.binding_sha256 == prefix.binding_sha256  # Appends cannot change the origin binding.
    assert ready(132.0) == request
    assert not background.background_request_cancelled(data, request, now=132.0)
    # The previous scalar activity algorithm cancelled this same request.
    marker = next((data / "hook_runtime/background").glob("*.activity-*.json"))
    stored = json.loads(marker.read_text())
    assert stored["active_at"] > request.requested_at
    assert "Fixture content" not in marker.read_text()


@pytest.mark.parametrize("addition", (
    [user("user.text")], [user("user.heartbeat"), user("user.text")],
    [user("user.text"), user("user.heartbeat")], [user(["user.heartbeat", "user.text"])],
    [user("user.heartbeat", metadata=False)], [user("user.heartbeat", turn="wrong-turn")],
))
def test_human_mixed_untyped_and_wrong_turn_activity_still_cancel(activity, addition):
    data, _project, _path, records, request, write, mark, ready = activity
    mark()
    records.extend(addition)
    write()
    assert ready(111.0) == request  # Returned for retirement, not model dispatch.
    assert background.background_request_cancelled(data, request, now=111.0)


def test_neutral_context_never_establishes_automatic_origin_or_holds_forever(activity):
    data, project, path, records, request, write, mark, ready = activity
    records.append(user("environments.environment_context"))
    write()
    mark()
    assert read_native_codex_turn(path, session_id="session", project_root=project).status == "pending"
    assert ready(139.999) is None
    assert ready(140.0) == request
    assert background.background_request_cancelled(data, request, now=140.0)


def test_repeated_same_pending_wake_cannot_extend_the_activity_window(activity):
    data, _project, _path, _records, request, _write, mark, ready = activity
    mark(110.0)
    mark(135.0)
    assert ready(139.0) is None
    assert ready(140.0) == request
    assert background.background_request_cancelled(data, request, now=140.0)


@pytest.mark.parametrize("change", ("session", "project", "turn", "role", "malformed", "missing", "metadata"))
def test_unproved_native_activity_does_not_gain_a_heartbeat_exemption(activity, change):
    data, project, path, records, request, write, mark, ready = activity
    records.append(user("user.heartbeat"))
    kwargs = {}
    if change == "session":
        records[0]["payload"]["id"] = "other-session"
    elif change == "project":
        records[0]["payload"]["cwd"] = str(project / "elsewhere")
    elif change == "turn":
        kwargs["native_turn_id"] = "another-turn"
    elif change == "role":
        records[-1]["payload"]["role"] = "assistant"
    elif change == "metadata":
        records[-1]["payload"].pop("internal_chat_message_metadata_passthrough")
    write()
    if change == "malformed":
        with path.open("a") as stream:
            stream.write("unfinished JSON")
    elif change == "missing":
        path.unlink()
    mark(**kwargs)
    assert ready(111.0) == request
    assert background.background_request_cancelled(data, request, now=111.0)


def test_a_newer_native_lifecycle_invalidates_the_stored_turn_binding(activity):
    data, _project, _path, records, request, write, mark, ready = activity
    mark()
    records.append(user("user.heartbeat"))
    records.append({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "new-turn"}})
    write()
    assert ready(131.0) == request
    assert background.background_request_cancelled(data, request, now=131.0)


@pytest.mark.parametrize("change", ("binding", "path", "turn", "timestamp", "invalid_json", "deadline_removed"))
def test_tampered_activity_marker_never_automatically_exempts(activity, change):
    data, _project, _path, records, request, write, mark, ready = activity
    mark()
    records.append(user("user.heartbeat"))
    write()
    marker = next((data / "hook_runtime/background").glob("*.activity-*.json"))
    stored = json.loads(marker.read_text())
    if change == "binding":
        stored["native_turn"]["binding_sha256"] = "0" * 64
    elif change == "path":
        stored["native_turn"]["path"] += ".missing"
    elif change == "turn":
        stored["native_turn"]["turn_id"] = "other-turn"
    elif change == "timestamp":
        stored["active_at"] = "not-a-time"
    elif change == "deadline_removed":
        stored.pop("pending_until")
    marker.write_text("bad JSON" if change == "invalid_json" else json.dumps(stored))
    assert ready(131.0) == request
    assert background.background_request_cancelled(data, request, now=131.0)


def test_later_heartbeat_cannot_erase_an_earlier_human_cancellation(activity):
    data, project, path, records, request, write, mark, _ready = activity
    background.record_background_activity(data, project_root=project, client="codex",
        session_id="session", now=110.0)  # Legacy/unproved activity retains ordinary cancellation.
    records.append(user("user.heartbeat"))
    write()
    mark(120.0, native_turn_id="automatic-turn")
    assert background.background_request_cancelled(data, request, now=121.0)
    newer_stop = replace(request, requested_at=115.0)
    assert not background.background_request_cancelled(data, newer_stop, now=121.0)


def test_old_pending_superseded_by_a_new_turn_preserves_cancellation(activity):
    data, _project, _path, records, request, write, mark, _ready = activity
    mark(110.0)
    records.extend([
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "new-turn"}},
        user("user.heartbeat", turn="new-turn"),
    ])
    write()
    mark(120.0)
    assert background.background_request_cancelled(data, request, now=121.0)


@pytest.mark.parametrize("client", ("antigravity", "codex"))
def test_unbound_activity_keeps_existing_host_cancellation(tmp_path, client):
    request = background.BackgroundRequest("request", str(tmp_path), client, "ide_hook", "session", 100.0)
    background.record_background_activity(tmp_path / "data", project_root=tmp_path,
        client=client, session_id="session", now=110.0)
    assert background.background_request_cancelled(tmp_path / "data", request, now=111.0)


@pytest.mark.parametrize("stamp", (145.0, None, "not-a-time", "1970-01-01T00:01:55"))
def test_expired_pending_cannot_be_reopened_by_late_or_unproved_heartbeat_time(activity, stamp):
    data, _project, _path, records, request, write, mark, ready = activity
    mark(110.0)
    assert background.background_request_cancelled(data, request, now=140.0)
    body = user("user.heartbeat")
    if isinstance(stamp, float):
        body["timestamp"] = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    elif stamp is None:
        body.pop("timestamp")
    else:
        body["timestamp"] = stamp
    records.append(body)
    write()
    selected = ready(146.0)
    assert selected.cancelled_by_activity
    assert background.background_request_cancelled(data, selected, now=146.0)


def test_ready_cancel_decision_survives_a_later_append_with_earlier_native_time(activity):
    data, _project, _path, records, request, write, mark, ready = activity
    mark(110.0)
    selected = ready(140.0)
    assert selected.cancelled_by_activity
    records.append(user("user.heartbeat"))  # Valid timestamp115, appended after selection at140.
    write()
    assert background.background_request_cancelled(data, selected, now=141.0)
    # This internal decision neither changes the source generation nor persists.
    assert selected.generation == request.generation
    background._write_request(background._pending_path(
        background._state_paths(data, project_root=Path(request.project_root), client="codex")[0],
        request.generation), selected)
    reloaded = background.load_background_request(data, project_root=Path(request.project_root), client="codex")
    assert not reloaded.cancelled_by_activity


@pytest.mark.parametrize("extra", (
    {"type": "response_item", "payload": None},
    {"type": "response_item", "payload": {"role": "user", "type": "unknown"}},
    {"type": "response_item", "payload": {"role": "user"}},
    {"type": "turn_context", "payload": None},
    {"type": "response_item", "payload": {"type": "message"}},
    {"type": "response_item", "payload": {"type": "message", "role": "unknown-role"}},
))
def test_malformed_native_user_or_lifecycle_envelopes_are_not_pure_heartbeat(activity, extra):
    data, project, path, records, request, write, mark, ready = activity
    records.extend([user("user.heartbeat"), extra])
    write()
    assert read_native_codex_turn(path, session_id="session", project_root=project).status == "unknown"
    mark()
    assert ready(111.0) == request
    assert background.background_request_cancelled(data, request, now=111.0)


def test_old_activity_writer_cannot_erase_newer_pending_turn(activity):
    data, project, _path, _records, request, _write, mark, ready = activity
    mark(120.0)
    background.record_background_activity(data, project_root=project, client="codex",
        session_id="session", now=110.0)
    newer_stop = replace(request, requested_at=115.0)
    assert not background.background_request_cancelled(data, newer_stop, now=131.0)
    assert background._background_activity_state(data, newer_stop, now=131.0) == "pending"


def test_same_session_activity_read_modify_write_is_serialized(activity, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    data, project, _path, records, request, write, mark, _ready = activity
    records.append(user("user.heartbeat"))
    write()
    real = background._record_background_activity_locked
    first_entered, release_first, second_entered = threading.Event(), threading.Event(), threading.Event()

    def observed(*args, **kwargs):
        if kwargs["now"] == 110.0:
            first_entered.set()
            assert release_first.wait(3.0)
        else:
            second_entered.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(background, "_record_background_activity_locked", observed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(background.record_background_activity, data, project_root=project,
            client="codex", session_id="session", now=110.0)
        assert first_entered.wait(3.0)
        second = pool.submit(mark, 120.0)
        assert not second_entered.wait(0.05)
        release_first.set()
        first.result(timeout=3.0)
        second.result(timeout=3.0)
    assert second_entered.is_set()
    assert background.background_request_cancelled(data, request, now=121.0)


def test_activity_without_turn_id_cannot_borrow_a_completed_previous_heartbeat(activity):
    data, project, path, records, request, write, mark, ready = activity
    records.extend([user("user.heartbeat"),
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "automatic-turn"}}])
    write()
    prior = read_native_codex_turn(path, session_id="session", project_root=project, turn_id="automatic-turn")
    assert prior.status == "heartbeat" and prior.completed
    mark()  # New prompt hook has no exact turn ID, new native lifecycle has not landed yet.
    assert ready(111.0) == request
    assert background.background_request_cancelled(data, request, now=111.0)


def test_activity_without_turn_id_cannot_borrow_an_already_visible_heartbeat(activity):
    data, _project, _path, records, request, write, mark, ready = activity
    records.append(user("user.heartbeat"))
    write()
    mark()
    assert ready(111.0) == request
    assert background.background_request_cancelled(data, request, now=111.0)


def test_old_turn_completion_does_not_erase_a_user_record_ahead_of_its_lifecycle(activity):
    _data, project, path, records, _request, write, _mark, _ready = activity
    records.extend([
        user("user.text", turn="new-turn"),
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "automatic-turn"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "new-turn"}},
        user("user.heartbeat", turn="new-turn"),
    ])
    write()
    assert read_native_codex_turn(path, session_id="session", project_root=project, turn_id="new-turn").status == "ordinary"


def test_new_heartbeat_writer_cannot_erase_a_malformed_previous_activity(activity):
    data, _project, _path, records, request, write, mark, _ready = activity
    mark(110.0)
    marker = next((data / "hook_runtime/background").glob("*.activity-*.json"))
    prior = json.loads(marker.read_text())
    prior.pop("active_at")
    prior["pending_until"] = 30.0
    marker.write_text(json.dumps(prior))
    records.append(user("user.heartbeat"))
    write()
    mark(120.0, native_turn_id="automatic-turn")
    assert background.background_request_cancelled(data, request, now=121.0)
