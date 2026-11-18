from __future__ import annotations

import os

import pytest

from harness_mem.autonomous.authorization import (
    background_status,
)
from harness_mem.config.merge import MergedConfig


def test_background_status_requires_enabled_and_available_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _client: "cli-bin",
    )
    assert background_status(None).ready is False
    status = background_status(
        MergedConfig(distill_autonomous_enabled=True), client="codex"
    )
    assert status.ready is True
    assert status.reason == "ok"
    assert background_status(MergedConfig(distill_autonomous_enabled=False)).ready is False


def test_background_status_accepts_runtime_dict_without_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _client: "cli-bin",
    )
    runtime = {
        "distill": {"autonomous": {"enabled": True}},
        "semantic": {
            "execution": {
                "restricted": True,
                "mode": "agent",
            },
        },
    }
    status = background_status(runtime, client="codex")
    assert status.ready is True
    assert status.reason == "ok"

    runtime["distill"]["autonomous"]["enabled"] = False
    assert background_status(runtime).ready is False


def test_background_status_reports_missing_cli_without_turning_background_off(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _client: "",
    )
    status = background_status(
        MergedConfig(distill_autonomous_enabled=True),
        client="opencode",
    )
    assert status.on is True
    assert status.ready is False
    assert status.selected_cli == "opencode"
    assert status.reason == "cli_not_found"


def test_background_status_requires_host_signal_when_cli_is_current(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for key in tuple(os.environ):
        if key.startswith("CLAUDE_CODE"):
            monkeypatch.delenv(key, raising=False)

    status = background_status(MergedConfig(distill_autonomous_enabled=True))

    assert status.on is True
    assert status.ready is False
    assert status.selected_cli is None
    assert status.reason == "host_not_detected"


def test_background_status_keeps_explicit_cli_when_host_is_unknown(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for key in tuple(os.environ):
        if key.startswith("CLAUDE_CODE"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _client: "cli-bin",
    )

    status = background_status(
        {
            "distill": {
                "autonomous": {
                    "enabled": True,
                    "cli": "opencode",
                }
            }
        }
    )

    assert status.ready is True
    assert status.selected_cli == "opencode"
    assert status.reason == "ok"


@pytest.mark.parametrize("host", ("codex", "claude-code", "hermes", "opencode", "antigravity"))
def test_background_readiness_reports_production_cap_limit(host, monkeypatch, capsys):
    from harness_mem.autonomous.authorization import background_on
    from harness_mem.commands.doctor_rendering import _doctor_background_status_block

    monkeypatch.setenv("HARNESS_MEM_CLIENT", host)
    monkeypatch.setattr("harness_mem.autonomous.executors.host_cli._resolve_executable", lambda _: "fake-cli")
    config = MergedConfig(
        distill_autonomous_enabled=True, distill_autonomous_cli=host,
        task_model_budget_max_calls=2, task_model_budget_max_seconds=900,
        task_model_budget_max_input_tokens=100, task_model_budget_max_output_tokens=20,
        task_model_budget_host_max_output_tokens=5,
    )
    assert background_on(config) is True
    for view in (config, config.to_runtime_config()):
        status = background_status(view, client=host)
        assert status.on is True
        assert status.ready is False
        assert status.reason == "host_output_limit_unsupported"
        assert status.selected_cli == host
    _doctor_background_status_block(config)
    output = capsys.readouterr().out
    assert "host_output_limit_unsupported" in output
    assert "no proven hard output token cap" in output
    assert "not found" not in output


def test_background_diagnostics_reports_unset_budget(monkeypatch, capsys):
    from harness_mem.commands.doctor_rendering import _doctor_background_status_block

    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")
    monkeypatch.setattr("harness_mem.autonomous.executors.host_cli._resolve_executable", lambda _: "fake-cli")
    _doctor_background_status_block(MergedConfig(
        distill_autonomous_enabled=True, task_model_budget_max_calls=None,
    ))
    output = capsys.readouterr().out
    assert "bounds_not_configured" in output
    assert "not found" not in output
