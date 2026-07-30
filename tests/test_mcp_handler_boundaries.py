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


def test_capability_handlers_stay_out_of_main_handler_facade() -> None:
    root = Path(__file__).resolve().parents[1]
    mcp = root / "harness_mem" / "mcp"
    modules = {
        name: (mcp / name).read_text(encoding="utf-8")
        for name in (
            "tool_handlers.py",
            "read_handlers.py",
            "read_search_handlers.py",
            "read_evidence_handlers.py",
            "read_wake_handlers.py",
            "status_handlers.py",
            "dream_handlers.py",
            "distill_handlers.py",
            "governance_handlers.py",
        )
    }
    main = modules["tool_handlers.py"]

    assert len(main.splitlines()) < 900
    assert "def tool_search_memory(" not in main
    assert "def tool_get_project_status(" not in main
    assert "def tool_dream_run(" not in main
    assert "def tool_prepare_session_distill(" not in main
    assert "def tool_govern_memory(" not in main
    assert len(modules["read_handlers.py"].splitlines()) < 100
    assert "def tool_search_memory(" in modules["read_search_handlers.py"]
    assert "def tool_timeline(" in modules["read_evidence_handlers.py"]
    assert "def tool_wake(" in modules["read_wake_handlers.py"]
    assert "def tool_get_project_status(" in modules["status_handlers.py"]
    assert "def tool_dream_run(" in modules["dream_handlers.py"]
    assert "def tool_prepare_session_distill(" in modules["distill_handlers.py"]
    assert "def tool_govern_memory(" in modules["governance_handlers.py"]
    assert "from harness_mem.mcp.governance_handlers import tool_govern_memory" in main
    assert "def build_tool_handlers(" in main


@pytest.mark.parametrize(
    "module_name",
    (
        "harness_mem.mcp.read_handlers",
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

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
