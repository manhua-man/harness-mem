"""Exported mcps/harness_mem/tools/*.json must match tool_specs."""

from __future__ import annotations

from pathlib import Path

from harness_mem.mcp.tool_descriptor_export import read_exported_tool_descriptor, tool_descriptor
from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES


def test_exported_harness_mem_tools_match_tool_specs() -> None:
    tools_dir = Path(__file__).resolve().parents[1] / "mcps" / "harness_mem" / "tools"
    for tool_name in sorted(PUBLIC_MCP_TOOL_NAMES):
        path = tools_dir / f"{tool_name}.json"
        assert path.exists(), f"missing exported descriptor: {path.name}"
        exported = read_exported_tool_descriptor(path)
        assert exported == tool_descriptor(tool_name), f"drift in {tool_name}.json"