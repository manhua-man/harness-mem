from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest



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
