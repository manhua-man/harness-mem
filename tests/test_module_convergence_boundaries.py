from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_structured_store_facade_stays_composed_and_bounded() -> None:
    facade = _source("harness_mem/storage/local_structured_store.py")

    assert len(facade.splitlines()) < 700
    for mixin in (
        "StructuredMemoryMixin",
        "StructuredCandidateMixin",
        "StructuredTruthMixin",
        "StructuredLedgerMixin",
    ):
        assert mixin in facade
    assert "async def save_memory_entry(" not in facade
    assert "async def save_rule_candidate(" not in facade
    assert "async def save_skill(" not in facade
    assert "async def save_dream_run(" not in facade


def test_read_handler_facade_and_domains_stay_bounded() -> None:
    facade = _source("harness_mem/mcp/read_handlers.py")
    domain_paths = (
        "harness_mem/mcp/read_query_support.py",
        "harness_mem/mcp/read_search_handlers.py",
        "harness_mem/mcp/read_evidence_handlers.py",
        "harness_mem/mcp/read_wake_handlers.py",
    )

    assert len(facade.splitlines()) < 100
    assert all(len(_source(path).splitlines()) < 700 for path in domain_paths)
    assert "def tool_search_memory(" not in facade
    assert "def tool_wake(" not in facade


def test_doctor_orchestrator_does_not_reabsorb_probe_or_rendering_bodies() -> None:
    doctor = _source("harness_mem/commands/doctor.py")
    classification = _source("harness_mem/commands/doctor_classification.py")
    probes = _source("harness_mem/commands/doctor_probes.py")
    rendering = _source("harness_mem/commands/doctor_rendering.py")

    assert len(doctor.splitlines()) < 400
    assert "async def cmd_doctor(" in doctor
    assert "def detect_cwd_project_mismatch(" in classification
    assert "async def local_health_summary(" in probes
    assert "def _doctor_storage_v2_block(" in rendering
    assert "async def local_health_summary(" not in doctor
    assert "def _doctor_storage_v2_block(" not in doctor


def test_split_runtime_modules_import_independently() -> None:
    modules = (
        "harness_mem.storage.local_structured_store",
        "harness_mem.mcp.read_query_support",
        "harness_mem.mcp.read_search_handlers",
        "harness_mem.mcp.read_evidence_handlers",
        "harness_mem.mcp.read_wake_handlers",
        "harness_mem.commands.doctor_classification",
        "harness_mem.commands.doctor_probes",
        "harness_mem.commands.doctor_rendering",
    )
    for module in modules:
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, f"{module}: {completed.stderr}"
