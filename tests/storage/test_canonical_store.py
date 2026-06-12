from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from harness_mem.storage.canonical_store import (
    CANONICAL_ENTITY_TABLES,
    build_canonical_store,
    canonical_store_health,
    canonical_store_path,
    export_json_snapshot,
    mirror_payload_to_canonical,
    read_compatible_payloads,
)
from harness_mem.storage.store_v2_migration import logical_checksum


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _seed_v3(data_dir: Path) -> None:
    _write_json(
        data_dir / "verbatim" / "obs-1.json",
        {
            "id": "obs-1",
            "session_id": "s1",
            "client": "codex",
            "content_type": "transcript",
            "raw_content": "canonical store observation",
            "timestamp": "2026-06-12T00:00:00+00:00",
            "metadata": {"project_name": "demo", "corpus_id": "sessions"},
            "tags": [],
            "compacted": False,
        },
    )
    _write_json(
        data_dir / "structured" / "memory_entries" / "mem-1.json",
        {
            "id": "mem-1",
            "project_name": "demo",
            "corpus_id": "truth",
            "category": "decision",
            "memory_type": "semantic",
            "content": "canonical store keeps metadata indexed",
            "confidence": 0.93,
            "status": "accepted",
            "source": "obs-1",
            "created_at": "2026-06-12T00:00:01+00:00",
            "updated_at": "2026-06-12T00:00:01+00:00",
            "valid_from": "2026-06-12T00:00:01+00:00",
            "valid_to": None,
            "tier": "warm",
            "tags": [],
        },
    )
    _write_json(
        data_dir / "structured" / "confirmed_rules" / "rule-1.json",
        {
            "id": "rule-1",
            "project_name": "demo",
            "pattern": "Use metadata filters before wide recall.",
            "trigger": "canonical store search",
            "examples": [],
            "confirmed_at": "2026-06-12T00:00:02+00:00",
            "source_candidate_id": "cand-1",
            "source_session_id": "s1",
            "tags": [],
        },
    )
    _write_json(
        data_dir / "structured" / "rule_candidates" / "cand-1.json",
        {
            "id": "cand-1",
            "project_name": "demo",
            "session_id": "s1",
            "pattern": "candidate payload",
            "trigger": "test",
            "examples": [],
            "confidence": 0.5,
            "status": "pending",
            "created_at": "2026-06-12T00:00:03+00:00",
        },
    )


def test_canonical_store_builds_entity_tables_and_metadata_indexes(data_dir: Path) -> None:
    _seed_v3(data_dir)

    result = build_canonical_store(data_dir, project_name="demo")

    assert result["checksum_match"] is True
    assert result["canonical_row_count"] == 4
    assert result["entity_tables"]["observations"] == 1
    assert result["entity_tables"]["memory_entries"] == 1
    assert result["entity_tables"]["rules"] == 1
    assert result["entity_tables"]["candidates"] == 1

    conn = sqlite3.connect(canonical_store_path(data_dir))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert set(CANONICAL_ENTITY_TABLES).issubset(tables)
        row = conn.execute(
            """
            SELECT project_id, corpus_id, type, truth_status, confidence,
                   valid_from, valid_to, tier
            FROM memory_entries
            WHERE entity_id = 'mem-1'
            """
        ).fetchone()
        assert row == (
            "demo",
            "truth",
            "semantic",
            "confirmed_current",
            0.93,
            "2026-06-12T00:00:01+00:00",
            None,
            "warm",
        )
    finally:
        conn.close()


def test_compat_reader_falls_back_to_legacy_json_until_migrated(data_dir: Path) -> None:
    _seed_v3(data_dir)

    rows = read_compatible_payloads(data_dir, project_name="demo")

    assert {row.entity_id for row in rows} == {"obs-1", "mem-1", "rule-1", "cand-1"}
    assert not canonical_store_path(data_dir).exists()


def test_json_snapshot_export_round_trips_canonical_checksum(
    data_dir: Path,
    tmp_path: Path,
) -> None:
    _seed_v3(data_dir)
    build_canonical_store(data_dir, project_name="demo")

    dry = export_json_snapshot(
        data_dir,
        tmp_path / "snapshot",
        project_name="demo",
        apply=False,
    )
    assert dry["dry_run"] is True
    assert dry["would_export_json_file_count"] == 4
    assert not (tmp_path / "snapshot").exists()

    exported = export_json_snapshot(
        data_dir,
        tmp_path / "snapshot",
        project_name="demo",
        apply=True,
    )
    assert exported["snapshot_checksum_match"] is True
    original = read_compatible_payloads(data_dir, project_name="demo")
    snapshot = read_compatible_payloads(tmp_path / "snapshot", project_name="demo")
    assert logical_checksum([row.to_legacy_payload_row() for row in original]) == (
        logical_checksum([row.to_legacy_payload_row() for row in snapshot])
    )


def test_canonical_store_health_reports_not_migrated_and_healthy(data_dir: Path) -> None:
    _seed_v3(data_dir)

    missing = canonical_store_health(data_dir, project_name="demo")
    assert missing["status"] == "not_migrated"
    assert missing["partial_migration"] is True

    build_canonical_store(data_dir, project_name="demo")
    healthy = canonical_store_health(data_dir, project_name="demo")
    assert healthy["status"] == "healthy"
    assert healthy["checksum_match"] is True
    assert healthy["index_drift"] == []


def test_dual_write_helper_is_gated(data_dir: Path, monkeypatch) -> None:
    payload = {
        "id": "mem-dual",
        "project_name": "demo",
        "category": "decision",
        "content": "dual write mirror",
        "confidence": 0.8,
        "status": "accepted",
        "source": "unit",
        "created_at": "2026-06-12T00:00:01+00:00",
        "updated_at": "2026-06-12T00:00:01+00:00",
    }

    off = mirror_payload_to_canonical(
        data_dir,
        collection="memory_entries",
        source_relpath="structured/memory_entries/mem-dual.json",
        payload=payload,
    )
    assert off["mirrored"] is False
    assert not canonical_store_path(data_dir).exists()

    monkeypatch.setenv("HARNESS_MEM_STORAGE_V2_DUAL_WRITE", "1")
    on = mirror_payload_to_canonical(
        data_dir,
        collection="memory_entries",
        source_relpath="structured/memory_entries/mem-dual.json",
        payload=payload,
    )
    assert on["mirrored"] is True
    assert canonical_store_path(data_dir).exists()
