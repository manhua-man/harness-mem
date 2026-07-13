from __future__ import annotations

from pathlib import Path


def test_release_workflow_publishes_only_to_github_releases() -> None:
    workflow = Path(".github/workflows/release-wheels.yml").read_text(encoding="utf-8")

    assert "publish-github-release:" in workflow
    assert "gh release upload" in workflow
    assert "publish-pypi:" not in workflow
    assert "pypa/gh-action-pypi-publish" not in workflow
    assert "id-token: write" not in workflow


def test_development_dependencies_do_not_include_pypi_upload_tools() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "twine" not in pyproject.lower()
