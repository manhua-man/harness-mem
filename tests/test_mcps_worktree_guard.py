"""Guard that committed harness MCP descriptors match the export contract."""

from __future__ import annotations

from pathlib import Path

from harness_mem.mcp.tool_descriptor_export import read_exported_tool_descriptor, tool_descriptor
from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES


def test_harness_mem_tool_descriptors_are_canonical() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tools_dir = repo_root / "mcps" / "harness_mem" / "tools"
    exported_names = sorted(path.stem for path in tools_dir.glob("*.json"))
    assert exported_names == sorted(PUBLIC_MCP_TOOL_NAMES)

    for tool_name in sorted(PUBLIC_MCP_TOOL_NAMES):
        path = tools_dir / f"{tool_name}.json"
        exported = read_exported_tool_descriptor(path)
        assert exported == tool_descriptor(tool_name), f"drift in {tool_name}.json"


def test_retired_router_snapshots_do_not_return() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "mcps" / "mcp-router").exists()
    assert not (repo_root / "mcps" / "mcp_router").exists()
