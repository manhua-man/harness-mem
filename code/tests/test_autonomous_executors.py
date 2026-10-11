from __future__ import annotations

import hashlib
import importlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
from typing import Any

import pytest

from harness_mem.autonomous.executors import host_structured_cli
from harness_mem.autonomous.executors import host_cli
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.registry import build_semantic_executor
from harness_mem.autonomous.provider import ProviderError
from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.config.merge import MergedConfig, load_merged_config


@pytest.fixture(autouse=True)
def fake_process_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    # This file mocks Popen; real Windows process containment is tested separately.
    monkeypatch.setattr(
        host_structured_cli, "_invocation_process_scope",
        lambda _process, **_kwargs: nullcontext(),
    )


def test_coerce_json_text_accepts_json_with_trailing_cli_text() -> None:
    raw = '{"points": []}\nHermes finished. usage={"total_tokens": 12}'
    assert host_structured_cli._coerce_json_text(raw) == '{"points": []}'


def test_codex_background_disables_global_and_project_mcps_without_config_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_root = tmp_path / "user-codex"
    project = tmp_path / "fictional-project"
    invocation = project / "runtime" / "call"
    invocation.mkdir(parents=True)
    codex_root.mkdir()
    project.joinpath(".codex").mkdir()
    global_path = codex_root / "config.toml"
    project_path = project / ".codex/config.toml"
    global_path.write_text(
        'model="operator-model"\n[mcp_servers."server.with.dot"]\n'
        'command="fictional-server"\n[mcp_servers."server.with.dot".env]\n'
        'TOKEN="fictional-private-value"\n', encoding="utf-8",
    )
    project_path.write_text('[mcp_servers.local]\ncommand="fictional-local"\n', encoding="utf-8")
    before = [path.read_bytes() for path in (global_path, project_path)]
    monkeypatch.setenv("CODEX_HOME", str(codex_root))
    args = host_cli._codex_background_overrides(invocation)
    import tomllib
    overrides = [tomllib.loads(value) for value in args[1::2]]
    assert overrides[0] == {"mcp_servers": {
        "server.with.dot": {"enabled": False}, "local": {"enabled": False},
    }}
    assert overrides[1] == {"features": {"memories": False}}
    assert overrides[2] == {"web_search": "disabled"}
    assert "operator-model" not in str(args)
    assert "fictional-private-value" not in str(args)
    assert before == [path.read_bytes() for path in (global_path, project_path)]


def test_codex_background_invalid_config_fails_before_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text('mcp_servers = "invalid"', encoding="utf-8")
    with pytest.raises(ProviderError, match="Invalid Codex MCP configuration"):
        host_cli._codex_background_overrides(tmp_path / "invocation")


def test_codex_background_missing_toml_parser_is_a_setup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("", encoding="utf-8")

    def unavailable(_name: str):
        raise ModuleNotFoundError("TOML parser unavailable")

    monkeypatch.setattr(host_cli.importlib, "import_module", unavailable)
    with pytest.raises(ProviderError, match="Cannot inspect") as raised:
        host_cli._codex_background_overrides(tmp_path / "invocation")
    assert raised.value.kind == "setup_required"


def test_codex_background_uses_available_tomli_backport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tomllib
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[mcp_servers.local]\ncommand="fixture"', encoding="utf-8"
    )
    imports: list[str] = []

    def backport(name: str):
        imports.append(name)
        if name == "tomllib":
            raise ModuleNotFoundError("Python predates 3.11")
        return tomllib  # A deterministic stand-in with the backport's API.

    monkeypatch.setattr(host_cli.importlib, "import_module", backport)
    assert "local" in host_cli._codex_background_overrides(tmp_path / "call")[1]
    assert imports == ["tomllib", "tomli"]


@pytest.mark.parametrize("fail_at", [1, 2])
def test_stream_allocation_failure_does_not_register_a_provider_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "fictional-codex-home"))
    leases: list[str] = []
    temporary_file = host_structured_cli.tempfile.TemporaryFile
    calls = 0

    def allocate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("fixture allocation failed")
        return temporary_file(**kwargs)

    monkeypatch.setattr(host_structured_cli.tempfile, "TemporaryFile", allocate)
    monkeypatch.setattr(
        host_structured_cli, "register_provider_process_lease",
        lambda *_args, **_kwargs: leases.append("lease"),
    )
    provider = HostStructuredCliProvider(host_client="codex", executable="fixture")
    with pytest.raises(OSError, match="fixture allocation failed"):
        provider.assimilate({}, runtime_dir=tmp_path / "runtime")
    assert leases == []
    assert not list((tmp_path / "runtime").iterdir())


def _authorized_config() -> MergedConfig:
    return MergedConfig(distill_autonomous_enabled=True)


def test_windows_hermes_shim_resolves_to_native_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows launcher behavior")
    native = (
        Path.home()
        / ".hermes"
        / "hermes-agent"
        / "venv"
        / "Scripts"
        / "hermes.exe"
    )
    if not native.is_file():
        pytest.skip("Hermes native install is not present")
    monkeypatch.delenv("HARNESS_MEM_HERMES_EXECUTABLE", raising=False)
    importlib.reload(host_cli)
    monkeypatch.setattr(host_cli.shutil, "which", lambda _name: r"C:\tools\hermes.CMD")
    assert Path(host_cli._resolve_executable("hermes")) == native


def _decision_payload() -> dict[str, Any]:
    return {
        "review": {
            "summary": "The user selected a durable project storage rule.",
            "final_request": "Use SQLite for local project indexes.",
            "actual_result": "The project storage rule was confirmed.",
            "contradictions": [],
            "unfinished": [],
            "no_candidate_reason": None,
            "not_durable_signals": [],
        },
        "points": [
            {
                "kind": "memory",
                "statement": "The project uses SQLite for local indexes.",
                "condition": None,
                "source_entity": None,
                "target_entity": None,
                "relation_type": None,
                "evidence_basis": "user_statement",
                "exchange_indexes": [1],
                "repository_locator": None,
                "repository_sha256": None,
            }
        ],
    }


def _decision_manifest() -> dict[str, Any]:
    return {
        "contract_version": "autonomous-distill-manifest-v1",
        "semantic_decision_exchanges": [
            {
                "exchange_index": 1,
                "content_sha256": "b" * 64,
                "content": "## E1\nUser request: Use SQLite.",
            }
        ],
    }


def test_build_semantic_executor_returns_host_agent_when_cli_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_HERMES_EXECUTABLE", "hermes-bin")
    executor = build_semantic_executor(_authorized_config(), "hermes")
    assert isinstance(executor, HostStructuredCliProvider)
    assert executor.host_client == "hermes"
    assert executor.timeout_seconds == 300


@pytest.mark.parametrize("current_host", ["cursor", "grok", "antigravity"])
def test_build_semantic_executor_uses_explicit_cli_instead_of_current_host(
    monkeypatch: pytest.MonkeyPatch,
    current_host: str,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_HERMES_EXECUTABLE", "hermes-bin")
    config = MergedConfig(
        distill_autonomous_enabled=True,
        distill_autonomous_cli="hermes",
    )
    executor = build_semantic_executor(config, current_host)
    assert executor.host_client == "hermes"


@pytest.mark.parametrize("current_host", ["cursor", "grok", "antigravity"])
def test_build_semantic_executor_does_not_replace_unsupported_current_host(
    monkeypatch: pytest.MonkeyPatch,
    current_host: str,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_CODEX_EXECUTABLE", "codex-bin")
    with pytest.raises(
        ProviderError,
        match=f"No background CLI is implemented for '{current_host}'",
    ):
        build_semantic_executor(_authorized_config(), current_host)


def test_build_semantic_executor_rejects_disabled_background() -> None:
    config = MergedConfig(distill_autonomous_enabled=False)
    with pytest.raises(ProviderError, match="disabled"):
        build_semantic_executor(config, "codex")


def test_build_semantic_executor_requires_host_cli_when_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_CODEX_EXECUTABLE", "")
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _host: "",
    )
    with pytest.raises(ProviderError, match="CLI executable was not found"):
        build_semantic_executor(_authorized_config(), "codex")


@pytest.mark.parametrize(
    ("host_client", "env_name", "binary", "expected_token"),
    [
        ("codex", "HARNESS_MEM_CODEX_EXECUTABLE", "codex-bin", "exec"),
        ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE", "hermes-bin", "-z"),
        (
            "claude-code",
            "HARNESS_MEM_CLAUDE_EXECUTABLE",
            "claude-bin",
            "--json-schema",
        ),
        ("opencode", "HARNESS_MEM_OPENCODE_EXECUTABLE", "opencode-bin", "run"),
    ],
)
def test_host_cli_invokes_structured_command_for_each_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host_client: str,
    env_name: str,
    binary: str,
    expected_token: str,
) -> None:
    monkeypatch.setenv(env_name, binary)
    monkeypatch.setenv("HARNESS_MEM_DISTILL_MODEL", "must-not-be-forwarded")
    monkeypatch.setenv("HARNESS_MEM_ASSIMILATION_MODEL", "must-not-be-forwarded")
    captured: dict[str, Any] = {}
    lease_events: list[str] = []

    class _Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            lease_events.append("popen")
            captured["command"] = args[0]
            captured["env"] = kwargs.get("env")
            captured["cwd"] = Path(kwargs["cwd"])

        def communicate(self, input=None, timeout=None):
            del timeout
            command = captured["command"]
            payload = json.dumps(_decision_payload())
            if "-z" in command:
                captured["prompt"] = command[command.index("-z") + 1]
                usage_path = command[command.index("--usage-file") + 1]
                Path(usage_path).write_text(
                    json.dumps(
                        {
                            "input_tokens": 100,
                            "output_tokens": 25,
                            "total_tokens": 125,
                        }
                    ),
                    encoding="utf-8",
                )
                return (payload, "")
            captured["prompt"] = input
            if "--output-last-message" in command:
                output_path = command[command.index("--output-last-message") + 1]
                Path(output_path).write_text(payload, encoding="utf-8")
                return ("{}", "")
            if "--output" in command:
                output_path = command[command.index("--output") + 1]
                Path(output_path).write_text(payload, encoding="utf-8")
                return ("{}", "")
            return (
                json.dumps({"structured_output": _decision_payload()}),
                "",
            )

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen",
        _Process,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.register_provider_process_lease",
        lambda *_args, **_kwargs: lease_events.append("lease") or tmp_path / "lease",
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.release_provider_process_lease",
        lambda _path: lease_events.append("release"),
    )

    provider = HostStructuredCliProvider(
        host_client=host_client,
        executable=binary,
    )
    result = provider.decide(
        _decision_manifest(),
        runtime_dir=tmp_path / "runtime",
    )

    assert expected_token in captured["command"]
    assert captured["command"][0] == binary
    assert "--model" not in captured["command"]
    assert "-m" not in captured["command"]
    assert captured["env"]["HARNESS_MEM_AUTONOMOUS_PROVIDER"] == "1"
    assert isinstance(result.decision, AutonomousDecision)
    assert result.host_client == host_client
    assert result.provider == f"{host_client}_cli"
    assert result.model is None
    assert result.receipt()["host_client"] == host_client
    assert lease_events == ["lease", "popen", "release"]
    if host_client == "hermes":
        assert captured["cwd"] == tmp_path / "runtime" / "hermes-cwd"
        assert "--ignore-rules" not in captured["command"]
        assert "--max-turns" not in captured["command"]
        assert "chat" not in captured["command"]
        assert "--run-budget" not in captured["command"]
        assert "--query-file" not in captured["command"]
        assert (
            captured["command"][captured["command"].index("--toolsets") + 1]
            == "context_engine"
        )
        assert captured["env"]["HERMES_SESSION_SOURCE"] == "tool"
        assert captured["prompt"].startswith("Read the complete session evidence")
        assert 'Use this shape: {"review"' in captured["prompt"]
        assert "Every object key and every string value must use ASCII double quotes" in captured["prompt"]
        assert '"$defs"' not in captured["prompt"]
        assert len(captured["prompt"]) < 5000
        assert result.input_sha256 == hashlib.sha256(
            captured["prompt"].encode("utf-8")
        ).hexdigest()
        assert result.total_tokens == 125
    else:
        assert captured["cwd"].parent == tmp_path / "runtime"
    assert result.decision.candidates[0].verification_refs[0].content_sha256 == "b" * 64
    assert result.decision.candidates[0].verification_outcome == "unverified"


def test_host_cli_assimilate_never_overrides_the_cli_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISTILL_MODEL", "must-not-be-forwarded")
    monkeypatch.setenv("HARNESS_MEM_ASSIMILATION_MODEL", "must-not-be-forwarded")
    captured: dict[str, Any] = {}

    class _Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["command"] = args[0]

        def communicate(self, input=None, timeout=None):
            del timeout
            return ('{"points": []}', "")

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen",
        _Process,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.register_provider_process_lease",
        lambda *_args, **_kwargs: tmp_path / "lease",
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.release_provider_process_lease",
        lambda _path: None,
    )

    provider = HostStructuredCliProvider(
        host_client="hermes",
        executable="hermes-bin",
    )
    provider.assimilate(
        {"verified_candidates": []},
        runtime_dir=tmp_path / "runtime",
    )

    command = captured["command"]
    assert "--model" not in command
    assert "-m" not in command


def test_host_cli_classifies_plain_text_http_failure_with_zero_exit_as_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def communicate(self, input=None, timeout=None):
            del input, timeout
            return (
                "API call failed after 3 retries: HTTP 503: "
                "Service temporarily unavailable",
                "",
            )

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen",
        _Process,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.register_provider_process_lease",
        lambda *_args, **_kwargs: tmp_path / "lease",
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.release_provider_process_lease",
        lambda _path: None,
    )

    provider = HostStructuredCliProvider(
        host_client="hermes",
        executable="hermes-bin",
    )
    with pytest.raises(ProviderError) as raised:
        provider.decide(
            _decision_manifest(),
            runtime_dir=tmp_path / "runtime",
        )

    assert raised.value.kind == "transient"
    assert raised.value.exit_code == 1


def test_host_cli_runs_each_phase_in_fresh_invocation_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocations: list[Path] = []

    class _Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.cwd = Path(kwargs["cwd"])
            invocations.append(self.cwd)
            (self.cwd / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)

        def communicate(self, input=None, timeout=None):
            del input, timeout
            if len(invocations) == 1:
                payload = json.dumps(_decision_payload())
            else:
                payload = json.dumps({"points": []})
            return (payload, "")

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.subprocess.Popen",
        _Process,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.register_provider_process_lease",
        lambda *_args, **_kwargs: tmp_path / "lease",
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_structured_cli.release_provider_process_lease",
        lambda _path: None,
    )

    provider = HostStructuredCliProvider(
        host_client="claude-code",
        executable="claude-bin",
    )
    runtime_dir = tmp_path / "runtime"
    provider.decide(
        _decision_manifest(),
        runtime_dir=runtime_dir,
    )
    provider.verify(
        {"candidates": []},
        runtime_dir=runtime_dir,
    )

    assert len(invocations) == 2
    assert invocations[0] != invocations[1]


def test_host_cli_runtime_cleanup_retries_a_short_windows_file_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_rmtree = host_structured_cli.shutil.rmtree
    attempts = 0

    def temporarily_locked(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(32, "file is in use", str(path))
        actual_rmtree(path)

    monkeypatch.setattr(host_structured_cli.shutil, "rmtree", temporarily_locked)
    monkeypatch.setattr(host_structured_cli.time, "sleep", lambda _seconds: None)
    parent = tmp_path / "runtime"
    parent.mkdir()

    with host_structured_cli._temporary_runtime_directory(
        prefix="assimilation-",
        parent=parent,
    ) as invocation_dir:
        (invocation_dir / "decision.json").write_text("{}", encoding="utf-8")

    assert attempts == 2
    assert not invocation_dir.exists()


def test_windows_timeout_terminates_the_cli_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class _Stream:
        def close(self) -> None:
            events.append("close")

    class _Process:
        pid = 1234
        stdin = _Stream()
        stdout = _Stream()
        stderr = _Stream()

        def poll(self):
            events.append("poll")
            return None

        def kill(self) -> None:
            events.append("kill")

        def communicate(self, input=None, timeout=None):
            del input
            events.append(("communicate", timeout))
            return ("", "")

    monkeypatch.setattr(host_structured_cli.os, "name", "nt")
    monkeypatch.setattr(
        host_structured_cli.subprocess,
        "run",
        lambda command, **_kwargs: events.append(command),
    )

    assert host_structured_cli._terminate_process_tree(_Process()) == ("", "")
    assert events[0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert events[1:] == ["poll", "kill", ("communicate", 10)]


def test_legacy_restricted_false_maps_to_enabled_false(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = project / ".harness-mem.toml"
    config_path.write_text(
        """
[distill.autonomous]
enabled = true

[semantic.execution]
profile = "hermes-sub2api"
restricted = false
""".strip(),
        encoding="utf-8",
    )

    merged = load_merged_config(project)
    assert merged.distill_autonomous_enabled is False
