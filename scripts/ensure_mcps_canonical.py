"""Restore canonical mcps/ descriptors (idempotent PR0 hygiene).

1. Revert incidental ``mcps/grok_com_github`` IDE/MCP header drift.
2. Regenerate ``mcps/harness_mem/tools`` from ``tool_specs``.
3. Fail if any path under ``mcps/`` still differs from HEAD.
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


def _checkout_grok_mcps() -> None:
    result = _run_git("checkout", "--", "mcps/grok_com_github")
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)


def _regenerate_harness_mem_tools() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from harness_mem.mcp.tool_descriptor_export import export_tool_descriptors

    output_dir = REPO_ROOT / "mcps" / "harness_mem" / "tools"
    written = export_tool_descriptors(output_dir)
    print(f"regenerated {len(written)} harness_mem tool descriptor(s)")


def _mcps_diff_names() -> list[str]:
    result = _run_git("diff", "--name-only", "--", "mcps/")
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    print(f"repo: {REPO_ROOT}")
    before = _mcps_diff_names()
    if before:
        print(f"mcps drift before repair: {len(before)} file(s)")
        for path in before[:10]:
            print(f"  - {path}")
        if len(before) > 10:
            print(f"  ... and {len(before) - 10} more")

    _checkout_grok_mcps()
    _regenerate_harness_mem_tools()

    remaining = _mcps_diff_names()
    if remaining:
        print("ERROR: mcps/ still differs from HEAD after canonical repair:", file=sys.stderr)
        for path in remaining:
            print(f"  {path}", file=sys.stderr)
        return 1

    print("OBSERVATION: mcps/ diff empty=YES")
    status = _run_git("status", "--short", "--", "mcps/")
    if status.returncode != 0:
        print(status.stderr or status.stdout, file=sys.stderr)
        return status.returncode
    short = status.stdout.strip()
    print(f"git status --short mcps/:\n{short or '(empty)'}")
    print("OBSERVATION: working tree mcps/ clean=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())