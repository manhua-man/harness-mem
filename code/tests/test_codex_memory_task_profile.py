"""Background JSON decisions must not inherit an interactive coding agent."""
from __future__ import annotations

from contextlib import nullcontext
import copy
import importlib
import io
import json
import os
from pathlib import Path
import queue

import pytest

from harness_mem.autonomous.executors import codex_app_server, host_cli, host_structured_cli
from harness_mem.autonomous.provider import ProviderError


@pytest.fixture
def fake_codex_rpc(tmp_path, monkeypatch):
    """Fake only stdio process I/O; exercise real RPC, attestation and validation."""
    owners = []
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "offline-codex-home"))
    original_which = codex_app_server.shutil.which
    executable_path = tmp_path / "offline-codex-binary"
    executable_path.write_bytes(b"test executable identity; never executed")
    monkeypatch.setattr(
        codex_app_server.shutil, "which",
        lambda name: str(executable_path) if name in {"fixture", "codex-bin"} else original_which(name),
    )
    monkeypatch.setattr(
        host_structured_cli, "_invocation_process_scope",
        lambda _process, **_kwargs: nullcontext(),
    )

    class Output:
        def __init__(self):
            self.lines = queue.Queue()

        def __iter__(self):
            while (line := self.lines.get()) is not None:
                yield line

        def close(self):
            self.lines.put(None)

    def merge(target, values):
        for key, value in values.items():
            if isinstance(value, dict):
                merge(target.setdefault(key, {}), value)
            else:
                target[key] = value

    def install(*, output='{"points":[]}', tool=None, input_tokens=10, output_tokens=2):
        captured = {"commands": [], "requests": [], "lease_events": [], "servers": []}
        captured["profile"] = {
            "model": "chosen-by-operator", "model_provider": "operator-provider",
            "model_reasoning_effort": "high", "service_tier": "priority",
        }

        class Process:
            # No actual PID/handle is used: the process scope is replaced above.
            pid = 123456

            def __init__(self, server, command, cwd, env):
                self.returncode = None
                self.stdout = Output()
                self.stderr = io.StringIO()
                self.stdin = self
                self.thread_count = 0
                self.turn_count = 0
                captured["servers"].append(server)
                captured["commands"].append(command)
                captured.update(command=command, cwd=cwd, env=env)
                settings = command[4:]
                toml = importlib.import_module("tomllib" if os.sys.version_info >= (3, 11) else "tomli")
                config = copy.deepcopy(captured["profile"])
                for index in range(0, len(settings), 2):
                    assert settings[index] == "-c"
                    merge(config, toml.loads(settings[index + 1]))
                path = Path(config["model_instructions_file"])
                captured["instruction_path"] = path
                captured["body"] = path.read_text("utf-8")
                assert path.parent == cwd
                # Native deep merge keeps MCP launch fields, including opaque env.
                for value in config["mcp_servers"].values():
                    value.update(command="fictional-mcp", env={"TOKEN": "fictional-private-value"})
                # ConfigV2 omits this native key; raw layers carry its precedence.
                config.pop("tools", None)
                captured["config_response"] = {"config": config, "layers": [
                    {"config": {"tools": {"experimental_request_user_input": {"enabled": False}}},
                     "disabledReason": None},
                    {"config": {"tools": {"experimental_request_user_input": {"enabled": True}}},
                     "disabledReason": None},
                ]}

            def send(self, message):
                self.stdout.lines.put(json.dumps(message, ensure_ascii=False) + "\n")

            def write(self, line):
                request = json.loads(line)
                captured["requests"].append(request)
                method, params = request["method"], request["params"]

                def reply(result):
                    self.send({"id": request["id"], "result": result})

                def notify(method, **params):
                    self.send({"method": method, "params": params})

                if method == "initialize":
                    reply({"userAgent": "in-memory-test-peer"})
                elif method == "initialized":
                    pass
                elif method == "config/read":
                    assert params["includeLayers"] is True
                    reply(copy.deepcopy(captured["config_response"]))
                elif method == "thread/start":
                    self.thread_count += 1
                    self.thread_id = f"thread-{self.thread_count}"
                    profile = captured["profile"]
                    reply({"thread": {"id": self.thread_id, "ephemeral": True, "path": None, "turns": []},
                           "instructionSources": [], "approvalPolicy": "never", "sandbox": {"type": "readOnly"},
                           "model": profile["model"], "modelProvider": profile["model_provider"],
                           "reasoningEffort": profile["model_reasoning_effort"], "serviceTier": profile["service_tier"]})
                elif method == "mcpServerStatus/list":
                    reply({"data": [], "nextCursor": None})
                elif method == "turn/start":
                    self.turn_count += 1
                    turn_id = f"turn-{self.turn_count}"
                    ids = {"threadId": self.thread_id, "turnId": turn_id}
                    captured["prompt"] = params["input"][0]["text"]
                    reply({"turn": {"id": turn_id, "status": "inProgress", "items": []}})
                    if tool:
                        notify("item/started", **ids, item={"type": tool, "id": "forbidden-tool"})
                    notify("rawResponse/completed", **ids, responseId=f"response-{self.turn_count}", usage={
                        "inputTokens": input_tokens, "outputTokens": output_tokens,
                        "cachedInputTokens": 0, "reasoningOutputTokens": 0,
                        "totalTokens": input_tokens + output_tokens,
                    })
                    item = {"type": "agentMessage", "id": f"answer-{self.turn_count}", "phase": "final_answer", "text": output}
                    notify("item/completed", **ids, item=item)
                    notify("turn/completed", threadId=self.thread_id,
                           turn={"id": turn_id, "status": "completed", "error": None, "items": [item]})
                elif method == "thread/unsubscribe":
                    reply({"status": "unsubscribed"})
                    notify("thread/closed", threadId=params["threadId"])
                elif method == "turn/interrupt":
                    reply({})
                else:
                    raise AssertionError(f"unexpected RPC method: {method}")

            def flush(self):
                pass

            def close(self):
                pass

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                self.stdout.close()
                return 0

        def spawn(server, command, cwd, env):
            captured["lease_events"].append("popen")
            return Process(server, command, cwd, env)

        monkeypatch.setattr(codex_app_server.CodexAppServer, "_spawn", spawn)
        monkeypatch.setattr(codex_app_server, "register_provider_process_lease",
                            lambda *_args, **_kwargs: captured["lease_events"].append("lease") or tmp_path / "lease")
        monkeypatch.setattr(codex_app_server, "release_provider_process_lease",
                            lambda _path: captured["lease_events"].append("release") if _path else None)
        if os.name != "nt":
            monkeypatch.setattr(codex_app_server.os, "killpg", lambda pid, _signal: None if pid == Process.pid else pytest.fail("unexpected PID"))
        owners.append(captured)
        return captured

    yield install
    for captured in owners:
        for server in captured["servers"]:
            server.close()


def test_background_profile_is_call_local_and_keeps_operator_model(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    config = home / "config.toml"
    config.write_text('model="chosen-by-operator"\n[skills]\ninclude_instructions=true\n', encoding="utf-8")
    skill = home / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("The user's existing skill stays installed.", encoding="utf-8")
    before = {p: p.read_bytes() for p in (config, skill)}
    monkeypatch.setenv("CODEX_HOME", str(home))
    values = host_cli._codex_background_overrides(tmp_path / "call")
    overrides = values[1::2]
    assert "skills.include_instructions=false" in overrides
    assert "project_doc_max_bytes=0" in overrides
    assert "features.shell_tool=false" in overrides
    assert "features.hooks=false" in overrides
    assert "tools.experimental_request_user_input.enabled=false" in overrides
    # The budget feature also owns context/evidence retention, not just tools.
    assert not any(value.startswith("features.token_budget=") for value in overrides)
    assert "features.sleep_tool=false" in overrides
    assert 'sandbox_mode="read-only"' in overrides
    assert not any(value.startswith("model=") or "auth" in value for value in overrides)
    assert all(p.read_bytes() == original for p, original in before.items())


def test_codex_decision_replaces_base_instructions_only_for_this_invocation(tmp_path, monkeypatch, fake_codex_rpc):
    home = tmp_path / "home"
    skill = home / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("The user's skill remains installed.", encoding="utf-8")
    config = home / "config.toml"
    config.write_text('model="chosen-by-operator"\n[mcp_servers."server.with.dot"]\ncommand="fictional-mcp"\n', encoding="utf-8")
    project_config = tmp_path / ".codex/config.toml"
    project_config.parent.mkdir()
    project_config.write_text('[mcp_servers.local]\ncommand="fictional-local"\n', encoding="utf-8")
    before = {path: path.read_bytes() for path in (config, skill, project_config)}
    monkeypatch.setenv("CODEX_HOME", str(home))
    provider = host_structured_cli.HostStructuredCliProvider(host_client="codex", executable="fixture")
    captured = fake_codex_rpc()
    result = provider.assimilate({}, runtime_dir=tmp_path / "runtime")
    assert "Do not call tools" in captured["body"]
    assert "memory" in captured["body"]
    start, = [request["params"] for request in captured["requests"] if request["method"] == "thread/start"]
    assert start["baseInstructions"] == captured["body"]
    assert start["ephemeral"] is True
    assert start["approvalPolicy"] == "never"
    assert start["sandbox"] == "read-only"
    assert start["config"]["mcp_servers"] == {
        "server.with.dot": {"enabled": False}, "local": {"enabled": False},
    }
    assert Path(start["cwd"]).parent == tmp_path / "runtime"
    assert result.decision.points == []
    assert result.input_tokens == 10
    assert not list((tmp_path / "runtime").glob("assimilation-*"))
    assert captured["instruction_path"].exists()  # The caller still owns the daemon.
    assert provider.close()["closed"] is True
    assert not captured["instruction_path"].exists()
    assert captured["lease_events"] == ["lease", "popen", "release"]
    assert all(path.read_bytes() == original for path, original in before.items())


@pytest.mark.parametrize("kind", ["commandExecution", "mcpToolCall", "fileChange", "webSearch", "collabAgentToolCall"])
def test_json_decision_rejects_unexpected_tools_before_accepting_output(tmp_path, monkeypatch, fake_codex_rpc, kind):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    provider = host_structured_cli.HostStructuredCliProvider(host_client="codex", executable="fixture")

    captured = fake_codex_rpc(tool=kind)
    with pytest.raises(ProviderError, match="tool") as raised:
        provider.assimilate({}, runtime_dir=tmp_path / "runtime")
    assert raised.value.kind == "unrecoverable"
    assert raised.value.attempt_results[-1].schema_valid is False
    assert raised.value.native_attempts[-1]["model_dispatched"] is True
    assert not any(request["method"] == "thread/unsubscribe" for request in captured["requests"])
    assert captured["lease_events"] == ["lease", "popen", "release"]
