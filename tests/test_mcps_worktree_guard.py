"""Guard against incidental mcps/ descriptor drift in the worktree."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_grok_com_github_mcps_has_no_worktree_diff() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "mcps/grok_com_github"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout.strip(), (
        "mcps/grok_com_github has local diff; revert with: "
        "git checkout -- mcps/grok_com_github"
    )