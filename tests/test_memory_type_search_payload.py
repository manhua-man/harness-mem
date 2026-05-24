"""End-to-end contract tests: memory_type is exposed (v1.6.0) and filterable
(v1.6.1) across the internal command helpers and MCP.

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

from harness_mem import cli
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
