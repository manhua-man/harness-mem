from __future__ import annotations

import argparse
import asyncio
import io
import json
import os

import pytest

import harness_mem.commands.dream as dream_module
import harness_mem.commands.maintenance as maintenance_module
import harness_mem.commands.wake as wake_module
import harness_mem.hook_background as hook_background
import harness_mem.host_entry.__main__ as host_entry
import harness_mem.hook_receipts as hook_receipts
import harness_mem.storage.local_memory_backend as backend_module
from harness_mem.config.merge import MergedConfig
from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.hook_receipts import read_hook_execution_receipt


class FakeBackend:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _args(tmp_path, action: str) -> argparse.Namespace:
    return argparse.Namespace(
        action=action,
        project_root=str(tmp_path),
        source="ide_hook",
        trigger_id="turn-1",
        client=None,
    )


def test_host_entry_wake_start_outputs_wake_text(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_args, **_kwargs: asyncio.sleep(0, result=(None, None)))

    async def fake_wake(_backend, project_name: str) -> str:
        return f"Wake context for {project_name}"

    async def fail_dream(*_args, **_kwargs):
        raise AssertionError("wake-start must not run dream")

    monkeypatch.setattr(wake_module, "build_wake_injection", fake_wake)
    monkeypatch.setattr(dream_module, "dream_auto_tick", fail_dream)

    code, payload = asyncio.run(host_entry.run(_args(tmp_path, "wake-start")))

    assert code == ExitCode.SUCCESS
    assert payload == f"Wake context for {tmp_path.name}"


def test_host_entry_wake_records_current_codex_hook_execution(monkeypatch, tmp_path) -> None:
    hook_path = tmp_path / ".codex" / "hooks.json"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(
        host_entry,
        "ensure_project_profile",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=(None, None)),
    )

    async def fake_wake(_backend, project_name: str) -> str:
        return f"Wake context for {project_name}"

    monkeypatch.setattr(wake_module, "build_wake_injection", fake_wake)
    args = _args(tmp_path, "wake-start")
    args.client = "codex"

    code, _payload = asyncio.run(host_entry.run(args))

    assert code == ExitCode.SUCCESS
    receipt = read_hook_execution_receipt(
        data_dir,
        project_root=tmp_path,
        client="codex",
        action="wake-start",
    )
    assert receipt is not None
    assert receipt["project_name"] == tmp_path.name


def test_host_entry_dream_end_outputs_dream_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_args, **_kwargs: asyncio.sleep(0, result=(None, None)))

    async def fake_dream(_backend, *, project_name: str, **_kwargs):
        return {
            "success": True,
            "status": "completed",
            "project_name": project_name,
            "job_id": "job-1",
            "summary": {"processed": 2},
        }

    async def fail_wake(*_args, **_kwargs):
        raise AssertionError("dream-end must not render wake")

    monkeypatch.setattr(dream_module, "dream_auto_tick", fake_dream)
    monkeypatch.setattr(wake_module, "build_wake_injection", fail_wake)

    code, payload = asyncio.run(host_entry.run(_args(tmp_path, "dream-end")))
    assert code == ExitCode.SUCCESS

    data = json.loads(payload or "{}")
    assert data["action"] == "dream-end"
    assert data["status"] == "completed"
    assert data["items_processed"] == 2
    assert "reflection" not in payload.lower()
    assert "metabolism" not in payload.lower()


def test_host_entry_post_turn_maintenance_outputs_combined_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_args, **_kwargs: asyncio.sleep(0, result=(None, None)))

    async def fake_post_turn(
        _backend,
        *,
        project_name: str,
        project_root: str,
        config,
        source: str,
        trigger_id: str | None = None,
    ):
        return {
            "action": "post-turn-maintenance",
            "success": True,
            "status": "queued",
            "project_name": project_name,
            "project_root": project_root,
            "source": source,
            "trigger_id": trigger_id,
            "evidence_packet": {"success": True, "observation_count": 3},
            "distill_job": {"id": "distill-1", "status": "needs_distill"},
            "summary": {
                "evidence_packet_ready": True,
                "observation_count": 3,
                "distill_queued": True,
                "distill_job_id": "distill-1",
            },
        }

    async def fail_wake(*_args, **_kwargs):
        raise AssertionError("post-turn-maintenance must not render wake")

    monkeypatch.setattr(maintenance_module, "run_post_turn_maintenance", fake_post_turn)
    monkeypatch.setattr(wake_module, "build_wake_injection", fail_wake)
    monkeypatch.setattr(dream_module, "dream_auto_tick", fail_wake)

    code, payload = asyncio.run(host_entry.run(_args(tmp_path, "post-turn-maintenance")))
    assert code == ExitCode.SUCCESS

    data = json.loads(payload or "{}")
    assert data["action"] == "post-turn-maintenance"
    assert data["status"] == "queued"
    assert data["summary"]["observation_count"] == 3
    assert data["summary"]["distill_job_id"] == "distill-1"
    assert "auto_review" not in data
    assert "dream" not in data


def test_host_entry_dispatches_ide_maintenance_without_loading_backend(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    def fake_dispatch(_data_dir, **kwargs):
        captured.update(kwargs)
        return hook_background.BackgroundDispatch(
            spawned=True,
            coalesced=False,
            generation="generation-1",
        )

    monkeypatch.setattr(hook_background, "dispatch_post_turn", fake_dispatch)
    monkeypatch.setattr(
        host_entry,
        "load_merged_config",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("background dispatch must happen before config/backend startup")
        ),
    )
    args = _args(tmp_path, "post-turn-maintenance")
    args.client = "cursor"

    code, payload = asyncio.run(host_entry.run(args))

    assert code == ExitCode.SUCCESS
    data = json.loads(payload or "{}")
    assert data["status"] == "queued"
    assert data["summary"] == {
        "background": True,
        "coalesced": False,
        "spawned": True,
    }
    assert captured["client"] == "cursor"


@pytest.mark.parametrize(
    ("client", "trigger_id"),
    (("hermes", "session-7"), ("antigravity", "conversation-7")),
)
def test_repeated_pre_hooks_skip_wake_for_same_host_session(
    monkeypatch,
    tmp_path,
    client: str,
    trigger_id: str,
) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(
        hook_receipts,
        "read_hook_execution_receipt",
        lambda *_args, **_kwargs: {"trigger_id": trigger_id},
    )

    class FailBackend:
        def __init__(self, _data_dir):
            raise AssertionError("duplicate wake must return before backend startup")

    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FailBackend)
    args = _args(tmp_path, "wake-start")
    args.client = client
    args.trigger_id = trigger_id

    code, payload = asyncio.run(host_entry.run(args))

    assert code == ExitCode.SUCCESS
    assert payload == ""


def test_host_entry_client_override_sets_runtime_host(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(host_entry, "load_merged_config", lambda _root: MergedConfig())
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", FakeBackend)
    monkeypatch.setattr(host_entry, "ensure_project_profile", lambda *_args, **_kwargs: asyncio.sleep(0, result=(None, None)))

    async def fake_wake(_backend, project_name: str) -> str:
        assert os.environ.get("HARNESS_MEM_CLIENT") == "cursor"
        return f"Wake context for {project_name}"

    monkeypatch.setattr(wake_module, "build_wake_injection", fake_wake)
    args = _args(tmp_path, "wake-start")
    args.client = "cursor"
    previous = os.environ.get("HARNESS_MEM_CLIENT")

    code, payload = asyncio.run(host_entry.run(args))

    assert code == ExitCode.SUCCESS
    assert payload == f"Wake context for {tmp_path.name}"
    assert os.environ.get("HARNESS_MEM_CLIENT") == previous


def test_hook_console_entry_reports_its_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        host_entry.main(["--version"])

    assert exc_info.value.code == 0
    assert "harness-mem-hook " in capsys.readouterr().out


def test_codex_stop_adapter_consumes_hook_payload(monkeypatch, tmp_path, capsys) -> None:
    captured: dict[str, object] = {}

    async def fake_run(args):
        captured.update(vars(args))
        return ExitCode.SUCCESS, '{"status": "queued"}'

    monkeypatch.setattr(host_entry, "run", fake_run)
    monkeypatch.setattr(host_entry.sys, "stdin", io.StringIO('{"turn_id": "turn-22"}'))

    assert host_entry.main(
        ["--adapter", "codex-stop", "--project-root", str(tmp_path)]
    ) == ExitCode.SUCCESS

    assert captured["action"] == "post-turn-maintenance"
    assert captured["client"] == "codex"
    assert captured["trigger_id"] == "turn-22"
    assert capsys.readouterr().out == "{}\n"


def test_antigravity_pre_adapter_emits_injected_context(monkeypatch, tmp_path, capsys) -> None:
    captured: dict[str, object] = {}

    async def fake_run(args):
        captured.update(vars(args))
        return ExitCode.SUCCESS, "remember this"

    monkeypatch.setattr(host_entry, "run", fake_run)
    monkeypatch.setattr(
        host_entry.sys,
        "stdin",
        io.StringIO(json.dumps({"workspacePaths": [str(tmp_path)], "conversationId": "conv-7"})),
    )

    assert host_entry.main(
        ["--adapter", "antigravity-pre", "--project-root", str(tmp_path)]
    ) == ExitCode.SUCCESS

    assert captured["action"] == "wake-start"
    assert captured["client"] == "antigravity"
    assert captured["trigger_id"] == "conv-7"
    assert json.loads(capsys.readouterr().out) == {
        "injectSteps": [{"ephemeralMessage": "remember this"}]
    }


def test_hermes_adapter_resolves_project_from_runtime_payload(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run(args):
        captured.update(vars(args))
        return ExitCode.SUCCESS, "runtime-scoped context"

    monkeypatch.setattr(host_entry, "run", fake_run)
    monkeypatch.setattr(
        host_entry.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "hermes-session",
                    "cwd": str(tmp_path),
                }
            )
        ),
    )

    assert host_entry.main(["--adapter", "hermes-pre"]) == ExitCode.SUCCESS

    assert captured["project_root"] == str(tmp_path.resolve())
    assert captured["client"] == "hermes"
    assert json.loads(capsys.readouterr().out) == {
        "context": "runtime-scoped context"
    }
