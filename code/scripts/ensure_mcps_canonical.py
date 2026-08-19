"""Verify and regenerate canonical harness-mem MCP descriptors.

Router aggregate snapshots are retired: they mixed unrelated servers and stale
harness-mem schemas. This script refuses their tracked or untracked return.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


RETIRED_ROUTER_SNAPSHOT_DIRS = (
    REPO_ROOT / "mcps" / "mcp-router",
    REPO_ROOT / "mcps" / "mcp_router",
)


def _retired_router_snapshots() -> list[Path]:
    return [path for path in RETIRED_ROUTER_SNAPSHOT_DIRS if path.exists()]


def _regenerate_harness_mem_tools() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from harness_mem.mcp.tool_descriptor_export import export_tool_descriptors

    output_dir = REPO_ROOT / "mcps" / "harness_mem" / "tools"
    written = export_tool_descriptors(output_dir)
    print(f"regenerated {len(written)} harness_mem tool descriptor(s)")


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
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    before = _mcps_diff_names()
    if before:
        print(f"mcps drift before repair: {len(before)} file(s)")
        for path in before[:10]:
            print(f"  - {path}")
        if len(before) > 10:
            print(f"  ... and {len(before) - 10} more")

    _regenerate_harness_mem_tools()

    remaining = _mcps_diff_names()
    if remaining:
        print("ERROR: code/mcps/ still differs from HEAD after canonical repair:", file=sys.stderr)
        for path in remaining:
            print(f"  {path}", file=sys.stderr)
        return 1

    print("OBSERVATION: code/mcps/ diff empty=YES")

    mcps_status = _run_git("status", "--short", "--", "code/mcps/")
    if mcps_status.returncode != 0:
        print(mcps_status.stderr or mcps_status.stdout, file=sys.stderr)
        return mcps_status.returncode
    mcps_short = mcps_status.stdout.strip()
    print(f"git status --short code/mcps/:\n{mcps_short or '(empty)'}")
    print("OBSERVATION: working tree code/mcps/ clean=YES")

    full_status = _run_git("status", "--short")
    if full_status.returncode != 0:
        print(full_status.stderr or full_status.stdout, file=sys.stderr)
        return full_status.returncode
    full_short = full_status.stdout.strip()
    print(f"git status --short:\n{full_short or '(empty)'}")
    if full_short:
        print(
            "ERROR: working tree has uncommitted changes outside PR0 repair",
            file=sys.stderr,
        )
        return 1
    print("OBSERVATION: working tree clean=YES")

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
