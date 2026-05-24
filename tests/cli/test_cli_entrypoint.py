from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.cli

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_python_m_cli_executes_main():
    result = subprocess.run(
        [sys.executable, "-m", "harness_mem.cli", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "harness-mem" in result.stdout


def test_cli_help_only_lists_maintenance_console_commands():
    result = subprocess.run(
        [sys.executable, "-m", "harness_mem.cli", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "{init,quickstart,qs,doctor,import,purge,maintenance}" in result.stdout
    for removed in [
        "wake",
        "search",
        "timeline",
        "status",
        "profile",
        "candidates",
        "confirm",
        "reject",
        "handoff",
        "ingest",
        "api",
    ]:
        assert removed not in result.stdout
