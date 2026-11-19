from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from harness_mem.mcp.tool_handlers import build_tool_handlers
from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, TOOL_CLUSTERS, _SCHEMAS


def test_mcp_registry_contains_public_tools_only() -> None:
    assert set(_SCHEMAS) == set(PUBLIC_MCP_TOOL_NAMES)
    assert set(TOOL_CLUSTERS) == set(PUBLIC_MCP_TOOL_NAMES)
    assert set(build_tool_handlers()) == set(PUBLIC_MCP_TOOL_NAMES)


@pytest.mark.parametrize(
    "module_name",
    (
        "harness_mem.mcp.read_feedback_handlers",
        "harness_mem.mcp.read_query_support",
        "harness_mem.mcp.read_search_handlers",
        "harness_mem.mcp.read_evidence_handlers",
        "harness_mem.mcp.read_wake_handlers",
        "harness_mem.mcp.status_handlers",
        "harness_mem.mcp.dream_handlers",
        "harness_mem.mcp.distill_handlers",
    ),
)
def test_capability_handler_imports_are_order_independent(module_name: str) -> None:
    """Each split handler module must import in a fresh interpreter."""

    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
