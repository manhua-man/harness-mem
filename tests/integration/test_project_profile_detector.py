from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile

pytestmark = pytest.mark.integration

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def test_build_project_profile_detects_php_ts_monorepo():
    fixture_path = WORKSPACE_ROOT / "tests" / "fixtures" / "php-ts-monorepo"
    profile = build_project_profile(fixture_path, project_name="php-ts-monorepo")

    assert profile.project_name == "php-ts-monorepo"
    assert "php" in profile.stacks
    assert "laravel" in profile.stacks
    assert "typescript" in profile.stacks
    assert "next.js" in profile.stacks or "react" in profile.stacks
    assert profile.key_files
