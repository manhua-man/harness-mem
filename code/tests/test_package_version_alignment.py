"""Runtime __version__ must match packaging metadata."""

from __future__ import annotations

import re
from pathlib import Path

from harness_mem import __version__


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
    root = Path(__file__).resolve().parents[2]
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    package = re.search(
        r'\[\[package\]\]\s+name = "harness-mem"\s+version = "([^"]+)"',
        lock,
    )
    assert package is not None
    assert package.group(1) == __version__
