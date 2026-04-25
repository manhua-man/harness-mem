"""Tests for project profile auto-detection."""

from __future__ import annotations

from pathlib import Path

from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def test_build_project_profile_detects_php_ts_monorepo():
    fixture_path = WORKSPACE_ROOT / "fixtures" / "php-ts-monorepo"
    profile = build_project_profile(fixture_path, project_name="php-ts-monorepo")

    assert profile.project_name == "php-ts-monorepo"
    assert "php" in profile.stacks
    assert "laravel" in profile.stacks
    assert "typescript" in profile.stacks
    assert "next.js" in profile.stacks or "react" in profile.stacks
    assert profile.key_files
