"""MCP descriptor export CLI."""

from __future__ import annotations

from harness_mem.mcp.tool_descriptor_export import default_export_dir, main


def test_export_cli_writes_canonical_tools(tmp_path) -> None:
    exit_code = main([str(tmp_path)])
    assert exit_code == 0
    assert (tmp_path / "list_candidates.json").exists()


def test_default_export_dir_points_at_harness_mem_tools() -> None:
    path = default_export_dir()
    assert path.name == "tools"
    assert path.parent.name == "harness_mem"
