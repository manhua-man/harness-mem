"""Per-proposer + integration tests for v2.3.1 metabolism pass (task 2.5).

Each test exercises one proposer (merge / stale / supersede) in
isolation; the final integration test seeds all three suggestion shapes
from one window and pins the cross-leg contract — including the v2.3.1
deferral that supersede must stay empty.

The merge tests rely on the project's standard ``sentence-transformers``
dependency. ``save_memory_entry`` already persists embeddings via
``persist_embedding``; the proposer reads them back from
``vec_embeddings`` rather than re-encoding. Existing embedding-touching
tests in the repo do not gate on a ``sentence_transformers``
``importorskip``, so this module follows that convention.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.commands.metabolism_pass import (
    MetabolismPass,
    select_metabolism_pass,
)
from harness_mem.commands.replay_window import ReplayBudget
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RetrievalSignal,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


@pytest.mark.anyio
async def test_propose_merges_isolated_pair(backend: LocalMemoryBackend) -> None:
    """Two near-duplicate entries surface as one merge candidate.

    Validates the merge leg in isolation:
    * Pair is lex-ordered (``target_a_id < target_b_id``) per the schema.
    * Similarity score clears the 0.85 threshold.
    * Supporting search_hit signals attach as ``evidence_signal_ids``.
    * ``metabolism_run_id`` is the ``"pending"`` sentinel — phase 5.2
      overwrites it before persistence.
    * Stale + supersede stay empty (only merge fires on this fixture).
    """
    project_name = "proj-merge-iso"
    now = datetime.now(timezone.utc)

    duplicate_a = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="Always parameterize SQL queries to prevent SQL injection.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )
    duplicate_b = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="Always use parameterized SQL queries to prevent SQL injection.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )
    unrelated = MemoryEntry(
        project_name=project_name,
        category="api",
        content="User authentication relies on JWT tokens stored in HTTP-only cookies.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    await structured_store.save_memory_entry(duplicate_a)
    await structured_store.save_memory_entry(duplicate_b)
    await structured_store.save_memory_entry(unrelated)

    # Two search_hit signals per duplicate so each entry's count >= 2 and
    # both land in window.repeat_search_hits — that's the gate that lets
    # the proposer's leg-1 query bucket them as evidence on the pair.
    for entry_id in (duplicate_a.id, duplicate_b.id):
        for offset in range(2):
            signal = RetrievalSignal(
                project_name=project_name,
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id=entry_id,
                recorded_at=now - timedelta(hours=offset + 1),
            )
            await structured_store.save_retrieval_signal(signal)

    result = await select_metabolism_pass(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    assert isinstance(result, MetabolismPass)
    assert len(result.merge) == 1
    candidate = result.merge[0]
    # The schema validates ``target_a_id < target_b_id`` at construction;
    # asserting it again here fails fast on a proposer ordering regression
    # before the schema layer would.
    assert candidate.target_a_id < candidate.target_b_id
    assert {candidate.target_a_id, candidate.target_b_id} == {
        duplicate_a.id,
        duplicate_b.id,
    }
    assert candidate.target_a_kind == "memory_entry"
    assert candidate.target_b_kind == "memory_entry"
    assert candidate.similarity_score >= 0.85
    assert candidate.evidence_signal_ids  # non-empty
    assert candidate.metabolism_run_id == "pending"

    # Stale silence default is 60d; entries created an hour ago don't
    # qualify, so stale stays empty.
    assert result.stale == []
    # Auto-supersede deferred in v2.3.1.
    assert result.supersede == []


@pytest.mark.anyio
async def test_propose_stale_isolated_silent_truth(
    backend: LocalMemoryBackend,
) -> None:
    """Silent truth surfaces as stale; recently surfaced truth doesn't.

    Validates the stale leg in isolation:
    * Long-silent ``MemoryEntry`` (90d) and ``ConfirmedRule`` (70d
      ``last_surfaced_at``) both qualify under the 60d default.
    * Sort order is ``days_since_last_surface`` DESC (entry first).
    * Fresh entry with a recent ``wake_surfaced`` signal has
      ``days_since == 0`` and is excluded.
    * ``evidence_signal_ids`` stays empty — silence is the trigger.
    * ``metabolism_run_id`` is the ``"pending"`` sentinel.
    """
    project_name = "proj-stale-iso"
    now = datetime.now(timezone.utc)

    stale_entry = MemoryEntry(
        project_name=project_name,
        category="decision",
        content="Use Pydantic v2 for all schema definitions.",
        source="manual",
        created_at=now - timedelta(days=90),
        # last_accessed_at left as None — silence is exactly the input.
    )
    stale_rule = ConfirmedRule(
        project_name=project_name,
        pattern="Co-locate tests next to source files.",
        trigger="When adding a new module",
        source_candidate_id="seed-stale-rule",
        confirmed_at=now - timedelta(days=75),
        last_surfaced_at=now - timedelta(days=70),
    )
    fresh_entry = MemoryEntry(
        project_name=project_name,
        category="api",
        content="REST endpoints under /v1/* return JSON only.",
        source="manual",
        created_at=now - timedelta(hours=1),
    )

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    await structured_store.save_memory_entry(stale_entry)
    await structured_store.save_memory_entry(fresh_entry)
    await structured_store.save_confirmed_rule(stale_rule)

    # Wake signal on the fresh entry → newer-of(v2_field=None,
    # signal=now) ⇒ days_since == 0, well below the 60-day threshold.
    fresh_signal = RetrievalSignal(
        project_name=project_name,
        signal_type="wake_surfaced",
        target_kind="memory_entry",
        target_id=fresh_entry.id,
        recorded_at=now - timedelta(hours=1),
    )
    await structured_store.save_retrieval_signal(fresh_signal)

    result = await select_metabolism_pass(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    assert len(result.stale) == 2
    first, second = result.stale

    # Sorted by days_since DESC.
    assert first.target_id == stale_entry.id
    assert first.target_kind == "memory_entry"
    # Allow a 1-day floor for clock granularity (delta.days truncates).
    assert first.days_since_last_surface >= 89
    assert first.evidence_signal_ids == []
    assert first.metabolism_run_id == "pending"

    assert second.target_id == stale_rule.id
    assert second.target_kind == "confirmed_rule"
    assert 60 <= second.days_since_last_surface <= 75
    assert second.evidence_signal_ids == []
    assert second.metabolism_run_id == "pending"

    # Fresh entry must not appear at all.
    assert all(
        candidate.target_id != fresh_entry.id for candidate in result.stale
    )

    # No near-duplicates and a single fresh entry → merge stays empty.
    assert result.merge == []
    # Auto-supersede deferred in v2.3.1.
    assert result.supersede == []


@pytest.mark.anyio
async def test_propose_supersedes_deferred_returns_empty(
    backend: LocalMemoryBackend,
) -> None:
    """Auto-supersede is deferred — proposer returns ``[]`` even when
    historical truths exist in the window.

    This is the deferral contract test: phase 2.4 is intentionally a
    stub until v2.3.2's distinguishing signal is spec'd. Locking in the
    empty result here keeps a future PR from accidentally reactivating
    auto-supersede on similarity alone.
    """
    project_name = "proj-supersede"
    now = datetime.now(timezone.utc)

    # Two historical entries + one historical rule, ``valid_to`` within
    # the default 30d lookback so the window's ``historical_truths``
    # dimension actually populates.
    historical_entry_a = MemoryEntry(
        project_name=project_name,
        category="bug",
        content="Old workaround for SQLite write contention.",
        source="manual",
        created_at=now - timedelta(days=20),
        valid_to=now - timedelta(days=2),
    )
    historical_entry_b = MemoryEntry(
        project_name=project_name,
        category="api",
        content="Deprecated /v0 endpoint shape.",
        source="manual",
        created_at=now - timedelta(days=18),
        valid_to=now - timedelta(days=1),
    )
    historical_rule = ConfirmedRule(
        project_name=project_name,
        pattern="Always use the legacy auth header.",
        trigger="On any inbound request",
        source_candidate_id="seed-historical-rule",
        confirmed_at=now - timedelta(days=25),
        valid_to=now - timedelta(days=3),
    )

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    await structured_store.save_memory_entry(historical_entry_a)
    await structured_store.save_memory_entry(historical_entry_b)
    await structured_store.save_confirmed_rule(historical_rule)

    result = await select_metabolism_pass(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    # The window observed the historical truths (sanity: confirms the
    # fixture actually exercises the historical_truths dimension).
    assert result.window.dimensions["historical_truths"].total_seen >= 3
    # …but the proposer stays a stub regardless.
    assert result.supersede == []


@pytest.mark.anyio
async def test_select_metabolism_pass_integration_merge_and_stale(
    backend: LocalMemoryBackend,
) -> None:
    """One window, three proposer legs.

    Merge fires on a near-duplicate pair, stale fires on long-silent
    truth (entry + rule), and supersede stays ``[]`` per the v2.3.1
    deferral. Also pins the window-shape contract: both duplicates land
    in ``repeat_search_hits``, and pass-level notes stay empty on a
    small fixture (no truncation paths fire).
    """
    project_name = "proj-integration"
    now = datetime.now(timezone.utc)

    duplicate_a = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="Run all tests with pytest, prefer the -q flag.",
        source="manual",
        created_at=now - timedelta(hours=2),
    )
    duplicate_b = MemoryEntry(
        project_name=project_name,
        category="convention",
        content="All tests must run via pytest, with -q for concise output.",
        source="manual",
        created_at=now - timedelta(hours=2),
    )
    stale_entry = MemoryEntry(
        project_name=project_name,
        category="decision",
        content="Long-forgotten decision about logging format.",
        source="manual",
        created_at=now - timedelta(days=90),
    )
    stale_rule = ConfirmedRule(
        project_name=project_name,
        pattern="Always emit structured JSON logs.",
        trigger="In every service",
        source_candidate_id="seed-rule-int",
        confirmed_at=now - timedelta(days=80),
        last_surfaced_at=now - timedelta(days=70),
    )

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    await structured_store.save_memory_entry(duplicate_a)
    await structured_store.save_memory_entry(duplicate_b)
    await structured_store.save_memory_entry(stale_entry)
    await structured_store.save_confirmed_rule(stale_rule)

    # Two search_hit signals per duplicate → each lands in
    # repeat_search_hits and supplies merge evidence.
    for entry_id in (duplicate_a.id, duplicate_b.id):
        for offset in range(2):
            signal = RetrievalSignal(
                project_name=project_name,
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id=entry_id,
                recorded_at=now - timedelta(hours=offset + 1),
            )
            await structured_store.save_retrieval_signal(signal)

    result = await select_metabolism_pass(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    assert len(result.merge) >= 1
    assert len(result.stale) >= 2
    assert result.supersede == []

    # Window structure: both duplicates qualify as repeat_search_hits.
    repeat_dim = result.window.dimensions["repeat_search_hits"]
    assert {duplicate_a.id, duplicate_b.id}.issubset(set(repeat_dim.selected_ids))

    # Pass-level notes only fire on truncation; this small fixture stays
    # well under every cap, so the audit channel stays quiet.
    assert result.notes == []
