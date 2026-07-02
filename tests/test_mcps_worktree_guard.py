"""Guard that entire mcps/ tree matches HEAD and harness export contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness_mem.mcp.tool_descriptor_export import read_exported_tool_descriptor, tool_descriptor
from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES


def test_mcps_tree_is_canonical() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--", "mcps/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert diff.returncode == 0, diff.stderr
    assert not diff.stdout.strip(), (
        "mcps/ has worktree drift; repair with: "
        "python scripts/ensure_mcps_canonical.py"
    )

    tools_dir = repo_root / "mcps" / "harness_mem" / "tools"
    for tool_name in sorted(PUBLIC_MCP_TOOL_NAMES):
        path = tools_dir / f"{tool_name}.json"
        assert path.exists(), f"missing exported descriptor: {path.name}"
        exported = read_exported_tool_descriptor(path)
        assert exported == tool_descriptor(tool_name), f"drift in {tool_name}.json"