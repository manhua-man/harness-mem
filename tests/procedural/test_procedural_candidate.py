import asyncio
import json
from pathlib import Path

from harness_mem.core.schemas import MemoryEntry, ProceduralCandidate
from harness_mem.procedural import (
    load_procedural_candidate_fixture,
    load_procedural_candidate_fixtures,
)
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.wake_selection import select_wake_memory_entries_with_buckets


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "procedural"


def test_procedural_candidate_round_trip_preserves_review_fields() -> None:
    candidate = ProceduralCandidate(
        project_name="harness-mem",
        activation_condition="Need to validate a focused runtime change",
        steps=[
            "Run focused tests",
            "Run ruff and mypy",
            "Run full pytest",
        ],
        termination_condition="All validation commands are green",
        success_examples=["323 passed, 1 skipped"],
        source_session_id="session-123",
        confidence=0.81,
        status="draft",
    )

    restored = ProceduralCandidate.from_dict(candidate.to_dict())

    assert restored.project_name == "harness-mem"
    assert restored.steps == candidate.steps
    assert restored.source_session_id == "session-123"
    assert restored.status == "draft"
    assert restored.confidence == 0.81


def test_load_single_procedural_fixture_sets_file_provenance() -> None:
    fixture_path = FIXTURE_DIR / "repeated-test-loop.json"

    candidate = load_procedural_candidate_fixture(fixture_path)

    assert candidate.project_name == "harness-mem"
    assert candidate.source_session_id == "procedural-spike-001"
    assert candidate.source.endswith("repeated-test-loop.json")
    assert candidate.steps[0] == "Run the most relevant focused tests first"


def test_load_procedural_fixture_set_contains_three_repo_workflows() -> None:
    candidates = load_procedural_candidate_fixtures(FIXTURE_DIR)

    assert [candidate.source_session_id for candidate in candidates] == [
        "procedural-spike-003",
        "procedural-spike-001",
        "procedural-spike-002",
    ]
    assert all(candidate.status == "draft" for candidate in candidates)
    assert all(candidate.steps for candidate in candidates)


def test_fixture_loading_is_read_only_for_structured_store(tmp_path: Path) -> None:
    async def check() -> None:
        assert await store.list_memory_entries("harness-mem", status="accepted") == []
        assert await store.list_rule_candidates("harness-mem") == []
        assert await store.list_supersede_candidates("harness-mem") == []
        assert await store.list_procedural_candidates("harness-mem") == []

    store = LocalStructuredStore(tmp_path)

    candidates = load_procedural_candidate_fixtures(FIXTURE_DIR)

    assert len(candidates) == 3
    structured_dir = tmp_path / "structured"
    procedural_blob_dir = structured_dir / "procedural_candidates"
    assert procedural_blob_dir.exists()
    assert list(procedural_blob_dir.glob("*.json")) == []
    asyncio.run(check())
    assert (structured_dir / "skills").exists()
    assert list((structured_dir / "skills").glob("*.json")) == []


def test_procedural_spike_does_not_change_default_wake_selection() -> None:
    candidates = load_procedural_candidate_fixtures(FIXTURE_DIR)
    entries = [
        MemoryEntry(
            project_name="harness-mem",
            category="decision",
            content="Use current-only truth by default.",
            source="test",
            memory_type="semantic",
            importance=0.8,
        ),
        MemoryEntry(
            project_name="harness-mem",
            category="decision",
            content=json.dumps(candidates[0].to_dict()),
            source="test",
            memory_type="procedural",
            importance=1.0,
        ),
    ]

    selected, stats = select_wake_memory_entries_with_buckets(
        entries,
        limit=2,
        quotas={"semantic": 0.5, "episodic": 0.5, "procedural": 0.0},
    )

    assert [entry.memory_type for entry in selected] == ["semantic"]
    assert stats["procedural"].used == 0
