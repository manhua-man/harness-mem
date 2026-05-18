"""End-to-end contract tests: memory_type is read-only exposed in search
payloads across CLI, MCP, and REST in v1.6.0.

Per ``openspec/changes/2026-05-17-v160-eval-and-typing/specs/retrieval``:
- memory_type SHALL be present in every memory entry result payload
- memory_type SHALL match the underlying MemoryEntry.memory_type
- v1.6.0 search SHALL NOT consume a memory_type filter parameter
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harness_mem import cli
from harness_mem.api.server import create_app, set_backend_override
from harness_mem.core.schemas import MemoryEntry
from harness_mem.mcp import server as mcp_server
from harness_mem.read_api import serialize_memory_entry_search_result
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


# ---------------------------------------------------------------------------
# Direct serializer contract
# ---------------------------------------------------------------------------


def test_serializer_emits_memory_type_for_typed_entry() -> None:
    entry = MemoryEntry(
        project_name="demo",
        category="bug",
        content="JWT expiry must be validated",
        source="manual",
        memory_type="episodic",
    )
    payload = serialize_memory_entry_search_result(entry, "fts")
    assert payload["memory_type"] == "episodic"
    assert payload["category"] == "bug"  # category MUST NOT be replaced


def test_serializer_defaults_memory_type_for_legacy_object() -> None:
    """Defensive: stub objects without the field still get a stable string."""

    class StubEntry:
        id = "mem_legacy"
        project_name = "demo"
        category = "convention"
        content = "use single quote"
        confidence = 0.8
        tags: list[str] = []
        provenance = None

    payload = serialize_memory_entry_search_result(StubEntry(), "fts")
    assert payload["memory_type"] == "semantic"


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_cli_search_displays_category_and_memory_type(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name="demo",
            category="convention",
            content="single quote is the project default",
            source="manual",
            memory_type="semantic",
        )
        run(backend.structured_store.save_memory_entry(entry))
    finally:
        run(backend.close())

    assert run(cli.cmd_search("demo", "single quote", "fts")) == 0
    output = capsys.readouterr().out
    assert "[convention/semantic]" in output


def test_cli_search_renders_episodic_memory_type(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name="demo",
            category="bug",
            content="trailing comma breaks parser",
            source="manual",
            memory_type="episodic",
        )
        run(backend.structured_store.save_memory_entry(entry))
    finally:
        run(backend.close())

    assert run(cli.cmd_search("demo", "trailing comma", "fts")) == 0
    output = capsys.readouterr().out
    assert "[bug/episodic]" in output


# ---------------------------------------------------------------------------
# MCP contract — exercise tool_search_memory directly
# ---------------------------------------------------------------------------


def test_mcp_search_memory_emits_memory_type(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entry = MemoryEntry(
            project_name="demo",
            category="decision",
            content="Use SQLite FTS5 for local memory search",
            source="manual",
            memory_type="semantic",
        )
        run(backend.structured_store.save_memory_entry(entry))

        # Inject backend into MCP server for this test.
        mcp_server.set_backend_override(backend)
        try:
            response = mcp_server.tool_search_memory(
                query="SQLite FTS5",
                project_name="demo",
                mode="fts",
            )
        finally:
            mcp_server.set_backend_override(None)
    finally:
        run(backend.close())

    entries = response["memory_entries"]
    assert entries, "expected at least one memory_entry result"
    assert entries[0]["memory_type"] == "semantic"
    assert entries[0]["category"] == "decision"


# ---------------------------------------------------------------------------
# REST contract
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_client(data_dir: Path) -> TestClient:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    entry = MemoryEntry(
        project_name="demo",
        category="convention",
        content="single quote is the project default",
        source="manual",
        memory_type="semantic",
    )
    legacy_entry = MemoryEntry(
        project_name="demo",
        category="bug",
        content="trailing comma breaks parser",
        source="manual",
        memory_type="episodic",
    )
    run(backend.structured_store.save_memory_entry(entry))
    run(backend.structured_store.save_memory_entry(legacy_entry))

    app = create_app()
    set_backend_override(backend)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        set_backend_override(None)
        run(backend.close())


def test_rest_search_includes_memory_type(rest_client: TestClient) -> None:
    resp = rest_client.get("/search", params={
        "query": "single quote",
        "project_name": "demo",
        "scope": "project",
        "mode": "fts",
    })
    assert resp.status_code == 200
    data = resp.json()
    entries = data["memory_entries"]
    assert entries, "expected at least one memory entry"
    assert entries[0]["memory_type"] == "semantic"


def test_rest_search_ignores_unknown_memory_type_param(rest_client: TestClient) -> None:
    """v1.6.0: passing memory_type as a query param SHALL NOT filter results.

    v1.6.1 introduces actual filtering. Today the param is silently ignored
    so that older clients can preview the field without breaking when the
    filter is later added.
    """
    resp = rest_client.get("/search", params={
        "query": "single quote OR trailing comma",
        "project_name": "demo",
        "scope": "project",
        "mode": "fts",
        "memory_type": "semantic",
    })
    assert resp.status_code == 200
    data = resp.json()
    types = sorted({e["memory_type"] for e in data["memory_entries"]})
    # Both episodic and semantic results come back even when filter requested
    # — confirms no filter is in effect at v1.6.0.
    assert "semantic" in types
    assert "episodic" in types
