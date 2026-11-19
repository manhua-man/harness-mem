from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import harness_mem.commands.integration_cmds as integration_cmds
from harness_mem.commands import token_estimator
from harness_mem.config.merge import MergedConfig
import harness_mem.commands.support as support_module
import harness_mem.mcp.status_handlers as status_handlers
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.agent_runtime import active_backend
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


@pytest.fixture(autouse=True)
def isolate_user_hook_installation(tmp_path, monkeypatch):
    """Status bootstrap may install user hooks; never let this suite touch a real host."""
    from harness_mem.integration import installer

    original = installer.install_user_hook_suite
    isolated_home = tmp_path / "isolated-user-home"

    def isolated_install(*, home_dir=None, **kwargs):
        target = Path(home_dir).resolve() if home_dir is not None else isolated_home.resolve()
        if not target.is_relative_to(tmp_path.resolve()):
            raise AssertionError("User Hook test target must remain inside tmp_path")
        return original(home_dir=target, **kwargs)

    monkeypatch.setattr(installer, "install_user_hook_suite", isolated_install)
    return isolated_home



@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    monkeypatch.delenv("HARNESS_MEM_MCP_MAINTENANCE", raising=False)

    async def _build():
        backend = LocalMemoryBackend(tmp_path)
        await backend.init()
        return backend

    backend = asyncio.run(_build())
    binding = active_backend.set(backend)
    try:
        yield backend
    finally:
        active_backend.reset(binding)
        asyncio.run(backend.close())


def test_status_bootstrap_user_hooks_stay_in_temporary_home(backend, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = tmp_path / "harness-mem-hook.exe"
    runner.write_text("fixture runner", encoding="utf-8")
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: runner)

    result = status_handlers.tool_get_project_status(project_root=str(workspace), host_client="codex")

    assert result["success"] is True
    hook_file = tmp_path / "isolated-user-home" / ".codex" / "hooks.json"
    hooks = json.loads(hook_file.read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "Stop"}
    assert all(str(runner).replace("\\", "/") in group[0]["hooks"][0]["command"]
               for group in hooks.values())


def test_get_project_status_bootstraps_router_workspace_and_codex_hooks(
    backend,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    isolate_user_hook_installation,
) -> None:
    workspace = tmp_path / "codex-workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    runner = tmp_path / "bin" / "harness-mem-hook.exe"
    runner.parent.mkdir()
    runner.write_text("", encoding="utf-8")

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: runner)
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.delenv("HARNESS_MEM_PROJECT_ROOT", raising=False)

    response = tool_handlers.tool_get_project_status(project_root=str(workspace), host_client='codex')

    assert response is not None
    payload = response
    assert payload == {
        "success": True,
        "project_name": "codex-workspace",
        "message": (
            "Memory storage is ready; Hook files are prepared. "
            "If not yet trusted, review user Hooks in Codex Settings, then start a new task."
        ),
    }
    assert token_estimator.count_tokens(json.dumps(payload)) < 50
    hook_path = isolate_user_hook_installation / ".codex" / "hooks.json"
    assert not (workspace / ".codex" / "hooks.json").exists()
    hook_config = json.loads(hook_path.read_text(encoding="utf-8"))
    wake_command = hook_config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    stop_command = hook_config["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "--adapter codex-start" in wake_command
    assert "--trigger-id codex-session-start" not in wake_command
    assert "codex-stop" in stop_command

    second_response = tool_handlers.tool_get_project_status(project_root=str(workspace), host_client='codex')
    assert second_response is not None
    assert second_response == {
        "success": True,
        "project_name": "codex-workspace",
        "message": (
            "Memory storage is ready; Hook files are prepared. "
            "If not yet trusted, review user Hooks in Codex Settings, then start a new task."
        ),
    }

    profile = asyncio.run(LocalProjectProfileStore(backend.data_dir).get("codex-workspace"))
    assert profile is not None
    assert profile.project_root == str(workspace.resolve())


@pytest.mark.parametrize("host_client", integration_cmds.SUPPORTED_HOOK_CLIENTS)
def test_get_project_status_dispatches_bootstrap_for_every_supported_host(
    backend,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    host_client: str,
) -> None:
    workspace = tmp_path / f"{host_client}-workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    installs: list[tuple[str, str, bool, str]] = []

    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(
        status_handlers,
        "cmd_install_hook_suite",
        lambda client, root, force, *, scope: installs.append((client, root, force, scope)) or 0,
    )

    response = tool_handlers.tool_get_project_status(project_root=str(workspace), host_client=host_client)

    assert response is not None
    payload = response
    assert payload == {
        "success": True,
        "project_name": f"{host_client}-workspace",
        "message": (
            "Memory storage is ready; Hook files are prepared."
            + (" If not yet trusted, review user Hooks in Codex Settings, then start a new task."
               if host_client == "codex" else "")
        ),
    }
    assert installs == [(host_client, str(workspace.resolve()), False, "user")]


def test_get_project_status_reports_hook_setup_failure_without_diagnostics(
    backend,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "failed-hook-workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", lambda *_args, scope: 1)

    response = tool_handlers.tool_get_project_status(project_root=str(workspace), host_client='codex')

    assert response is not None
    assert response == {
        "success": False,
        "project_name": "failed-hook-workspace",
        "message": "Host Hooks could not be prepared. Run diagnostics to identify the cause.",
        "action": "Run python -m harness_mem.cli doctor.",
    }


def test_get_project_status_does_not_report_queue_progress(
    backend,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "pending-workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", lambda *_args, scope: 0)
    monkeypatch.setattr(
        backend.transcript_store,
        "count_pending_distill_jobs",
        lambda _project_name: (_ for _ in ()).throw(
            AssertionError("short readiness must not read queue progress")
        ),
    )

    response = tool_handlers.tool_get_project_status(project_root=str(workspace), host_client='codex')

    assert response is not None
    assert response == {
        "success": True,
        "project_name": "pending-workspace",
        "message": (
            "Memory storage is ready; Hook files are prepared. "
            "If not yet trusted, review user Hooks in Codex Settings, then start a new task."
        ),
    }


def test_project_status_reports_real_file_conflict_and_safe_recovery(
    backend, tmp_path, monkeypatch: pytest.MonkeyPatch, isolate_user_hook_installation,
) -> None:
    workspace = tmp_path / "conflicting-workspace"
    workspace.mkdir()
    hook = isolate_user_hook_installation / ".codex" / "hooks.json"
    runner = tmp_path / "harness-mem-hook.exe"
    runner.write_text("fixture runner", encoding="utf-8")
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(integration_cmds, "verified_hook_runner", lambda: runner)
    assert status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )["success"]
    installed = hook.read_bytes()
    modified = json.loads(installed)
    modified["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 30
    original = json.dumps(modified).encode("utf-8")
    hook.write_bytes(original)
    payload = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert payload["success"] is False
    assert "conflict" in payload["message"]
    assert "preserved" in payload["message"]
    assert "doctor" in payload["action"]
    assert "--scope user" in payload["action"]
    assert str(hook) not in json.dumps(payload)
    assert hook.read_bytes() == original
    hook.write_bytes(installed)
    recovered = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert recovered["success"] is True
    assert "Hook files are prepared" in recovered["message"]
    assert "If not yet trusted" in recovered["message"]
    repeated = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert repeated == recovered


@pytest.mark.parametrize("error, message, action", [
    (PermissionError("private path"), "access was denied", "write access"),
    (RuntimeError("harness-mem-hook is unavailable: private path"),
     "program is unavailable", "environment"),
    (ValueError("invalid configuration: private path"), "could not be read", "before editing"),
    (NotImplementedError("Hook API unavailable: private path"),
     "not available", "supported Agent"),
])
def test_project_status_preserves_known_setup_failure_without_private_detail(
    backend, tmp_path, monkeypatch: pytest.MonkeyPatch, error, message, action,
) -> None:
    workspace = tmp_path / "failure-workspace"
    workspace.mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)

    def unavailable_runner():
        raise error

    monkeypatch.setattr(integration_cmds, "verified_hook_runner", unavailable_runner)
    payload = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert payload["success"] is False
    assert message in payload["message"]
    assert action in payload["action"]
    assert "private path" not in json.dumps(payload)


@pytest.mark.parametrize("stage", ["ensure_profile", "active_project"])
@pytest.mark.parametrize("error_type, message, action", [
    (PermissionError, "access was denied", "write access"),
    (OSError, "opened or saved", "doctor"),
    (ValueError, "could not be read", "before editing"),
])
def test_project_status_profile_failure_is_short_and_stops_hook_setup(
    backend, tmp_path, monkeypatch, stage, error_type, message, action,
) -> None:
    from unittest.mock import AsyncMock, Mock

    workspace = tmp_path / "profile-failure"
    workspace.mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    hook_setup = Mock(side_effect=AssertionError("must not install after profile failure"))
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", hook_setup)
    if stage == "ensure_profile":
        monkeypatch.setattr(support_module, "ensure_project_profile",
                            AsyncMock(side_effect=error_type("private profile path")))
    else:
        monkeypatch.setattr(status_handlers, "set_active_project",
                            Mock(side_effect=error_type("private profile path")))
    result = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert result["success"] is False
    assert message in result["message"]
    assert action in result["action"]
    assert "private profile path" not in json.dumps(result)
    hook_setup.assert_not_called()
    assert not (workspace / ".codex").exists()


def test_project_status_preserves_actual_malformed_profile(backend, tmp_path, monkeypatch) -> None:
    from unittest.mock import Mock

    workspace = tmp_path / "broken-profile"
    workspace.mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    store = LocalProjectProfileStore(backend.data_dir)
    profile_path = store.profiles_dir / "broken-profile.json"
    original = b'{"project_name": "broken-profile", invalid private content'
    profile_path.write_bytes(original)
    hook_setup = Mock(side_effect=AssertionError("must preserve broken settings"))
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", hook_setup)
    result = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert result["success"] is False
    assert "existing files were preserved" in result["message"]
    assert "private content" not in json.dumps(result)
    assert profile_path.read_bytes() == original
    hook_setup.assert_not_called()
    assert not (backend.data_dir / "active_project.txt").exists()


@pytest.mark.parametrize("operation", ["get", "save"])
def test_project_status_profile_store_io_failure_stops_setup(
    backend, tmp_path, monkeypatch, operation,
) -> None:
    from unittest.mock import AsyncMock, Mock

    workspace = tmp_path / "store-io-failure"
    workspace.mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(LocalProjectProfileStore, operation,
                        AsyncMock(side_effect=PermissionError("private profile path")))
    hook_setup = Mock(side_effect=AssertionError("must stop setup"))
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", hook_setup)
    result = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert result["success"] is False
    assert "access was denied" in result["message"]
    assert "private profile path" not in json.dumps(result)
    hook_setup.assert_not_called()


@pytest.mark.parametrize("error_type", [ValueError, PermissionError])
def test_project_status_backend_open_failure_has_safe_recovery(
    backend, tmp_path, monkeypatch, error_type,
) -> None:
    from unittest.mock import Mock

    workspace = tmp_path / "backend-failure"
    workspace.mkdir()
    monkeypatch.setattr(support_module, "DEFAULT_DATA_DIR", backend.data_dir)
    monkeypatch.setattr(status_handlers, "cmd_install_hook_suite", lambda *_, scope: 0)
    monkeypatch.setattr(status_handlers, "_get_backend",
                        Mock(side_effect=error_type("private canonical path")))
    result = status_handlers.tool_get_project_status(
        project_root=str(workspace), host_client="codex",
    )
    assert result["success"] is False
    assert "could not be opened" in result["message"]
    assert "doctor" in result["action"]
    assert "private canonical path" not in json.dumps(result)


def test_get_observations_accepts_o_prefixed_ids(backend) -> None:
    asyncio.run(
        backend.verbatim_store.save(
            Observation(
                id="recent-context-observation-1234",
                session_id="session-1",
                client="cursor",
                raw_content="User: Build the recent context index.",
                content_type="transcript",
                timestamp=datetime(2026, 7, 12, tzinfo=timezone.utc),
                metadata={"project_name": "demo"},
            )
        )
    )

    response = tool_handlers.tool_get_observations(project_name='demo', observation_ids=['O-recent-c'])

    assert response is not None
    payload = response
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["unresolved_ids"] == []
    assert payload["observations"][0]["id"] == "recent-context-observation-1234"


def test_public_governance_does_not_promote_legacy_memory_rows(backend) -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="decision",
        content="The public MCP surface can confirm only through explicit review tools.",
        source="observation:2",
        confidence=0.9,
        status="pending",
    )
    asyncio.run(backend.structured_store.save_memory_entry(entry))

    response = tool_handlers.tool_govern_memory(action='decide', arguments={'kind': 'memory', 'decision': 'confirm', 'candidate_id': entry.id})

    payload = response
    reloaded = asyncio.run(backend.structured_store.get_memory_entry(entry.id))

    assert payload["success"] is False
    assert reloaded is not None
    assert reloaded.status == "pending"


def test_dream_auto_is_enabled_by_default_config() -> None:
    assert MergedConfig().dream_auto_enabled is True
    assert MergedConfig().to_reflection_config()["dream"]["auto"]["enabled"] is True
