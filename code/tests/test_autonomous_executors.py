from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from harness_mem.autonomous.executors import host_structured_cli
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.registry import build_semantic_executor
from harness_mem.autonomous.provider import ProviderError
from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.config.merge import MergedConfig, load_merged_config


def _authorized_config() -> MergedConfig:
    return MergedConfig(distill_autonomous_enabled=True)


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
