"""Smoke + scope-guard tests for the host entry (v2.4.1 Task 7, Req 1)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from harness_mem import cli as cli_module

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_host_entry_module_importable() -> None:
    import harness_mem.host_entry as host_entry_pkg

    assert hasattr(host_entry_pkg, "HostEntryResult")
    assert hasattr(host_entry_pkg, "ExitCode")
    assert int(host_entry_pkg.ExitCode.SUCCESS) == 0


def test_host_entry_help_exits_zero() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "harness_mem.host_entry", "--help"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout or "--project-root" in proc.stdout


def test_no_harness_mem_reflection_subcommand() -> None:
    cli_source = Path(cli_module.__file__).read_text(encoding="utf-8")
    assert 'add_parser("reflection"' not in cli_source, (
        "Found a reflection subcommand registration in cli.py — "
        "v2.4.0 Req 10.2 forbids a user-facing harness-mem reflection CLI."
    )
    assert "add_parser('reflection'" not in cli_source, (
        "Found a reflection subcommand registration in cli.py — "
        "v2.4.0 Req 10.2 forbids a user-facing harness-mem reflection CLI."
    )
