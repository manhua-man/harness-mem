"""End-to-end contract tests: memory_type is exposed (v1.6.0) and filterable
(v1.6.1) across CLI, MCP, and REST.

Per ``openspec/changes/2026-05-17-v160-eval-and-typing/specs/retrieval``:
- memory_type SHALL be present in every memory entry result payload
- memory_type SHALL match the underlying MemoryEntry.memory_type

Per ``openspec/changes/2026-05-19-v161-bucket-budget-and-distill-readonly/specs/retrieval``:
- search SHALL accept a ``memory_type`` filter (list, OR semantics)
- invalid values SHALL surface as 422-class errors at the contract boundary
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


def test_mcp_search_memory_filters_by_memory_type(
    data_dir: Path,
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="convention",
                    content="single quote is the project default",
                    source="manual",
                    memory_type="semantic",
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="bug",
                    content="trailing comma breaks parser single",
                    source="manual",
                    memory_type="episodic",
                )
            )
        )
        mcp_server.set_backend_override(backend)
        try:
            semantic_only = mcp_server.tool_search_memory(
                query="single",
                project_name="demo",
                mode="fts",
                memory_type=["semantic"],
            )
            both = mcp_server.tool_search_memory(
                query="single",
                project_name="demo",
                mode="fts",
                memory_type=["semantic", "episodic"],
            )
            invalid = mcp_server.tool_search_memory(
                query="single",
                project_name="demo",
                memory_type=["unknown"],
            )
        finally:
            mcp_server.set_backend_override(None)
    finally:
        run(backend.close())

    assert {e["memory_type"] for e in semantic_only["memory_entries"]} == {"semantic"}
    assert {e["memory_type"] for e in both["memory_entries"]} == {"semantic", "episodic"}
    assert invalid.get("success") is False
    assert "unknown memory_type" in invalid["error"]


def test_cli_search_filter_rejects_unknown_value(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run(
        cli.cmd_search(
            "demo",
            "anything",
            "fts",
            memory_type=["bogus"],
        )
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown memory_type" in err


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


def test_rest_search_filters_memory_type_v161(rest_client: TestClient) -> None:
    """v1.6.1: passing ``memory_type`` actually filters memory entries.

    The v1.6.0 contract (silently ignore the param) was a transitional
    behavior; v1.6.1 turns it into a real OR-filter. Multiple values are
    accepted as repeated query params.
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
    types = {e["memory_type"] for e in data["memory_entries"]}
    assert types == {"semantic"} or types == set()


def test_rest_search_rejects_unknown_memory_type(rest_client: TestClient) -> None:
    resp = rest_client.get("/search", params={
        "query": "anything",
        "project_name": "demo",
        "scope": "project",
        "memory_type": "unknown",
    })
    assert resp.status_code == 422
    assert "unknown memory_type" in resp.json()["detail"]
