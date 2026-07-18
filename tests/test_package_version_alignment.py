"""Runtime __version__ must match packaging metadata."""

from __future__ import annotations

import json
from pathlib import Path

from harness_mem import __version__


def _pyproject_version() -> str:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version = "):
            return stripped.split("=", 1)[1].strip().strip('"')
    raise AssertionError("pyproject.toml version not found")


def test_runtime_version_matches_pyproject() -> None:
    assert __version__ == _pyproject_version()


def test_public_install_and_plugin_versions_match_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "plugins/harness-mem/.codex-plugin/plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["version"] == __version__

    for relative in ("README.md", "README.zh-CN.md", "docs/quickstart.md"):
        content = (root / relative).read_text(encoding="utf-8")
        assert f"harness-mem=={__version__}" in content
        assert f"expanded_assets/v{__version__}" in content

    maturity = (root / "docs/maturity-model.md").read_text(encoding="utf-8")
    readiness = (root / "canvases/harness-mem-readiness-v1.canvas.tsx").read_text(
        encoding="utf-8"
    )
    assert f"Current snapshot (v{__version__})" in maturity
    assert f'RUNTIME_VERSION = "{__version__}"' in readiness
