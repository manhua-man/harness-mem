from __future__ import annotations

import harness_mem.commands.wake as wake


def test_auto_sync_runtime_plan_supports_cursor(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "cursor")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    plan = wake._auto_sync_runtime_plan()

    assert plan.runtime_client == "cursor"
    assert plan.sync_client == "cursor"
    assert plan.skip_reason is None


def test_auto_sync_runtime_plan_supports_grok_native_sessions(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "grok")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    plan = wake._auto_sync_runtime_plan()

    assert plan.runtime_client == "grok"
    assert plan.sync_client == "grok"
    assert plan.skip_reason is None


def test_auto_sync_runtime_plan_supports_codex_native_sessions(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "codex")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    plan = wake._auto_sync_runtime_plan()

    assert plan.runtime_client == "codex"
    assert plan.sync_client == "codex"
    assert plan.skip_reason is None


def test_auto_sync_runtime_plan_supports_hermes_native_sessions(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "hermes")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    plan = wake._auto_sync_runtime_plan()

    assert plan.runtime_client == "hermes"
    assert plan.sync_client == "hermes"
    assert plan.skip_reason is None
