"""Exported mcps/harness_mem/tools/*.json must match tool_specs."""

from __future__ import annotations

import json
from pathlib import Path

from harness_mem.mcp.tool_descriptor_export import read_exported_tool_descriptor, tool_descriptor
from harness_mem.mcp.tool_specs import INTERNAL_MCP_TOOL_NAMES, PUBLIC_MCP_TOOL_NAMES


def test_exported_harness_mem_tools_match_tool_specs() -> None:
    tools_dir = Path(__file__).resolve().parents[1] / "mcps" / "harness_mem" / "tools"
    for tool_name in sorted(PUBLIC_MCP_TOOL_NAMES):
        path = tools_dir / f"{tool_name}.json"
        assert path.exists(), f"missing exported descriptor: {path.name}"
        exported = read_exported_tool_descriptor(path)
        assert exported == tool_descriptor(tool_name), f"drift in {tool_name}.json"


def test_exported_public_descriptors_do_not_reference_internal_tools() -> None:
    tools_dir = Path(__file__).resolve().parents[1] / "mcps" / "harness_mem" / "tools"
    for path in sorted(tools_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, sort_keys=True)
        for internal_name in INTERNAL_MCP_TOOL_NAMES:
            assert internal_name not in serialized, (path.name, internal_name)
