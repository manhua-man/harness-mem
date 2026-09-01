from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness_mem.autonomous.executors.host_cli import HostCliAgentExecutor
from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.executors.registry import build_semantic_executor
from harness_mem.autonomous.provider import ProviderError
from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.config.merge import MergedConfig, load_merged_config


def _authorized_config() -> MergedConfig:
    return MergedConfig(distill_autonomous_enabled=True)


def _decision_payload() -> dict[str, Any]:
    return {
        "semantic_review": {
            "session_summary": "The session only reported a transient status update.",
            "final_user_request": "Report the current status.",
            "final_outcome": "The status was reported without a durable decision.",
            "last_turn_status": "answered",
            "contradictions": [],
            "unfinished_work": [],
            "evidence_status": "answered",
            "promotion_decision": "no_promotion",
            "zero_candidate_challenge": {
                "version": "v1",
                "source_revision": "sha256:" + "a" * 64,
                "evidence_fidelity": "complete",
                "future_utility": "none",
                "checks": {
                    "user_correction": "absent",
                    "explicit_decision": "absent",
                    "successful_solution": "not_durable",
                    "repeated_failure": "absent",
                    "rule_or_preference": "absent",
                    "reusable_workflow_or_fact": "absent",
                    "version_or_migration": "absent",
                    "unfinished_handoff": "absent",
                },
                "inspected_exchange_refs": [
                    {"exchange_index": 1, "content_sha256": "b" * 64}
                ],
                "conclusion": "no_durable_candidate",
                "rationale": "successful_solution is session-only because no reusable implementation evidence was provided.",
            },
        },
        "candidates": [],
    }


def test_build_semantic_executor_returns_host_agent_when_cli_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_HERMES_EXECUTABLE", "hermes-bin")
    executor = build_semantic_executor(_authorized_config(), "hermes")
    assert isinstance(executor, HostCliAgentExecutor)
    assert executor.host_client == "hermes"
    assert executor._cli is not None


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
        ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE", "hermes-bin", "chat"),
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
    captured: dict[str, Any] = {}
    lease_events: list[str] = []

    class _Process:
        returncode = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            lease_events.append("popen")
            captured["command"] = args[0]
            captured["env"] = kwargs.get("env")

        def communicate(self, input=None, timeout=None):
            del timeout
            captured["prompt"] = input
            command = captured["command"]
            payload = json.dumps(_decision_payload())
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
        "harness_mem.autonomous.executors.host_structured_cli._prepare_isolated_codex_home",
        lambda _dir: (tmp_path / "home", "gpt-test"),
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
        config=_authorized_config(),
    )
    result = provider.decide(
        {"contract_version": "autonomous-distill-manifest-v1"},
        runtime_dir=tmp_path / "runtime",
    )

    assert expected_token in captured["command"]
    assert captured["command"][0] == binary
    assert captured["env"]["HARNESS_MEM_AUTONOMOUS_PROVIDER"] == "1"
    assert isinstance(result.decision, AutonomousDecision)
    assert result.execution_mode == "agent"
    assert result.host_client == host_client
    assert result.provider == f"{host_client}_cli"
    assert "hooks_disabled" not in result.receipt()
    assert "mcp_disabled" not in result.receipt()
    assert "config_isolated" not in result.receipt()
    assert lease_events == ["lease", "popen", "release"]


def test_host_cli_assimilate_does_not_default_to_codex_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_MEM_ASSIMILATION_MODEL", raising=False)
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
        config=_authorized_config(),
    )
    provider.assimilate(
        {"verified_candidates": []},
        runtime_dir=tmp_path / "runtime",
    )

    command = captured["command"]
    assert "gpt-5.6-terra" not in command
    assert "-m" not in command


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
