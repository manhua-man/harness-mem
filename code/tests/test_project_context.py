from __future__ import annotations

import asyncio
from pathlib import Path

import harness_mem.commands.support as support
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


def test_resolve_project_context_prefers_project_root_over_active_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    monkeypatch.setattr(support, "get_active_project", lambda: "wrong-project")
    monkeypatch.delenv("HARNESS_MEM_PROJECT", raising=False)
    monkeypatch.delenv("HARNESS_MEM_PROJECT_ROOT", raising=False)

    context = support.resolve_project_context(
        None,
        project_root=workspace,
        required=True,
        action_label="test",
    )

    assert context is not None
    assert context.project_name == "servers"
    assert context.project_root == workspace.resolve()
    assert context.project_id == support.stable_project_id(workspace.resolve())
    assert context.source == "project_root"


def test_resolve_project_context_uses_workspace_cwd_before_active_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(support, "get_active_project", lambda: "legacy-project")
    monkeypatch.delenv("HARNESS_MEM_PROJECT", raising=False)
    monkeypatch.delenv("HARNESS_MEM_PROJECT_ROOT", raising=False)

    context = support.resolve_project_context(
        None,
        required=False,
        action_label="test",
    )

    assert context is not None
    assert context.project_name == "workspace"
    assert context.project_root == workspace.resolve()
    assert context.source == "workspace_cwd"


def test_find_project_root_never_relabels_unrelated_cwd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "harness-mem"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    assert support.find_project_root("unrelated-project") is None


def test_ensure_project_profile_persists_root_metadata(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    workspace = tmp_path / "servers"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='servers'\n", encoding="utf-8")

    monkeypatch.setattr(support, "DEFAULT_DATA_DIR", data_dir)

    profile, resolved_root = asyncio.run(
        support.ensure_project_profile("servers", workspace)
    )

    assert profile is not None
    assert resolved_root == workspace.resolve()

    store = LocalProjectProfileStore(data_dir)
    saved = asyncio.run(store.get("servers"))
    assert saved is not None
    assert saved.project_root == str(workspace.resolve())
    assert saved.project_id == support.stable_project_id(workspace.resolve())
    assert saved.display_name == "servers"


def test_resolve_host_source_keeps_cursor_label_without_claude_alias() -> None:
    resolution = support.resolve_host_source("cursor")

    assert resolution.host_client == "cursor"
    assert resolution.resolved_client == "cursor"
    assert resolution.source_kind == "transcript"
    assert resolution.adapter_available is True


def test_resolve_ingest_client_no_longer_aliases_cursor_to_claude() -> None:
    assert support.resolve_ingest_client("cursor") == "cursor"


def test_resolve_host_source_uses_native_grok_adapter() -> None:
    resolution = support.resolve_host_source("grok")

    assert resolution.host_client == "grok"
    assert resolution.resolved_client == "grok"
    assert resolution.source_kind == "transcript"
    assert resolution.adapter_available is True


def test_current_agent_client_prefers_explicit_cursor_env(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "cursor")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    assert support.current_agent_client() == "cursor"


def test_current_agent_client_keeps_explicit_grok_label(monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_MEM_CLIENT", "grok")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    assert support.current_agent_client() == "grok"


def test_current_agent_client_detects_native_codex_rollout(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-123")

    assert support.current_agent_client() == "codex"
