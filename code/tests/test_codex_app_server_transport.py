"""Real stdio and Windows Job regression tests, with no native CLI/model/network.

Run: python -m pytest -q code/tests/test_codex_app_server_transport.py
Only _spawn is substituted; production RPC, process scope, readers and leases run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from harness_mem.autonomous.executors.codex_app_server import CodexAppServer
from harness_mem.autonomous.executors import codex_app_server as transport
from harness_mem.autonomous.executors import host_structured_cli as cli
from harness_mem.autonomous.provider import ProviderError


CONFIG = {
    "model": "operator-model", "model_provider": "operator-provider",
    "model_reasoning_effort": "high", "service_tier": "priority",
    "mcp_servers": {"server.with.dot": {"enabled": False}, "local": {"enabled": False}},
    "features": {"memories": False, "plugins": False, "apps": False, "hooks": False},
    "web_search": "disabled",
}
OVERRIDES = [
    "-c", 'mcp_servers={"server.with.dot"={enabled=false},local={enabled=false}}',
    "-c", 'features={memories=false,plugins=false,apps=false,hooks=false}',
    "-c", 'web_search="disabled"',
]
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}
INSTRUCTIONS = "Only supplied evidence. 不调用工具。\nReturn JSON."
KNOWN = {"input_tokens": 30, "output_tokens": 7, "total_tokens": 37}
UNKNOWN = dict.fromkeys(KNOWN)
PEER = Path(__file__).parent / "support" / "codex_stdio_peer.py"


def _wait_for(path: Path):
    until = time.monotonic() + 5
    while not path.exists():
        assert time.monotonic() < until, f"peer did not create {path.name}"
        time.sleep(0.01)


def _windows_child_exited(pid: int):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 3000) == 0
        finally:
            kernel.CloseHandle(handle)
    else:
        assert ctypes.get_last_error() == 87


@pytest.fixture
def peer_factory(tmp_path, monkeypatch):
    owners = []

    def deny_network(*_args, **_kwargs):
        raise AssertionError("transport tests must not use a network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)

    def create(**plan):
        root = tmp_path / f"peer-{len(owners)}"
        runtime = root / "runtime"
        runtime.mkdir(parents=True)
        signals = root / "witness"
        signals.mkdir()
        plan_path = signals / "plan.json"
        plan_path.write_text(json.dumps({"config": CONFIG, **plan}, ensure_ascii=False), encoding="utf-8")
        # Inherit only OS launch necessities, never accounts, auth or user config.
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH")
               if key in os.environ}
        env["FICTIONAL_PROVIDER_TOKEN"] = plan.get("secret", "fictional-secret")
        env["CODEX_HOME"] = str(root / "private-home")
        monkeypatch.setenv("CODEX_HOME", env["CODEX_HOME"])
        server = CodexAppServer(
            sys.executable, scope_factory=cli._invocation_process_scope,
            remove_directory=cli._remove_runtime_directory, poll_seconds=0.02,
        )
        context = SimpleNamespace(server=server, root=root, runtime=runtime, signals=signals,
                                  env=env, processes=[], commands=[], readers=[])
        owners.append(context)

        def spawn(command, cwd, child_env):
            context.commands.append(command)
            process = subprocess.Popen(
                [sys.executable, "-I", "-u", "-X", "utf8", str(PEER), str(signals),
                 str(plan_path)],
                cwd=cwd, env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="strict",
                creationflags=(subprocess.CREATE_NO_WINDOW | 0x00000004) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            context.processes.append(process)
            return process

        monkeypatch.setattr(server, "_spawn", spawn)
        return context

    yield create
    for context in owners:
        (context.signals / "release-close").touch()
        (context.signals / "release-child").touch()
        context.server.close()
        for process in context.processes:
            assert process.poll() is not None


def _run(context, *, prompt="完整原文\r\nsource payload", seconds=3, heartbeat=None):
    def tick():
        context.readers.extend(thread for thread in context.server._readers if thread not in context.readers)
        if heartbeat is not None:
            heartbeat()

    try:
        text, record = context.server.run(
            runtime_dir=context.runtime, data_dir=context.root / "data", cwd=context.runtime,
            env=context.env, overrides=list(OVERRIDES), instructions=INSTRUCTIONS,
            prompt=prompt, schema=SCHEMA, deadline=time.monotonic() + seconds, heartbeat=tick,
        )
        context.last_record = record
        return text, record
    except ProviderError as error:
        context.last_record = error.native_attempts[-1]
        raise
    finally:
        context.readers.extend(context.server._readers)


def _wire(context, direction="in"):
    path = context.signals / "wire.jsonl"
    return [row["message"] for line in path.read_text("utf-8").splitlines()
            if (row := json.loads(line))["direction"] == direction]


def _assert_clean(context):
    assert all(process.poll() is not None for process in context.processes)
    assert all(not thread.is_alive() for thread in context.readers)
    assert not list(context.runtime.glob("codex-app-server-*")), getattr(context, "last_record", {})
    assert not list(context.runtime.glob("fixture-*"))
    assert not list(context.root.rglob("hook_guard/active/*.json"))
    assert context.server._process is None
    assert context.server._lease is None
    assert context.server._root is None
    assert context.server._resources is None
    assert context.server._stderr_file is None
    assert context.server._readers == []
    assert context.server._cleanup_pending is False


def test_reuses_daemon_with_fresh_ephemeral_threads_and_verbatim_sources(peer_factory):
    sources = ["source\r\n首段 \t\\ \"quote\" " + "完整证据🚀\n" * 5000 + f"END-{i}" for i in range(3)]
    outputs = [json.dumps({"answer": text}, ensure_ascii=False) + "\n " for text in sources]
    context = peer_factory(outputs=outputs)
    records = []
    for source, expected in zip(sources, outputs):
        raw, record = _run(context, prompt=source)
        assert raw.encode("utf-8") == expected.encode("utf-8")
        assert record["response_text_sha256"] == hashlib.sha256(expected.encode()).hexdigest()
        assert record["usage"] == KNOWN
        assert record["thread_closed"] is True
        assert record["requested_profile"] == record["effective_profile"] == {
            key: CONFIG[key] for key in ("model", "model_provider", "model_reasoning_effort", "service_tier")}
        records.append(record)
    assert len(context.processes) == 1
    assert len({record["thread_id"] for record in records}) == 3
    assert len({record["server_epoch"] for record in records}) == 1
    requests = _wire(context)
    assert [row["method"] for row in requests].count("initialize") == 1
    assert not any("resume" in row["method"] or "fork" in row["method"] for row in requests)
    starts = [row["params"] for row in requests if row["method"] == "thread/start"]
    assert len(starts) == 3
    for start in starts:
        assert start == {"cwd": str(context.runtime), "ephemeral": True, "approvalPolicy": "never",
                         "sandbox": "read-only", "baseInstructions": INSTRUCTIONS,
                         "config": {key: CONFIG[key] for key in ("mcp_servers", "features", "web_search")},
                         "experimentalRawEvents": True}
    turns = [row["params"] for row in requests if row["method"] == "turn/start"]
    for turn, source in zip(turns, sources):
        assert turn["input"] == [{"type": "text", "text": source}]
        assert turn["outputSchema"] == SCHEMA
    assert context.commands[0][1:4] == ["app-server", "--listen", "stdio://"]
    assert context.commands[0][4:4 + len(OVERRIDES)] == OVERRIDES
    assert context.server.close()["server_starts"] == 1
    _assert_clean(context)


@pytest.mark.parametrize("mode", ["early", "terminal_reply", "late_usage", "foreign", "duplicate", "two_responses"])
def test_correlates_early_and_duplicate_events_without_summing_cumulative_usage(peer_factory, mode):
    context = peer_factory(mode=mode)
    raw, record = _run(context)
    assert json.loads(raw)["answer"] == "完整 source\r\n终点"
    multiplier = 2 if mode == "two_responses" else 1
    assert record["usage"] == {key: value * multiplier for key, value in KNOWN.items()}
    assert len(record["responses"]) == multiplier


@pytest.mark.parametrize("mode, expected", [
    ("missing_usage", UNKNOWN), ("unknown_suffix", UNKNOWN), ("native_retry", UNKNOWN),
])
def test_missing_response_usage_is_unknown_with_known_prefix_preserved(peer_factory, mode, expected):
    context = peer_factory(mode=mode)
    _, record = _run(context)
    assert record["usage"] == expected
    if mode in {"unknown_suffix", "native_retry"}:
        assert record["known_usage_subtotal"] == KNOWN


@pytest.mark.parametrize("mode", ["early_eof", "early_timeout"])
@pytest.mark.parametrize("unknown_suffix", [False, True])
def test_early_paid_completion_survives_missing_start_reply_without_semantic_authority(
    peer_factory, mode, unknown_suffix,
):
    context = peer_factory(mode=mode, early_unknown_suffix=unknown_suffix)
    with pytest.raises(ProviderError) as raised:
        _run(context, seconds=0.8)
    record, = raised.value.native_attempts
    assert record["thread_id"] == "thread-1"
    assert record["turn_id"] is None
    assert record["terminal"] is None
    assert record["response_text_sha256"] == ""
    assert record["status"] == "failed"
    assert record["usage"] == UNKNOWN
    assert record["known_usage_subtotal"] == KNOWN
    assert record["known_usage_response_count"] == 1
    assert record["unknown_response_usage_count"] == int(unknown_suffix)
    assert [(row["thread_id"], row["turn_id"], row["response_id"])
            for row in record["responses"]] == [
                ("thread-1", "turn-1", "response-1"),
                *([("thread-1", "turn-1", "response-1-unknown")] if unknown_suffix else []),
            ]
    assert [row["method"] for row in _wire(context)].count("turn/start") == 1
    assert len(context.processes) == 1
    _assert_clean(context)


def test_confirmed_start_reply_filters_early_foreign_turn_cost_and_semantics(peer_factory):
    context = peer_factory(mode="early", early_foreign_turn=True)
    text, record = _run(context)
    assert json.loads(text)["answer"] == "完整 source\r\n终点"
    assert record["usage"] == record["known_usage_subtotal"] == KNOWN
    assert [(row["turn_id"], row["response_id"]) for row in record["responses"]] == [
        ("turn-1", "response-1"),
    ]


@pytest.mark.parametrize("mode, message", [
    ("conflict_usage", "Conflicting duplicate native usage"),
    ("conflict_message", "Conflicting duplicate native final item"),
])
def test_conflicting_notifications_fail_without_hidden_resend(peer_factory, mode, message):
    context = peer_factory(mode=mode)
    with pytest.raises(ProviderError, match=message) as raised:
        _run(context)
    assert len(raised.value.native_attempts) == 1
    assert [row["method"] for row in _wire(context)].count("turn/start") == 1
    _assert_clean(context)


@pytest.mark.parametrize("mode", ["eof", "eof_no_usage", "timeout", "heartbeat", "missing_close"])
def test_stream_failures_stop_process_without_hidden_resend(peer_factory, mode):
    context = peer_factory(mode=mode)

    def heartbeat():
        if mode == "heartbeat" and (context.server._active or {}).get("responses"):
            raise RuntimeError("fixture heartbeat failed")

    started = time.monotonic()
    with pytest.raises(ProviderError) as raised:
        _run(context, seconds=0.8, heartbeat=heartbeat)
    assert time.monotonic() - started < 5
    record = raised.value.native_attempts[-1]
    assert record["status"] == "failed"
    assert record["known_usage_subtotal"] == (dict.fromkeys(KNOWN, 0) if mode == "eof_no_usage" else KNOWN)
    if mode != "missing_close":
        assert record["usage"] == UNKNOWN
    assert len(context.processes) == 1
    assert [row["method"] for row in _wire(context)].count("turn/start") == 1
    _assert_clean(context)


def test_thread_closed_notification_is_a_barrier(peer_factory):
    context = peer_factory(hold_close=True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run, context)
        try:
            _wait_for(context.signals / "unsubscribe-ack")
            time.sleep(0.08)
            assert not future.done(), "unsubscribe reply/foreign close must not release thread"
        finally:
            (context.signals / "release-close").touch()
        assert future.result(timeout=4)[1]["thread_closed"] is True


def test_owner_close_kills_startup_child_and_readers_and_releases_lease(peer_factory):
    context = peer_factory(child=True)
    _run(context)
    _wait_for(context.signals / "child.json")
    assert list((context.root / "data").rglob("active/*.json"))
    assert context.server.close()["closed"] is True
    _assert_clean(context)
    if os.name == "nt":
        _windows_child_exited(json.loads((context.signals / "child.json").read_text("utf-8"))["pid"])
    before = len(context.processes)
    with pytest.raises(ProviderError, match="owner is closed"):
        _run(context)
    assert len(context.processes) == before
    assert context.server.close()["closed"] is True


@pytest.mark.skipif(os.name == "nt", reason="requires an actual POSIX session and pipe-holding child")
def test_dead_posix_leader_still_kills_owned_group_and_cleans_pipes(peer_factory):
    context = peer_factory(child=True, mode="dead_leader")
    started = time.monotonic()
    with pytest.raises(ProviderError) as raised:
        _run(context, seconds=0.8)
    assert time.monotonic() - started < 5
    assert raised.value.native_attempts[-1]["model_dispatched"] is False
    assert not any(row["method"] == "turn/start" for row in _wire(context))
    _assert_clean(context)


@pytest.mark.parametrize("absent_group", [False, True])
def test_posix_teardown_signals_dead_leaders_group_and_joins_before_closing(
    monkeypatch, absent_group,
):
    events = []

    def killpg(pid, sig):
        events.append(("killpg", pid, sig))
        if absent_group:
            raise ProcessLookupError("fixture group already absent")

    def stream(name):
        def close():
            assert events.index("join") < len(events)
            events.append(("close", name))
        return SimpleNamespace(close=close)

    server = CodexAppServer(sys.executable, scope_factory=None,
                            remove_directory=None, poll_seconds=0.02)
    monkeypatch.setattr(transport, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(transport, "signal", SimpleNamespace(SIGKILL=9))
    process = SimpleNamespace(pid=123456, poll=lambda: 0,
                              wait=lambda **_kwargs: events.append("wait"),
                              stdin=stream("stdin"), stdout=stream("stdout"), stderr=stream("stderr"))
    server._process = process
    server._readers = [SimpleNamespace(join=lambda **_kwargs: events.append("join"),
                                       is_alive=lambda: False)]
    server._stop(time.monotonic() + 1, None)
    assert events[0] == ("killpg", process.pid, 9)
    assert events[1:3] == ["wait", "join"]
    assert events[3:] == [("close", name) for name in ("stdin", "stdout", "stderr")]
    assert server._process is None


def test_reader_timeout_keeps_ownership_without_closing_busy_streams(monkeypatch):
    closed = []
    blocked = True
    server = CodexAppServer(sys.executable, scope_factory=None,
                            remove_directory=None, poll_seconds=0.02)
    monkeypatch.setattr(transport, "os", SimpleNamespace(name="posix", killpg=lambda *_args: None))
    monkeypatch.setattr(transport, "signal", SimpleNamespace(SIGKILL=9))
    stream = SimpleNamespace(close=lambda: closed.append("pipe"))
    process = SimpleNamespace(pid=123456, wait=lambda **_kwargs: 0,
                              stdin=stream, stdout=stream, stderr=stream)
    server._process = process
    server._stderr_file = SimpleNamespace(close=lambda: closed.append("capture"))
    joins = []
    reader = SimpleNamespace(join=lambda **kwargs: joins.append(kwargs["timeout"]),
                             is_alive=lambda: blocked)
    server._readers = [reader]
    with pytest.raises(ProviderError, match="reader cleanup failed"):
        server._stop(time.monotonic() - 1, None)
    assert closed == []
    assert 0 < joins[0] <= 0.02
    assert server._process is process and server._readers == [reader]
    assert server._stderr_file is not None and server._cleanup_pending is True
    blocked = False
    server._stop(time.monotonic() + 1, None)
    assert closed == ["pipe", "pipe", "pipe", "capture"]
    assert server._process is None and server._stderr_file is None


@pytest.mark.parametrize("blocker", ["directory", "lease"])
def test_reuse_waits_for_retained_cleanup_even_without_process(peer_factory, monkeypatch, blocker):
    context = peer_factory()
    _run(context)
    server = context.server
    old_root, old_lease = server._root, server._lease
    remove = server.remove_directory
    release = transport.release_provider_process_lease
    blocked = True

    def remove_directory(path):
        if blocked and blocker == "directory":
            raise PermissionError("fixture scratch locked")
        remove(path)

    def release_lease(path):
        if blocked and blocker == "lease":
            raise PermissionError("fixture lease locked")
        release(path)

    monkeypatch.setattr(server, "remove_directory", remove_directory)
    monkeypatch.setattr(transport, "release_provider_process_lease", release_lease)
    try:
        with pytest.raises(PermissionError):
            server._stop(time.monotonic() + 1, None)
        assert server._process is None
        assert server._lease == old_lease and old_lease.exists()
        if blocker == "directory":
            assert server._root == old_root and old_root.exists()
        with pytest.raises(ProviderError, match="fixture .* locked"):
            _run(context)
        assert len(context.processes) == 1, "must clean old ownership before another spawn"
        assert server._lease == old_lease and old_lease.exists()
        blocked = False
        _run(context)
        assert len(context.processes) == 2
        assert not old_root.exists() and not old_lease.exists()
        assert server._root != old_root and server._lease != old_lease
        server.close()
        _assert_clean(context)
    finally:
        blocked = False
        server.close()
        remove(old_root)
        release(old_lease)


@pytest.mark.parametrize("resource", ["_resources", "_stderr_file", "_readers"])
def test_reuse_cannot_overwrite_retained_nonprocess_resources(peer_factory, resource):
    context = peer_factory()
    blocked = True

    def close():
        if blocked:
            raise PermissionError("fixture retained resource locked")

    retained = ([SimpleNamespace(join=lambda **_kwargs: None, is_alive=lambda: blocked)]
                if resource == "_readers" else SimpleNamespace(close=close))
    setattr(context.server, resource, retained)
    try:
        with pytest.raises(ProviderError):
            _run(context)
        assert getattr(context.server, resource) is retained
        assert context.processes == []
        blocked = False
        _run(context)
        assert len(context.processes) == 1
        context.server.close()
        _assert_clean(context)
    finally:
        blocked = False


def test_separate_calls_keep_independent_heartbeat_throttles(monkeypatch):
    server = CodexAppServer(sys.executable, scope_factory=None,
                            remove_directory=None, poll_seconds=5)
    now = 0.0
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: now))
    callbacks = []
    seen = {"a": [], "b": []}

    def capture_call(_deadline, heartbeat):
        callbacks.append(heartbeat)
        raise ProviderError("fixture lock waiting captured", kind="transient")

    monkeypatch.setattr(server, "_acquire", capture_call)
    for caller in ("a", "b"):
        with pytest.raises(ProviderError, match="fixture lock waiting captured"):
            server.run(runtime_dir=Path("unused"), data_dir=Path("unused"), cwd=Path("unused"),
                       env={}, overrides=[], instructions=INSTRUCTIONS, prompt=caller, schema=SCHEMA,
                       deadline=100, heartbeat=lambda caller=caller: seen[caller].append(now))
    # Reproduce the adversarial order while both calls retain their own callback.
    server._tick(100, callbacks[0])
    for now in (0.1, 5.1, 10.1, 15.1):
        server._tick(100, callbacks[1])
        now += 0.1
        server._tick(100, callbacks[0])
    assert seen["a"] == pytest.approx([0, 5.2, 10.2, 15.2])
    assert seen["b"] == pytest.approx([0.1, 5.1, 10.1, 15.1])


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str


def test_invalid_schema_retains_completed_attempt_cost(peer_factory, monkeypatch):
    context = peer_factory(outputs=['{"answer":42}'])
    provider = cli.HostStructuredCliProvider(host_client="codex", executable=sys.executable)
    provider._codex_server = context.server
    monkeypatch.setattr(cli, "_codex_background_overrides", lambda _cwd: list(OVERRIDES))
    with pytest.raises(ProviderError, match="invalid fixture JSON") as raised:
        provider._run_codex(runtime_dir=context.runtime, heartbeat=None, decision_model=_Answer,
                            prompt="fixture", temporary_prefix="fixture-", error_label="fixture")
    attempt, = raised.value.attempt_results
    assert attempt.schema_valid is False
    assert (attempt.input_tokens, attempt.output_tokens, attempt.total_tokens) == (30, 7, 37)
    assert attempt.response_sha256 == hashlib.sha256(b'{"answer":42}').hexdigest()
    assert len(raised.value.native_attempts) == 1
    assert len([row for row in _wire(context) if row["method"] == "turn/start"]) == 1
    provider.close()
    _assert_clean(context)


@pytest.mark.parametrize("usage_patch", [
    {"totalTokens": 38}, {"totalTokens": None}, {"inputTokens": True},
    {"outputTokens": -1}, {"cachedInputTokens": 31}, {"reasoningOutputTokens": 8},
    {"cachedInputTokens": False}, {"reasoningOutputTokens": -1},
])
def test_inconsistent_response_usage_cannot_be_reported_as_complete(peer_factory, usage_patch):
    context = peer_factory(usage_patch=usage_patch)
    _, record = _run(context)
    assert record["usage"] == UNKNOWN
    assert record["known_usage_response_count"] == 0
    assert record["unknown_response_usage_count"] == 1
    assert record["known_usage_subtotal"] == dict.fromkeys(KNOWN, 0)


@pytest.mark.parametrize("knobs, message", [
    ({"config_patch": {"web_search": "live"}}, "override unattested"),
    ({"config_patch": {"mcp_servers": {"local": {"enabled": True}}}}, "override unattested"),
    ({"profile_patch": {"model": "substituted-model"}}, "profile mismatch"),
    ({"profile_patch": {"reasoningEffort": "low"}}, "profile mismatch"),
    ({"profile_patch": {"serviceTier": "flex"}}, "profile mismatch"),
    ({"mcp_status": {"data": [{"name": "local", "tools": {"unexpected": {}}}], "nextCursor": None}}, "MCP isolation failed"),
    ({"mcp_status": {"data": [], "nextCursor": "unexamined"}}, "MCP isolation failed"),
    ({"thread_patch": {"turns": [{"id": "prior-turn"}]}}, "inherited history"),
    ({"thread_patch": {"ephemeral": False}}, "ephemeral thread isolation failed"),
    ({"thread_patch": {"path": "fictional-persisted-path"}}, "ephemeral thread isolation failed"),
])
def test_unattested_configuration_or_history_stops_before_inference(peer_factory, knobs, message):
    context = peer_factory(**knobs)
    with pytest.raises(ProviderError, match=message) as raised:
        _run(context)
    assert raised.value.kind == "setup_required"
    assert raised.value.native_attempts[-1]["model_dispatched"] is False
    assert not any(row["method"] == "turn/start" for row in _wire(context))
    _assert_clean(context)


def test_reused_thread_identity_is_rejected_without_a_second_turn(peer_factory):
    context = peer_factory(mode="reused_thread")
    _run(context)
    with pytest.raises(ProviderError, match="ephemeral thread isolation failed"):
        _run(context)
    assert len(context.processes) == 1
    assert [row["method"] for row in _wire(context)].count("turn/start") == 1
    _assert_clean(context)


@pytest.mark.parametrize("mode, message", [
    ("started_only", "no primary final message"), ("tool_activity", "unexpected tool activity"),
])
def test_started_text_is_not_final_and_tool_requests_are_rejected(peer_factory, mode, message):
    context = peer_factory(mode=mode)
    with pytest.raises(ProviderError, match=message):
        _run(context)
    assert [row["method"] for row in _wire(context)].count("turn/start") == 1
    _assert_clean(context)


def test_receipt_hashes_do_not_bind_credentials_in_environment_or_native_config(peer_factory):
    records = []
    for secret in ("fictional-secret-alpha", "fictional-secret-beta"):
        context = peer_factory(secret=secret)
        _, record = _run(context)
        serialized = json.dumps(record, sort_keys=True)
        assert secret not in serialized
        assert hashlib.sha256(secret.encode()).hexdigest() not in serialized
        records.append(record)
    for key in ("native_configuration_sha256", "protocol_sha256", "input_sha256",
                "schema_sha256", "instructions_sha256", "response_text_sha256"):
        assert records[0][key] == records[1][key], f"{key} binds a fictional credential"


@pytest.mark.parametrize("borrowed, fail", [(False, False), (False, True), (True, False), (True, True)])
def test_worker_closes_owned_executor_but_preserves_borrowed_owner(peer_factory, monkeypatch, borrowed, fail):
    from harness_mem.autonomous import worker

    context = peer_factory(child=True)
    _run(context)
    provider = cli.HostStructuredCliProvider(host_client="codex", executable=sys.executable)
    provider._codex_server = context.server
    lifecycle_updates = []
    monkeypatch.setattr(worker, "build_semantic_executor", lambda *_args: provider)

    def fake_batch(_backend, **kwargs):
        chosen = kwargs["provider"] if kwargs["provider"] is not None else kwargs["_create_executor"](None, "codex")
        assert chosen is provider
        if fail:
            raise ProviderError("fixture worker failed", kind="transient")
        return {"success": True, "outcomes": []}

    def receipt(*_args, **kwargs):
        lifecycle_updates.append(kwargs["update"])
        return {"fixture_receipt": True}

    monkeypatch.setattr(worker, "_run_autonomous_distill_batch", fake_batch)
    monkeypatch.setattr(worker, "_write_receipt", receipt)

    def run_batch():
        return worker.run_autonomous_distill_batch(
            SimpleNamespace(data_dir=context.root / "data"), project_name="fictional",
            project_root=context.root, config=None, trigger_id=None, client="codex",
            provider=provider if borrowed else None,
        )

    if fail:
        with pytest.raises(ProviderError, match="fixture worker failed"):
            run_batch()
    else:
        result = run_batch()
        assert result["success"] is True
    if borrowed:
        assert context.processes[0].poll() is None
        assert context.server._lease.exists()
        assert lifecycle_updates == []
        provider.close()
    else:
        assert lifecycle_updates[-1]["provider_lifecycle"]["closed"] is True
        assert lifecycle_updates[-1]["provider_lifecycle"]["server_starts"] == 1
    _assert_clean(context)
    if os.name == "nt":
        _windows_child_exited(json.loads((context.signals / "child.json").read_text("utf-8"))["pid"])
