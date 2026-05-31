"""MCP stdout cleanliness for the v2.5.2 file_context tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.core.schemas import MemoryEntry, Observation, ProjectProfile
from harness_mem.mcp.server import set_backend_override, tool_file_context
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run

pytestmark = pytest.mark.mcp

PROJECT = "file-context-stdout-project"
RELATIVE_PATH = "harness_mem/mcp/server.py"


async def _seed(backend: LocalMemoryBackend) -> None:
    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(
            project_name=PROJECT,
            description="File-context stdout test project",
            key_files=[RELATIVE_PATH],
        )
    )
    await backend.verbatim_store.save(
        Observation(
            session_id="file-context-stdout",
            client="codex",
            raw_content="Touched harness_mem/mcp/server.py while adding file_context.",
            content_type="transcript",
            metadata={"project_name": PROJECT},
        )
    )
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            project_name=PROJECT,
            category="architecture",
            content="harness_mem/mcp/server.py owns MCP tool registration.",
            source="manual",
        )
    )


def test_tool_file_context_stdout_stays_clean(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    set_backend_override(backend)
    try:
        run(_seed(backend))
        capsys.readouterr()

        payload = tool_file_context(project_name=PROJECT, path=RELATIVE_PATH)
        captured = capsys.readouterr()

        assert payload["success"] is True
        assert payload["item_count"] >= 2
        assert captured.out == ""

        serialized = json.dumps(payload)
        assert isinstance(serialized, str)
        decoded = json.loads(serialized)
        assert decoded["normalized_path"] == RELATIVE_PATH
        assert decoded["cost_hint"]["estimated_tokens"] >= 0
    finally:
        set_backend_override(None)
        run(backend.close())
