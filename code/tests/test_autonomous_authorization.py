from __future__ import annotations

from harness_mem.autonomous.authorization import (
    background_on,
    background_ready,
    background_status,
)
from harness_mem.config.merge import MergedConfig


def test_background_ready_requires_enabled_and_available_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _client: "cli-bin",
    )
    assert background_ready(None) is False
    assert background_ready(
        MergedConfig(distill_autonomous_enabled=True), client="codex"
    ) is True
    assert background_ready(MergedConfig(distill_autonomous_enabled=False)) is False
    assert background_ready(MergedConfig(semantic_execution_restricted=False)) is False


def test_legacy_restricted_off_counts_as_off() -> None:
    config = MergedConfig(
        distill_autonomous_enabled=True,
        semantic_execution_restricted=False,
    )
    assert background_on(config) is False
    assert background_ready(config) is False
    status = background_status(config)
    assert status.reason == "legacy_restricted_off"
    assert status.legacy_off is True


def test_background_ready_accepts_runtime_dict_without_profile(monkeypatch) -> None:
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
    assert background_ready(runtime, client="codex") is True

    runtime["distill"]["autonomous"]["enabled"] = False
    assert background_ready(runtime) is False

    runtime["distill"]["autonomous"]["enabled"] = True
    runtime["semantic"]["execution"]["restricted"] = False
    assert background_ready(runtime) is False
    assert background_status(runtime).reason == "legacy_restricted_off"


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
