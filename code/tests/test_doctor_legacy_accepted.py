"""Doctor legacy accepted status scan."""

from __future__ import annotations

import asyncio
from io import StringIO
import sys
from pathlib import Path

import pytest

from harness_mem.commands.doctor import (
    _doctor_legacy_accepted_block,
    legacy_accepted_status_report,
    local_health_summary,
)
from harness_mem.core.schemas import MemoryEntry, RelationFact
from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.fixture
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalMemoryBackend:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    yield backend
    asyncio.run(backend.close())


def test_legacy_accepted_report_zero_when_clean(backend: LocalMemoryBackend) -> None:
    report = asyncio.run(
        legacy_accepted_status_report(backend.structured_store, "legacy-demo")
    )
    assert report["total"] == 0
    assert report["by_table"] == {}


def test_legacy_accepted_report_counts_injected_blob(
    backend: LocalMemoryBackend,
) -> None:
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="legacy-demo",
                category="decision",
                content="legacy accepted memory blob",
                source="obs:legacy",
                status=LEGACY_ACCEPTED_STATUS,
            )
        )
    )
    asyncio.run(
        backend.structured_store.save_relation_fact(
            RelationFact(
                project_name="legacy-demo",
                source_entity="a",
                target_entity="b",
                relation_type="depends_on",
                evidence="legacy accepted relation",
                source="obs:legacy-rel",
                status=LEGACY_ACCEPTED_STATUS,
            )
        )
    )

    report = asyncio.run(
        legacy_accepted_status_report(backend.structured_store, "legacy-demo")
    )
    assert report["total"] == 2
    assert report["by_table"]["memory_entries"] == 1
    assert report["by_table"]["relation_facts"] == 1


def test_legacy_accepted_block_prints_zero_line() -> None:
    buffer = StringIO()
    stdout = sys.stdout
    try:
        sys.stdout = buffer
        _doctor_legacy_accepted_block({"total": 0, "by_table": {}})
    finally:
        sys.stdout = stdout
    output = buffer.getvalue()
    assert f"Legacy status={LEGACY_ACCEPTED_STATUS}: 0 records" in output


def test_legacy_accepted_block_prints_count_when_present() -> None:
    buffer = StringIO()
    stdout = sys.stdout
    try:
        sys.stdout = buffer
        _doctor_legacy_accepted_block(
            {"total": 2, "by_table": {"memory_entries": 2}}
        )
    finally:
        sys.stdout = stdout
    output = buffer.getvalue()
    assert f"Legacy status={LEGACY_ACCEPTED_STATUS}: 2 record(s)" in output


def test_local_health_summary_includes_legacy_accepted(
    backend: LocalMemoryBackend,
) -> None:
    asyncio.run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="legacy-demo",
                category="decision",
                content="legacy accepted in health summary",
                source="obs:legacy-health",
                status=LEGACY_ACCEPTED_STATUS,
            )
        )
    )
    summary = asyncio.run(local_health_summary(backend, "legacy-demo"))
    assert summary["legacy_accepted"]["total"] == 1