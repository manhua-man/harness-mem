from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile

pytestmark = pytest.mark.integration


def _fixture_path(name: str) -> Path:
    test_file = Path(__file__).resolve()
    for parent in test_file.parents:
        candidate = parent / "tests" / "fixtures" / name
        if candidate.exists():
            return candidate
    raise AssertionError(f"Fixture not found: {name}")


def test_build_project_profile_detects_php_ts_monorepo():
    fixture_path = _fixture_path("php-ts-monorepo")
    profile = build_project_profile(fixture_path, project_name="php-ts-monorepo")

    assert profile.project_name == "php-ts-monorepo"
    assert "php" in profile.stacks
    assert "laravel" in profile.stacks
    assert "typescript" in profile.stacks
    assert "next.js" in profile.stacks or "react" in profile.stacks
    assert profile.key_files


def test_build_project_profile_detects_unity_from_assets_cwd(tmp_path: Path):
    unity_root = tmp_path / "My project"
    (unity_root / "Assets").mkdir(parents=True)
    (unity_root / "Packages").mkdir()
    (unity_root / "ProjectSettings").mkdir()
    (unity_root / "Packages" / "manifest.json").write_text(
        '{"dependencies": {"com.unity.inputsystem": "1.7.0"}}',
        encoding="utf-8",
    )
    (unity_root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.0.0f1",
        encoding="utf-8",
    )
    (unity_root / "Assembly-CSharp.csproj").write_text("<Project />", encoding="utf-8")
    (unity_root / ".claude" / "skills" / "gstack").mkdir(parents=True)
    (unity_root / ".claude" / "skills" / "gstack" / "package.json").write_text(
        '{"dependencies": {"typescript": "5.0.0"}}',
        encoding="utf-8",
    )

    profile = build_project_profile(unity_root / "Assets", project_name="pvz-unity")

    assert profile.project_name == "pvz-unity"
    assert "unity" in profile.stacks
    assert "csharp" in profile.stacks
    assert "typescript" not in profile.stacks
    assert "node" not in profile.stacks
    assert "ProjectSettings/ProjectVersion.txt" in profile.key_files
    assert "Packages/manifest.json" in profile.key_files


def test_build_project_profile_ignores_generated_and_fixture_dirs(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'real-python-project'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "fixtures" / "php-ts-monorepo").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "php-ts-monorepo" / "composer.json").write_text(
        '{"require": {"laravel/framework": "^11.0"}}',
        encoding="utf-8",
    )
    (tmp_path / ".tmp" / "old-run" / "demo").mkdir(parents=True)
    (tmp_path / ".tmp" / "old-run" / "demo" / "package.json").write_text(
        '{"dependencies": {"next": "15.0.0", "react": "19.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "target" / "debug" / "nested").mkdir(parents=True)
    (tmp_path / "target" / "debug" / "nested" / "go.mod").write_text(
        "module ignored.example\n",
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "package.json").write_text(
        '{"dependencies": {"typescript": "5.0.0"}}',
        encoding="utf-8",
    )

    profile = build_project_profile(tmp_path, project_name="real-python-project")

    assert profile.stacks == ["python"]
    assert profile.key_files == ["pyproject.toml"]
