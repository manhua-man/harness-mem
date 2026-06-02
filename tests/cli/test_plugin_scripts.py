from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.cli

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_SCRIPT = REPO_ROOT / "plugins" / "harness-mem" / "scripts" / "doctor.ps1"


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def test_plugin_doctor_script_succeeds_without_removed_status_call(tmp_path: Path):
    env = _isolated_env(tmp_path)
    quickstart = subprocess.run(
        [sys.executable, "-m", "harness_mem.cli", "quickstart", "demo", "--client", "skip"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert quickstart.returncode == 0

    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(DOCTOR_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0
    assert "invalid choice: 'status'" not in combined
    assert "harness-mem" in combined
    assert "📍 Phase:" in combined


def test_plugin_doctor_script_wake_switch_prints_ide_hint(tmp_path: Path):
    env = _isolated_env(tmp_path)
    quickstart = subprocess.run(
        [sys.executable, "-m", "harness_mem.cli", "quickstart", "demo", "--client", "skip"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert quickstart.returncode == 0

    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(DOCTOR_SCRIPT), "-Wake"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0
    assert "invalid choice: 'status'" not in combined
    assert "/hm:wake" in combined
