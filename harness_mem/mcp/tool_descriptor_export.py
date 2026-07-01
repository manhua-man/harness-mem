"""Export MCP tool descriptors for mcps/harness_mem/tools/*.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, _SCHEMAS


def tool_descriptor(tool_name: str) -> dict[str, Any]:
    """Build one exported MCP tool descriptor from ``tool_specs``."""

    if tool_name not in _SCHEMAS:
        raise KeyError(f"unknown tool: {tool_name}")
    schema = _SCHEMAS[tool_name]
    return {
        "name": tool_name,
        "description": schema["description"],
        "inputSchema": schema["input_schema"],
    }


def export_tool_descriptors(
    output_dir: Path,
    *,
    tool_names: frozenset[str] | None = None,
) -> list[Path]:
    """Write exported tool JSON files and return written paths."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = sorted(tool_names or PUBLIC_MCP_TOOL_NAMES)
    written: list[Path] = []
    for tool_name in names:
        path = output_dir / f"{tool_name}.json"
        path.write_text(
            json.dumps(tool_descriptor(tool_name), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def read_exported_tool_descriptor(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))