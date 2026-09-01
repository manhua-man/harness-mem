"""Runtime __version__ must match packaging metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness_mem import __version__

PUBLIC_RELEASE_VERSION = "0.9.25"


def _pyproject_version() -> str:
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version = "):
            return stripped.split("=", 1)[1].strip().strip('"')
    raise AssertionError("pyproject.toml version not found")


def test_runtime_version_matches_pyproject() -> None:
    assert __version__ == _pyproject_version()


def test_source_and_public_install_versions_are_aligned() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "code/plugins/harness-mem/.codex-plugin/plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == __version__

    for relative in ("README.md", "README.zh-CN.md", "docs/quickstart.md"):
        content = (root / relative).read_text(encoding="utf-8")
        assert f"harness-mem=={PUBLIC_RELEASE_VERSION}" in content
        assert f"expanded_assets/v{PUBLIC_RELEASE_VERSION}" in content
        assert set(re.findall(r"expanded_assets/v(\d+\.\d+\.\d+)", content)) == {
            PUBLIC_RELEASE_VERSION
        }

    current_version_text = {
        "README.md": f"The current `{__version__}` source",
        "README.zh-CN.md": f"当前 `{__version__}` 源码",
        "AGENTS.md": f"当前源码版本 `{__version__}`",
        "docs/memory-adoption.md": f"current\nsource is `{__version__}`",
        "docs/auto-promoted-memory-governance.md": (
            f"current `{__version__}` source"
        ),
        "docs/canvases/README.md": f"**当前源码**：{__version__}",
    }
    for relative, expected in current_version_text.items():
        assert expected in (root / relative).read_text(encoding="utf-8")

    for relative in (
        "docs/assets/harness-mem-cold-start-flow.svg",
        "docs/assets/harness-mem-lossless-session-flow.svg",
        "docs/assets/harness-mem-candidate-governance.svg",
        "docs/assets/harness-mem-runtime-layered-architecture.svg",
    ):
        content = (root / relative).read_text(encoding="utf-8")
        assert f"source {__version__}" in content
        assert f"v{__version__}" not in content
        assert "selected CLI" in content
        assert "Verified outcome" not in content
        assert "terminal outcome" not in content

    maturity = (root / "docs/maturity-model.md").read_text(encoding="utf-8")
    readiness = (root / "docs/canvases/harness-mem-readiness-v1.canvas.tsx").read_text(
        encoding="utf-8"
    )
    convergence = (
        root / "docs/canvases/harness-mem-convergence.canvas.tsx"
    ).read_text(encoding="utf-8")
    assert f"Current snapshot (v{__version__})" in maturity
    for canvas in (readiness, convergence):
        assert f'RUNTIME_VERSION = "{__version__}"' in canvas
        assert f'PUBLIC_RELEASE_VERSION = "{PUBLIC_RELEASE_VERSION}"' in canvas
        assert "source {RUNTIME_VERSION}" in canvas
        assert "public {PUBLIC_RELEASE_VERSION}" in canvas
    assert f"published package is\n`{PUBLIC_RELEASE_VERSION}`" in maturity
    assert f"GitHub 最新公开版本为 {PUBLIC_RELEASE_VERSION}" in readiness

    release_notes = (root / "release-notes.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.startswith(f"# Draft release {__version__} ")
    assert f"latest public release is `{PUBLIC_RELEASE_VERSION}`" in release_notes
    assert changelog.startswith("# Changelog\n\n## Unreleased\n")
    assert f"## [{__version__}]" not in changelog
