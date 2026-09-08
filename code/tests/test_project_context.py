from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

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


def test_detect_runtime_client_does_not_guess_when_no_signal_exists(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for key in tuple(os.environ):
        if key.startswith("CLAUDE_CODE"):
            monkeypatch.delenv(key, raising=False)

    assert support.detect_runtime_client() is None


def test_auto_host_resolution_is_unavailable_when_no_signal_exists(monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_MEM_CLIENT", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for key in tuple(os.environ):
        if key.startswith("CLAUDE_CODE"):
            monkeypatch.delenv(key, raising=False)

    resolution = support.resolve_host_source("auto")

    assert resolution.host_client == "unknown"
    assert resolution.resolved_client is None
    assert resolution.source_kind == "unavailable"
    assert resolution.adapter_available is False
    assert support.resolve_ingest_client("auto") == "unknown"
    assert support.current_agent_client() == "unknown"


def test_project_state_counts_current_knowledge_without_reading_legacy_entries(
    monkeypatch,
) -> None:
    class FakeKnowledgeStore:
        async def list_entries(self, project_name: str) -> list[object]:
            assert project_name == "demo"
            return [object(), object()]

    class FakeStructuredStore:
        knowledge_store = FakeKnowledgeStore()

        async def list_memory_entries(self, *_args, **_kwargs) -> list[object]:
            raise AssertionError("project status must not read legacy MemoryEntry rows")

        async def get_latest_handoffs(
            self,
            project_name: str,
            *,
            limit: int,
        ) -> list[object]:
            assert (project_name, limit) == ("demo", 100)
            return [object()]

        async def list_confirmed_rules(self, project_name: str) -> list[object]:
            assert project_name == "demo"
            return [object(), object(), object()]

    class FakeVerbatimStore:
        async def list(self, *, limit: int) -> list[object]:
            assert limit == 10000
            return [
                SimpleNamespace(metadata={"project_name": "demo"}),
                SimpleNamespace(metadata={"project_name": "other"}),
            ]

    class FakeBackend:
        def __init__(self) -> None:
            self.structured_store = FakeStructuredStore()
            self.verbatim_store = FakeVerbatimStore()
            self.initialized = False
            self.closed = False

        async def init(self) -> None:
            self.initialized = True

        async def close(self) -> None:
            self.closed = True

    backend = FakeBackend()
    monkeypatch.setattr(support, "LocalMemoryBackend", lambda _data_dir: backend)

    state = asyncio.run(support.project_state("demo"))

    assert backend.initialized is True
    assert backend.closed is True
    assert state == {
        "observations": 1,
        "current_knowledge": 2,
        "task_handoffs": 1,
        "confirmed_rules": 3,
    }
    assert "memory_entries" not in state


def test_wake_budget_reads_current_knowledge_statements() -> None:
    total_tokens, level = support.wake_budget(
        None,
        [
            SimpleNamespace(statement="x" * 40),
            SimpleNamespace(content="legacy content is not current knowledge"),
        ],
        [],
        [],
    )

    assert total_tokens == 10
    assert level == "L0"


def test_suggested_next_step_uses_current_knowledge_count() -> None:
    common = {
        "project_name": "demo",
        "observation_count": 1,
        "claude_sessions": [],
        "cursor_sessions": [],
        "grok_sessions": [],
        "codex_sessions": [],
    }

    empty_command, _empty_reason = support.suggested_next_step(
        current_knowledge_count=0,
        **common,
    )
    ready_command, _ready_reason = support.suggested_next_step(
        current_knowledge_count=1,
        **common,
    )

    assert empty_command == 'MCP search_memory(query="<query>")'
    assert ready_command == 'MCP wake(project_name="demo")'
