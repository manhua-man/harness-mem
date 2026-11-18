"""Content-free failure evidence using isolated Hook dependencies only."""
from __future__ import annotations

import argparse
import asyncio
import json
from types import SimpleNamespace

import pytest

import harness_mem.commands.dream_continuation as continuation
import harness_mem.commands.wake as wake
import harness_mem.hook_background as background
import harness_mem.hook_receipts as receipts
import harness_mem.host_entry.__main__ as entry
import harness_mem.storage.local_memory_backend as storage
from harness_mem.config.merge import MergedConfig
from harness_mem.config.errors import ConfigError
from harness_mem.host_entry.exit_codes import ExitCode


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    data = tmp_path / "data"
    closed, schedules = [], []

    class Backend:
        def __init__(self, data_dir):
            assert data_dir == data
            self.data_dir = data_dir

        async def init(self):
            return None

        async def close(self):
            closed.append(True)

    async def profile(*_a, **_kw):
        return None, None

    async def schedule(*_a, **_kw):
        schedules.append(True)
        return {"status": "skipped", "reason": "isolated_fixture"}

    async def render(*_a, **_kw):
        return "Exact ordinary wake output."

    monkeypatch.setattr(storage, "DEFAULT_DATA_DIR", data)
    monkeypatch.setattr(storage, "LocalMemoryBackend", Backend)
    monkeypatch.setattr(entry, "resolve_project_context", lambda *_a, **_kw: SimpleNamespace(
        project_root=tmp_path, project_name="demo"))
    monkeypatch.setattr(entry, "load_merged_config", lambda *_a: MergedConfig())
    monkeypatch.setattr(entry, "ensure_project_profile", profile)
    monkeypatch.setattr(background, "record_background_activity", lambda *_a, **_kw: None)
    monkeypatch.setattr(receipts, "record_hook_execution", lambda *_a, **_kw: None)
    monkeypatch.setattr(continuation, "enqueue_bound_continuation", schedule)
    monkeypatch.setattr(wake, "build_wake_injection", render)
    args = argparse.Namespace(action="wake-start", project_root=str(tmp_path), source="ide_hook",
        trigger_id="fixture-session", client="codex", current_task="Fixture task.")
    return args, data, closed, schedules


def events(data):
    return [json.loads(line) for line in (data / "debug/run-events.ndjson").read_text().splitlines()]


@pytest.mark.parametrize("error", [ValueError, RuntimeError, OSError])
def test_wake_failure_retains_exit_type_and_package_locations_without_source(isolated_hook, monkeypatch, error):
    args, data, closed, schedules = isolated_hook

    async def failure(*_a, **_kw):
        raise error("sensitive original source or database contents")

    monkeypatch.setattr(wake, "build_wake_injection", failure)
    assert asyncio.run(entry.run(args)) == (ExitCode.HOOK_FAILED, None)
    final = events(data)[-1]
    details = final["details"]
    assert final["stage"] == "failed" and details["exit_code"] == int(ExitCode.HOOK_FAILED)
    assert details["failure_owner"] == "wake_injection"
    assert details["exception_type"] == error.__name__
    assert any("host_entry/__main__.py:_run_core:" in location for location in details["exception_locations"])
    assert "sensitive original" not in json.dumps(events(data))
    assert closed == [True] and schedules == [True]


def test_config_failure_retains_owner_without_raw_configuration(isolated_hook, monkeypatch):
    args, data, closed, schedules = isolated_hook

    def failure(*_a, **_kw):
        raise ConfigError("secret configuration value")

    monkeypatch.setattr(entry, "load_merged_config", failure)
    assert asyncio.run(entry.run(args)) == (ExitCode.CONFIG_LOAD_ERROR, None)
    details = events(data)[-1]["details"]
    assert details["exit_code"] == int(ExitCode.CONFIG_LOAD_ERROR)
    assert details["failure_owner"] == "config_load" and details["exception_type"] == "ConfigError"
    assert "secret configuration" not in json.dumps(events(data))
    assert not closed and not schedules


def test_argument_failure_is_distinct_from_wake_or_configuration(isolated_hook, monkeypatch):
    args, data, closed, schedules = isolated_hook
    monkeypatch.setattr(entry, "validate_args", lambda _args: "Fixture validation failure")
    assert asyncio.run(entry.run(args)) == (ExitCode.ARG_VALIDATION_ERROR, None)
    assert events(data)[-1]["details"] == {"failure_owner": "argument_validation", "exit_code": 2}
    assert not closed and not schedules


def test_success_preserves_exact_output_and_has_no_failure_detail(isolated_hook):
    args, data, closed, schedules = isolated_hook
    assert asyncio.run(entry.run(args)) == (ExitCode.SUCCESS, "Exact ordinary wake output.")
    assert events(data)[-1]["status"] == "completed"
    assert "details" not in events(data)[-1]
    assert closed == [True] and schedules == [True]


def test_reused_request_cannot_carry_a_previous_failure_owner(isolated_hook, monkeypatch):
    args, data, _closed, _schedules = isolated_hook
    index = [0]

    async def core(request):
        if not index[0]:
            request._hook_failure_details = {"failure_owner": "wake_injection", "exception_type": "ValueError"}
        index[0] += 1
        return ExitCode.HOOK_FAILED, None

    monkeypatch.setattr(entry, "_run_core", core)
    asyncio.run(entry.run(args))
    asyncio.run(entry.run(args))
    failed = [event for event in events(data) if event["stage"] == "failed"]
    assert failed[0]["details"]["failure_owner"] == "wake_injection"
    assert failed[1]["details"] == {"exit_code": int(ExitCode.HOOK_FAILED)}
