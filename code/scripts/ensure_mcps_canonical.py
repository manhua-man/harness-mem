"""Verify and regenerate canonical harness-mem MCP descriptors.

Router aggregate snapshots are retired: they mixed unrelated servers and stale
harness-mem schemas. This script refuses their tracked or untracked return.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_ROOT.parent


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


RETIRED_ROUTER_SNAPSHOT_DIRS = (
    CODE_ROOT / "mcps" / "mcp-router",
    CODE_ROOT / "mcps" / "mcp_router",
)


def _retired_router_snapshots() -> list[Path]:
    return [path for path in RETIRED_ROUTER_SNAPSHOT_DIRS if path.exists()]


def _regenerate_harness_mem_tools() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from harness_mem.mcp.tool_descriptor_export import export_tool_descriptors

    output_dir = CODE_ROOT / "mcps" / "harness_mem" / "tools"
    written = export_tool_descriptors(output_dir)
    print(f"regenerated {len(written)} harness_mem tool descriptor(s)")


def _verify_harness_mem_tools() -> list[str]:
    """Return exported descriptors that do not equal the source tool specs."""

    sys.path.insert(0, str(REPO_ROOT))
    from harness_mem.mcp.tool_descriptor_export import (
        read_exported_tool_descriptor,
        tool_descriptor,
    )
    from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES

    output_dir = CODE_ROOT / "mcps" / "harness_mem" / "tools"
    return [
        tool_name
        for tool_name in PUBLIC_MCP_TOOL_NAMES
        if not (output_dir / f"{tool_name}.json").is_file()
        or read_exported_tool_descriptor(output_dir / f"{tool_name}.json")
        != tool_descriptor(tool_name)
    ]


def _mcps_diff_names() -> list[str]:
    result = _run_git("diff", "--name-only", "--", "code/mcps/")
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    print(f"repo: {REPO_ROOT}")
    retired = _retired_router_snapshots()
    if retired:
        print(
            "ERROR: retired Router snapshot directories must not exist:",
            file=sys.stderr,
        )
        for path in retired:
            print(f"  {path.relative_to(CODE_ROOT)}", file=sys.stderr)
        return 1
    _regenerate_harness_mem_tools()
    mismatched = _verify_harness_mem_tools()
    if mismatched:
        print("ERROR: exported descriptors differ from canonical source:", file=sys.stderr)
        for tool_name in mismatched:
            print(f"  {tool_name}.json", file=sys.stderr)
        return 1

    print("OBSERVATION: exported descriptors match canonical source=YES")

    mcps_status = _run_git("status", "--short", "--", "code/mcps/")
    if mcps_status.returncode != 0:
        print(mcps_status.stderr or mcps_status.stdout, file=sys.stderr)
        return mcps_status.returncode
    mcps_short = mcps_status.stdout.strip()
    print(f"git status --short code/mcps/:\n{mcps_short or '(empty)'}")

    diff_check = _run_git("diff", "--check")
    if diff_check.returncode != 0:
        print("git diff --check:", file=sys.stderr)
        print(diff_check.stdout or diff_check.stderr, file=sys.stderr)
        return diff_check.returncode
    check_out = (diff_check.stdout or diff_check.stderr).strip()
    print(f"git diff --check:\n{check_out or '(no whitespace/conflict issues)'}")
    print("OBSERVATION: git diff --check passes=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
