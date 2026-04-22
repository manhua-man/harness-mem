"""Tests for project profile auto-detection."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = REPO_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile


def test_build_project_profile_detects_php_ts_monorepo():
    fixture_path = WORKSPACE_ROOT / "fixtures" / "php-ts-monorepo"
    profile = build_project_profile(fixture_path, project_name="php-ts-monorepo")

    assert profile.project_name == "php-ts-monorepo"
    assert "php" in profile.stacks
    assert "laravel" in profile.stacks
    assert "typescript" in profile.stacks
    assert "next.js" in profile.stacks or "react" in profile.stacks
    assert profile.key_files
