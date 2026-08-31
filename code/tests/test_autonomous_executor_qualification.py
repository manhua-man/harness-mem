from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.autonomous.executors.constants import AGENT_HOST_CLIENTS, host_cli_provider_name
from harness_mem.autonomous.executors.registry import build_semantic_executor
from harness_mem.autonomous.hook_guard import autonomous_provider_hook_reentry_blocked
from harness_mem.config.merge import MergedConfig


def test_agent_host_clients_cover_cli_executors() -> None:
    assert AGENT_HOST_CLIENTS == frozenset(
        {"codex", "claude-code", "hermes", "opencode"}
    )
    assert host_cli_provider_name("codex") == "codex_cli"
    assert host_cli_provider_name("hermes") == "hermes_cli"


def test_hook_guard_blocks_all_host_entry_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_AUTONOMOUS_PROVIDER", "1")
    assert autonomous_provider_hook_reentry_blocked("wake-start") is True
    assert autonomous_provider_hook_reentry_blocked("post-turn-maintenance") is True
    assert autonomous_provider_hook_reentry_blocked("dream-end") is True


def test_build_semantic_executor_requires_cli_for_each_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda _host: "",
    )
    config = MergedConfig(
        distill_autonomous_enabled=True,
    )
    with pytest.raises(Exception):
        build_semantic_executor(config, "hermes")


def test_smoke_report_matches_cli_contract() -> None:
    report_path = Path(__file__).resolve().parents[2] / ".tmp" / "host-cli-smoke-report.json"
    if not report_path.is_file():
        pytest.skip("host CLI smoke report not generated yet")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    assert summary.get("codex") in {"probe_only", "passed"}
    assert summary.get("claude-code") in {"probe_only", "passed"}
    assert summary.get("hermes") in {"probe_only", "passed", "fallback", "blocked"}
    assert summary.get("opencode") in {"probe_only", "blocked", "failed"}
