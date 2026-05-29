"""Tests for :func:`harness_mem.commands.doctor.candidate_health` (Req 1, 2).

The diagnostic is a read-only per-table aggregate of pending candidates across
the five covered candidate tables (``rule_candidates``, ``memory_entries``,
``relation_facts``, ``procedural_candidates``, ``supersede_candidates``). It
reports pending counts, stale counts (per-type threshold), high-risk-stale
counts (stale + low confidence; ``None`` for supersede), and the single oldest
pending row's id + ISO timestamp.

We seed candidates directly through the store's ``save_*`` methods so the
assertions stay focused on the aggregation logic. ``created_at`` is set
explicitly to exercise the stale / fresh boundary. Async functions are driven
via :func:`tests.helpers.run` (``asyncio.run``), following the rest of the
suite. The store is scoped to ``tmp_path`` per the project data-isolation rule.

Following the convention of the suite, age boundaries use a comfortable margin
(threshold ± 1 day) rather than freezing the clock, so ±5s wall-clock jitter
between fixture creation and ``datetime.now`` inside the helper is irrelevant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.doctor import candidate_health
from harness_mem.commands.doctor_thresholds import (
    HIGH_RISK_CONFIDENCE_CUTOFFS,
    STALE_THRESHOLDS,
)
from harness_mem.core.schemas import (
    MemoryEntry,
    ProceduralCandidate,
    RelationFact,
    RuleCandidate,
    SupersedeCandidate,
)
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

PROJECT = "demo"

# Every covered table key the payload must always expose (Req 1.7).
_TABLE_KEYS = {
    "rule_candidates",
    "memory_entries",
    "relation_facts",
    "procedural_candidates",
    "supersede_candidates",
}

# Per-table dict keys the summary must always expose.
_SUMMARY_KEYS = {
    "pending_count",
    "stale_count",
    "high_risk_stale_count",
    "oldest_pending_id",
    "oldest_pending_created_at",
}


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> LocalStructuredStore:
    """A fresh LocalStructuredStore scoped to tmp_path, closed on teardown."""
    local_store = LocalStructuredStore(tmp_path / "data")
    try:
        yield local_store
    finally:
        local_store.close()


# ---- seed helpers --------------------------------------------------------


def _seed_rule(
    store: LocalStructuredStore,
    *,
    created_at: datetime,
    confidence: float = 0.9,
    status: str = "pending",
) -> RuleCandidate:
    candidate = RuleCandidate(
        project_name=PROJECT,
        session_id="sess-1",
        pattern="always run ruff",
        trigger="before commit",
        confidence=confidence,
        status=status,
        created_at=created_at,
    )
    run(store.save_rule_candidate(candidate))
    return candidate


def _seed_memory(
    store: LocalStructuredStore,
    *,
    created_at: datetime,
    confidence: float = 0.9,
    status: str = "pending",
) -> MemoryEntry:
    entry = MemoryEntry(
        project_name=PROJECT,
        category="architecture",
        content="uses sqlite fts5",
        source="manual",
        confidence=confidence,
        status=status,
        created_at=created_at,
    )
    run(store.save_memory_entry(entry))
    return entry


def _seed_relation(
    store: LocalStructuredStore,
    *,
    created_at: datetime,
    confidence: float = 0.9,
    status: str = "pending",
) -> RelationFact:
    fact = RelationFact(
        project_name=PROJECT,
        source_entity="api",
        target_entity="db",
        relation_type="depends_on",
        evidence="imports module",
        source="manual",
        confidence=confidence,
        status=status,
        created_at=created_at,
    )
    run(store.save_relation_fact(fact))
    return fact


def _seed_procedural(
    store: LocalStructuredStore,
    *,
    created_at: datetime,
    confidence: float = 0.9,
    status: str = "pending",
) -> ProceduralCandidate:
    candidate = ProceduralCandidate(
        project_name=PROJECT,
        activation_condition="when releasing",
        steps=["bump version", "tag", "push"],
        termination_condition="ci green",
        confidence=confidence,
        status=status,
        created_at=created_at,
    )
    run(store.save_procedural_candidate(candidate))
    return candidate


def _seed_supersede(
    store: LocalStructuredStore,
    *,
    created_at: datetime,
    confidence: float = 0.9,
    status: str = "pending",
) -> SupersedeCandidate:
    candidate = SupersedeCandidate(
        project_name=PROJECT,
        target_type="memory_entry",
        target_id="old-id",
        replacement_type="memory_entry",
        replacement_id="new-id",
        reason="superseded by newer decision",
        evidence="see session",
        confidence=confidence,
        status=status,
        created_at=created_at,
    )
    run(store.save_supersede_candidate(candidate))
    return candidate


def _stale_for(table: str) -> datetime:
    """A created_at comfortably older than the table's stale threshold."""
    return datetime.now(timezone.utc) - STALE_THRESHOLDS[table] - timedelta(days=1)


def _fresh() -> datetime:
    """A created_at well inside every stale threshold."""
    return datetime.now(timezone.utc) - timedelta(hours=1)


def _snapshot_blobs(store: LocalStructuredStore) -> dict[str, str]:
    """Map of relative blob path -> file content, for read-only assertions."""
    snapshot: dict[str, str] = {}
    for path in sorted(store.blob_dir.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(store.blob_dir))] = path.read_text()
    return snapshot


# ---- test 1: zero-state --------------------------------------------------


def test_zero_state_all_tables_present_with_zero_counts(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 1.6, 1.7 — fresh store, stable zero-shape."""
    report = run(candidate_health(store, PROJECT))

    assert set(report.keys()) == _TABLE_KEYS
    for table, summary in report.items():
        assert set(summary.keys()) == _SUMMARY_KEYS, table
        assert summary["pending_count"] == 0, table
        assert summary["stale_count"] == 0, table
        assert summary["oldest_pending_id"] is None, table
        assert summary["oldest_pending_created_at"] is None, table

    # supersede high_risk_stale_count is explicitly None; the other four are 0.
    assert report["supersede_candidates"]["high_risk_stale_count"] is None
    for table in _TABLE_KEYS - {"supersede_candidates"}:
        assert report[table]["high_risk_stale_count"] == 0, table


# ---- test 2: mixed pending counts ---------------------------------------


def test_mixed_pending_counts_match(store: LocalStructuredStore) -> None:
    """Validates: Requirements 1.2 — pending_count equals seeded fresh rows."""
    fresh = _fresh()
    for _ in range(2):
        _seed_rule(store, created_at=fresh)
    for _ in range(3):
        _seed_memory(store, created_at=fresh)
    _seed_relation(store, created_at=fresh)
    for _ in range(4):
        _seed_procedural(store, created_at=fresh)
    for _ in range(2):
        _seed_supersede(store, created_at=fresh)

    report = run(candidate_health(store, PROJECT))

    assert report["rule_candidates"]["pending_count"] == 2
    assert report["memory_entries"]["pending_count"] == 3
    assert report["relation_facts"]["pending_count"] == 1
    assert report["procedural_candidates"]["pending_count"] == 4
    assert report["supersede_candidates"]["pending_count"] == 2
    # Fresh rows are never stale.
    assert all(report[t]["stale_count"] == 0 for t in _TABLE_KEYS)


def test_non_pending_rows_are_excluded(store: LocalStructuredStore) -> None:
    """Validates: Requirements 1.1, 1.2 — only status='pending' rows count."""
    fresh = _fresh()
    _seed_rule(store, created_at=fresh, status="pending")
    _seed_rule(store, created_at=fresh, status="accepted")
    _seed_memory(store, created_at=fresh, status="pending")
    _seed_memory(store, created_at=fresh, status="accepted")

    report = run(candidate_health(store, PROJECT))

    assert report["rule_candidates"]["pending_count"] == 1
    assert report["memory_entries"]["pending_count"] == 1


# ---- test 3: stale boundary ---------------------------------------------


def test_stale_boundary_per_table(store: LocalStructuredStore) -> None:
    """Validates: Requirements 1.3, 2.1 — old rows stale, fresh rows not."""
    seeders = {
        "rule_candidates": _seed_rule,
        "memory_entries": _seed_memory,
        "relation_facts": _seed_relation,
        "procedural_candidates": _seed_procedural,
        "supersede_candidates": _seed_supersede,
    }
    for table, seeder in seeders.items():
        seeder(store, created_at=_stale_for(table))  # stale
        seeder(store, created_at=_fresh())  # fresh

    report = run(candidate_health(store, PROJECT))

    for table in _TABLE_KEYS:
        assert report[table]["pending_count"] == 2, table
        assert report[table]["stale_count"] == 1, table


# ---- test 4: high-risk-stale --------------------------------------------


def test_high_risk_stale_counts_low_confidence_stale_rows(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 2.2 — stale + low confidence is high-risk."""
    table = "rule_candidates"
    cutoff = HIGH_RISK_CONFIDENCE_CUTOFFS[table]
    stale = _stale_for(table)

    # Stale + below cutoff → high-risk.
    _seed_rule(store, created_at=stale, confidence=cutoff - 0.1)
    # Stale + above cutoff → stale but NOT high-risk.
    _seed_rule(store, created_at=stale, confidence=cutoff + 0.1)
    # Fresh + below cutoff → not stale, so not high-risk.
    _seed_rule(store, created_at=_fresh(), confidence=cutoff - 0.1)

    report = run(candidate_health(store, PROJECT))

    assert report[table]["pending_count"] == 3
    assert report[table]["stale_count"] == 2
    assert report[table]["high_risk_stale_count"] == 1


def test_high_risk_uses_strict_less_than_cutoff(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 2.2 — confidence exactly at cutoff is NOT high-risk."""
    table = "memory_entries"
    cutoff = HIGH_RISK_CONFIDENCE_CUTOFFS[table]
    _seed_memory(store, created_at=_stale_for(table), confidence=cutoff)

    report = run(candidate_health(store, PROJECT))

    assert report[table]["stale_count"] == 1
    assert report[table]["high_risk_stale_count"] == 0


# ---- test 5: supersede high_risk_stale_count is None --------------------


def test_supersede_high_risk_stale_is_none_even_with_stale_rows(
    store: LocalStructuredStore,
) -> None:
    """Validates: Requirements 2.2 — supersede has no high-risk category."""
    stale = _stale_for("supersede_candidates")
    _seed_supersede(store, created_at=stale, confidence=0.1)
    _seed_supersede(store, created_at=stale, confidence=0.1)

    report = run(candidate_health(store, PROJECT))

    summary = report["supersede_candidates"]
    assert summary["pending_count"] == 2
    assert summary["stale_count"] == 2
    assert summary["high_risk_stale_count"] is None


# ---- test 6: oldest pending ---------------------------------------------


def test_oldest_pending_is_minimum_created_at(store: LocalStructuredStore) -> None:
    """Validates: Requirements 1.4 — oldest id + ISO timestamp surfaced."""
    now = datetime.now(timezone.utc)
    middle = _seed_rule(store, created_at=now - timedelta(days=10))
    oldest = _seed_rule(store, created_at=now - timedelta(days=40))
    newest = _seed_rule(store, created_at=now - timedelta(days=1))

    report = run(candidate_health(store, PROJECT))

    summary = report["rule_candidates"]
    assert summary["oldest_pending_id"] == oldest.id
    assert summary["oldest_pending_id"] not in {middle.id, newest.id}
    # ISO 8601 string that round-trips to the seeded created_at.
    parsed = datetime.fromisoformat(summary["oldest_pending_created_at"])
    assert abs((parsed - oldest.created_at).total_seconds()) < 1


# ---- test 7: read-only invariant ----------------------------------------


def test_candidate_health_is_read_only(store: LocalStructuredStore) -> None:
    """Validates: Requirements 1.5, 2.6 — no blob mutation across the call."""
    # Seed a spread of states so any mutator would leave a trace.
    _seed_rule(store, created_at=_stale_for("rule_candidates"), confidence=0.2)
    _seed_memory(store, created_at=_fresh())
    _seed_relation(store, created_at=_stale_for("relation_facts"))
    _seed_procedural(store, created_at=_fresh())
    _seed_supersede(store, created_at=_stale_for("supersede_candidates"))

    before = _snapshot_blobs(store)
    run(candidate_health(store, PROJECT))
    after = _snapshot_blobs(store)

    assert before == after
