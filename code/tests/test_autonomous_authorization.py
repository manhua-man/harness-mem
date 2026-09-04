from __future__ import annotations

import os

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
    assert background_status(
        MergedConfig(distill_autonomous_enabled=True), client="codex"
    ).ready is True
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
    assert background_status(runtime, client="codex").ready is True

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
