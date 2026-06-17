from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.canonical_store import (
    canonical_store_health,
    canonical_store_path,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _seed_legacy_payloads(data_dir: Path) -> None:
    timestamp = "2026-06-12T00:00:00+00:00"
    _write_json(
        data_dir / "verbatim" / "obs-legacy.json",
        {
            "id": "obs-legacy",
            "session_id": "session-legacy",
            "client": "pytest",
            "content_type": "transcript",
            "raw_content": "legacy observation payload",
            "timestamp": timestamp,
            "metadata": {"project_name": "demo", "corpus_id": "sessions"},
            "tags": [],
            "compacted": False,
        },
    )
    _write_json(
        data_dir / "structured" / "memory_entries" / "mem-legacy.json",
        {
            "id": "mem-legacy",
            "project_name": "demo",
            "category": "decision",
            "content": "legacy memory entry payload",
            "confidence": 0.93,
            "status": "accepted",
            "source": "obs-legacy",
            "created_at": timestamp,
            "updated_at": timestamp,
            "memory_type": "semantic",
            "tier": "warm",
        },
    )
    _write_json(
        data_dir / "structured" / "confirmed_rules" / "rule-legacy.json",
        {
            "id": "rule-legacy",
            "project_name": "demo",
            "pattern": "Prefer canonical SQLite truth.",
            "trigger": "storage cutover",
            "examples": [],
            "confirmed_at": timestamp,
            "source_candidate_id": "cand-legacy",
        },
    )
    _write_json(
        data_dir / "structured" / "rule_candidates" / "cand-legacy.json",
        {
            "id": "cand-legacy",
            "project_name": "demo",
            "session_id": "session-legacy",
            "pattern": "Prefer canonical SQLite truth.",
            "trigger": "storage cutover",
            "examples": [],
            "confidence": 0.66,
            "status": "pending",
            "created_at": timestamp,
        },
    )
    _write_json(
        data_dir / "structured" / "relation_facts" / "rel-legacy.json",
        {
            "id": "rel-legacy",
            "project_name": "demo",
            "source_entity": "storage",
            "target_entity": "sqlite",
            "relation_type": "implemented_by",
            "confidence": 0.8,
            "status": "accepted",
            "evidence": "legacy relation fact payload",
            "source": "obs-legacy",
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    _write_json(
        data_dir / "structured" / "skills" / "skill-legacy.json",
        {
            "id": "skill-legacy",
            "project_name": "demo",
            "name": "Canonical verify",
            "activation_condition": "when validating default truth",
            "steps": ["run storage doctor"],
            "termination_condition": "doctor output is healthy",
            "success_examples": [],
            "scope": "project",
            "origin_project": "demo",
            "source_ids": [],
            "portability_notes": "",
            "disabled_assumptions": [],
            "confidence": 0.8,
            "status": "active",
            "usage_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0.0,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    _write_json(
        data_dir / "structured" / "task_handoffs" / "handoff-legacy.json",
        {
            "id": "handoff-legacy",
            "project_name": "demo",
            "task_id": "task-legacy",
            "summary": "finish default storage cutover",
            "status": "in_progress",
            "next_steps": ["switch runtime search"],
            "blockers": [],
            "last_activity": timestamp,
        },
    )
    _write_json(
        data_dir / "structured" / "retrieval_signals" / "signal-legacy.json",
        {
            "id": "signal-legacy",
            "project_name": "demo",
            "signal_type": "search_hit",
            "target_kind": "memory_entry",
            "target_id": "mem-legacy",
            "recorded_at": timestamp,
            "value": 1.0,
        },
    )


def test_fresh_backend_bootstraps_canonical_truth_without_runtime_blobs(
    data_dir: Path,
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        assert backend.runtime_state == "canonical"
        assert canonical_store_path(data_dir).exists()

        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-fresh",
                    session_id="session-fresh",
                    client="pytest",
                    raw_content="fresh canonical observation",
                    content_type="transcript",
                    timestamp=now,
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id="mem-fresh",
                    project_name="demo",
                    category="decision",
                    content="fresh canonical truth",
                    confidence=0.9,
                    source="obs-fresh",
                    created_at=now,
                    updated_at=now,
                )
            )
        )
        assert run(backend.structured_store.get_memory_entry("mem-fresh")) is not None
        assert run(backend.verbatim_store.get("obs-fresh")) is not None
    finally:
        run(backend.close())

    assert not any((data_dir / "structured").rglob("*.json"))
    assert not any((data_dir / "verbatim").glob("*.json"))
    health = canonical_store_health(data_dir, project_name="demo")
    assert health["runtime_state"] == "canonical"


def test_legacy_only_backend_auto_migrates_and_is_idempotent(data_dir: Path) -> None:
    _seed_legacy_payloads(data_dir)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        assert backend.runtime_state == "bootstrapped_from_legacy"
        assert len(run(backend.verbatim_store.list(limit=10))) == 1
        assert len(run(backend.structured_store.list_memory_entries("demo", include_history=True))) == 1
        assert len(run(backend.structured_store.list_confirmed_rules("demo", include_history=True))) == 1
        assert len(run(backend.structured_store.list_relation_facts("demo", include_history=True))) == 1
        assert len(run(backend.structured_store.list_skills("demo"))) == 1
        assert len(run(backend.structured_store.get_latest_handoffs("demo", limit=10))) == 1
        assert len(run(backend.structured_store.list_rule_candidates("demo"))) == 1
        assert len(run(backend.structured_store.query_retrieval_signals("demo"))) == 1
        first_health = canonical_store_health(data_dir, project_name="demo")
        first_checksum = first_health["canonical_checksum"]
    finally:
        run(backend.close())

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        assert backend.runtime_state == "bootstrapped_from_legacy"
        second_health = canonical_store_health(data_dir, project_name="demo")
        assert second_health["canonical_checksum"] == first_checksum
        assert second_health["canonical_row_count"] == first_health["canonical_row_count"]
    finally:
        run(backend.close())


def test_invalid_legacy_payload_enters_degraded_fallback(data_dir: Path) -> None:
    broken = data_dir / "structured" / "memory_entries" / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ this is not valid json", encoding="utf-8")

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        assert backend.runtime_state == "degraded_fallback"
        health = canonical_store_health(data_dir)
        assert health["runtime_state"] == "degraded_fallback"
        assert health["fix_command"] == "harness-mem maintenance migrate-store-v2 --apply"
        assert "export-json-snapshot" in health["recovery_hint"]
    finally:
        run(backend.close())
