"""Actual isolated device outcomes; no native apps, Hooks or model calls."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness_mem.adapters.source_inspection import HOSTS
from harness_mem.qualification.device_memory_outcome_probe import run_device_memory_variant


@pytest.mark.parametrize("native_containers", [False, True], ids=["files", "containers_and_archives"])
def test_device_memory_outcome(native_containers):
    result = run_device_memory_variant(native_containers=native_containers)
    assert result["verified"] is True, result
    assert all(value for value in result.values() if isinstance(value, bool)), result
    assert set(result["hosts"]) == set(HOSTS)
    assert all(all(host.values()) for host in result["hosts"].values())
    assert result["semantic_mode"] == "deterministic_fixture_agent"
    assert result["native_apps_or_hooks"] == "not_run"


def test_device_memory_outcome_module_emits_isolated_json():
    completed = subprocess.run(
        [sys.executable, "-m", "harness_mem.qualification.device_memory_outcome_probe"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
        encoding="utf-8", timeout=60, check=False,
    )
    result = json.loads(completed.stdout)
    assert result["native_variant_count"] == 2
    assert set(result["variants"]) == {"files", "containers_and_archives"}
    assert result["semantic_mode"] == "deterministic_fixture_agent"
    assert result["native_apps_or_hooks"] == "not_run"
    assert completed.returncode == 0 and result["verified"] is True, result
