"""CLI tests for ``harness-mem maintenance assign-memory-types``.

Covers the v1.6.0 backfill contract:

- ``--dry-run`` is the default and writes nothing
- ``--apply`` mutates JSON blobs to persist memory_type
- Idempotency: re-running ``--dry-run`` after ``--apply`` reports 0 changes
- Project scoping: only blobs whose ``project_name`` matches the active /
  ``--project`` are touched
- Missing project context fails with a clear message and non-zero exit
- Already-typed entries (``memory_type`` present) are skipped
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.commands.maintenance import cmd_assign_memory_types
from harness_mem.core.schemas import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def _seed_legacy_blob(
    data_dir: Path,
    *,
    entry_id: str,
    project_name: str,
    category: str,
    include_memory_type: bool = False,
    memory_type: str | None = None,
) -> Path:
    """Write a JSON blob mimicking pre-v1.6.0 shape (no memory_type by default)."""
    blob_dir = data_dir / "structured" / "memory_entries"
    blob_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "id": entry_id,
        "project_name": project_name,
        "category": category,
        "content": f"legacy entry {entry_id}",
        "confidence": 0.8,
        "status": "accepted",
        "source": "manual",
        "created_at": "2026-04-23T00:00:00+00:00",
        "updated_at": "2026-04-23T00:00:00+00:00",
        "tags": [],
        "compacted": False,
        "usage_count": 0,
        "last_accessed_at": None,
        "provenance": None,
    }
    if include_memory_type:
        payload["memory_type"] = memory_type
    blob_path = blob_dir / f"{entry_id}.json"
    blob_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return blob_path


def _seed_three_legacy_blobs(data_dir: Path, project_name: str = "demo") -> list[Path]:
    """Two legacy blobs missing memory_type + one already typed."""
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    run(backend.close())
    return [
        _seed_legacy_blob(
            data_dir, entry_id="mem_legacy_a", project_name=project_name,
            category="convention",
        ),
        _seed_legacy_blob(
            data_dir, entry_id="mem_legacy_b", project_name=project_name,
            category="raw_note",
        ),
        _seed_legacy_blob(
            data_dir, entry_id="mem_already_typed", project_name=project_name,
            category="bug", include_memory_type=True, memory_type="semantic",
        ),
    ]


# ---------------------------------------------------------------------------
# Direct command call — easier to assert structured behavior
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_and_reports_pending(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.cmd_use("demo")
    blobs = _seed_three_legacy_blobs(data_dir)
    snapshot = {p: p.read_text(encoding="utf-8") for p in blobs}

    rc = run(cmd_assign_memory_types("demo", apply=False))
    assert rc == 0

    output = capsys.readouterr().out
    assert "Would update 2 MemoryEntry rows" in output
    assert "1 already typed" in output
    assert "No changes written. Use --apply to commit." in output
    assert "mem_legacy_a (category=convention) -> semantic" in output
    assert "mem_legacy_b (category=raw_note) -> episodic" in output

    # Files MUST be byte-identical after dry-run.
    for blob_path in blobs:
        assert blob_path.read_text(encoding="utf-8") == snapshot[blob_path]


def test_apply_persists_derived_memory_type(data_dir: Path) -> None:
    cli.cmd_use("demo")
    legacy_a, legacy_b, already_typed = _seed_three_legacy_blobs(data_dir)

    rc = run(cmd_assign_memory_types("demo", apply=True))
    assert rc == 0

    payload_a = json.loads(legacy_a.read_text(encoding="utf-8"))
    payload_b = json.loads(legacy_b.read_text(encoding="utf-8"))
    payload_already = json.loads(already_typed.read_text(encoding="utf-8"))

    assert payload_a["memory_type"] == "semantic"  # derived from "convention"
    assert payload_b["memory_type"] == "episodic"  # derived from "raw_note"
    assert payload_already["memory_type"] == "semantic"  # untouched


def test_apply_then_dry_run_is_idempotent(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.cmd_use("demo")
    _seed_three_legacy_blobs(data_dir)

    assert run(cmd_assign_memory_types("demo", apply=True)) == 0
    capsys.readouterr()  # discard apply output

    assert run(cmd_assign_memory_types("demo", apply=False)) == 0
    output = capsys.readouterr().out
    assert "Would update 0 MemoryEntry rows" in output
    assert "3 already typed" in output


def test_apply_round_trips_through_memory_entry_from_dict(data_dir: Path) -> None:
    """After backfill, legacy blob loads cleanly through MemoryEntry.from_dict
    and reports the persisted memory_type without re-derivation."""
    cli.cmd_use("demo")
    blob_a, _, _ = _seed_three_legacy_blobs(data_dir)

    assert run(cmd_assign_memory_types("demo", apply=True)) == 0

    data = json.loads(blob_a.read_text(encoding="utf-8"))
    assert "memory_type" in data
    entry = MemoryEntry.from_dict(data)
    assert entry.memory_type == "semantic"


def test_project_scoping_only_touches_target_project(data_dir: Path) -> None:
    cli.cmd_use("demo")
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    run(backend.close())

    own = _seed_legacy_blob(
        data_dir, entry_id="mem_own", project_name="demo",
        category="convention",
    )
    other = _seed_legacy_blob(
        data_dir, entry_id="mem_other", project_name="other",
        category="convention",
    )

    assert run(cmd_assign_memory_types("demo", apply=True)) == 0

    own_payload = json.loads(own.read_text(encoding="utf-8"))
    other_payload = json.loads(other.read_text(encoding="utf-8"))
    assert own_payload["memory_type"] == "semantic"
    assert "memory_type" not in other_payload  # MUST remain untouched


def test_missing_project_context_fails_with_message(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force non-interactive so prompt path is skipped.
    monkeypatch.setattr("harness_mem.commands.support.can_prompt", lambda: False)

    rc = run(cmd_assign_memory_types(None, apply=True))
    assert rc == 1


# ---------------------------------------------------------------------------
# Argparse-level wiring sanity — confirms the dispatch path is hooked up
# ---------------------------------------------------------------------------


def test_cli_dispatch_invokes_dry_run_by_default(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.cmd_use("demo")
    _seed_three_legacy_blobs(data_dir)

    monkeypatch.setattr(
        "sys.argv",
        ["harness-mem", "maintenance", "assign-memory-types", "-p", "demo"],
    )
    rc = cli.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Would update 2 MemoryEntry rows" in out
    assert "No changes written" in out


def test_cli_dispatch_apply_writes(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.cmd_use("demo")
    legacy_a, _, _ = _seed_three_legacy_blobs(data_dir)

    monkeypatch.setattr(
        "sys.argv",
        ["harness-mem", "maintenance", "assign-memory-types", "-p", "demo", "--apply"],
    )
    rc = cli.main()
    assert rc == 0
    payload = json.loads(legacy_a.read_text(encoding="utf-8"))
    assert payload["memory_type"] == "semantic"
