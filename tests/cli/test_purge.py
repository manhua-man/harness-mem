from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.cli


def test_purge_dry_run_handles_aware_timestamps_without_deleting(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="purge-aware-dry-run",
                    client="claude-code",
                    raw_content="Old observation kept during dry run.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Old memory kept during dry run.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.search("dry run", project_name="demo", limit=10))
        entries = run(backend.structured_store.search_memory_entries("dry run", project_name="demo", limit=10))
        assert len(observations) == 1
        assert len(entries) == 1
    finally:
        run(backend.close())

    captured = capsys.readouterr().out
    assert "[DRY RUN] Would soft-delete" in captured


def test_purge_hides_soft_deleted_data_from_search_timeline_and_wake(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    assert cli.cmd_use("demo") == 0

    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="purge-hide-001",
                    client="claude-code",
                    raw_content="Ancient auth observation that should disappear.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Ancient auth memory that should disappear.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", False)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.search("Ancient auth", project_name="demo", limit=10))
        timeline = run(backend.verbatim_store.timeline(project_name="demo", limit=10))
        entries = run(backend.structured_store.search_memory_entries("Ancient auth", project_name="demo", limit=10))
        listed_entries = run(backend.structured_store.list_memory_entries("demo", limit=10))
        assert observations == []
        assert timeline == []
        assert entries == []
        assert listed_entries == []
    finally:
        run(backend.close())

    assert run(cli.cmd_wake_up("demo")) == 0
    wake_output = capsys.readouterr().out
    assert "Ancient auth" not in wake_output


def test_purge_all_requires_project_context_for_structured_memory(
    capsys: pytest.CaptureFixture[str],
):
    assert run(cli.cmd_purge("2026-01-01", "all", True, project_name=None)) == 1
    output = capsys.readouterr().out
    assert "Project name required for purge" in output


def test_purge_project_scope_only_removes_target_project_data(
    data_dir: Path,
):
    old = datetime.now(timezone.utc) - timedelta(days=120)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="demo-session",
                    client="claude-code",
                    raw_content="Old demo observation.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.verbatim_store.save(
                Observation(
                    session_id="other-session",
                    client="claude-code",
                    raw_content="Old other observation.",
                    content_type="transcript",
                    timestamp=old,
                    metadata={"project_name": "other"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="decision",
                    content="Old demo memory.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="other",
                    category="decision",
                    content="Old other memory.",
                    source="manual",
                    created_at=old,
                    updated_at=old,
                )
            )
        )
    finally:
        run(backend.close())

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert run(cli.cmd_purge(cutoff, "all", False, project_name="demo")) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        demo_observations = run(backend.verbatim_store.search("Old demo", project_name="demo", limit=10))
        other_observations = run(backend.verbatim_store.search("Old other", project_name="other", limit=10))
        demo_entries = run(backend.structured_store.search_memory_entries("Old demo", project_name="demo", limit=10))
        other_entries = run(backend.structured_store.search_memory_entries("Old other", project_name="other", limit=10))
        assert demo_observations == []
        assert demo_entries == []
        assert len(other_observations) == 1
        assert len(other_entries) == 1
    finally:
        run(backend.close())
