"""Smoke test for the v2.3.0 replay window selector scaffold.

Task 3.1 only ships the time-range + empty-dimension contract. The
per-dimension querying lives in 3.2 and gets a fuller test matrix in
3.4 / 3.5. This file just locks in the empty-window invariant.

v2.3.1 task 3.2 swapped the soft-cap estimate from per-id constants
to content-based ``count_tokens``. Tests that previously pinned exact
token totals (derived from ``_TOKENS_PER_*``) now assert on shape and
trim ordering instead — the math is no longer a constant of the
fixture, it depends on the actual content tokenized.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.commands.replay_window import (
    ReplayBudget,
    ReplayDimension,
    ReplayWindow,
    select_replay_window,
)
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    Observation,
    ProceduralCandidate,
    RelationFact,
    RetrievalSignal,
    RuleCandidate,
    Skill,
    SupersedeCandidate,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


@pytest.mark.anyio
async def test_select_replay_window_empty_backend(backend: LocalMemoryBackend) -> None:
    budget = ReplayBudget()

    before = datetime.now(timezone.utc)
    window = await select_replay_window(
        backend, project_name="empty-project", budget=budget
    )
    after = datetime.now(timezone.utc)

    assert isinstance(window, ReplayWindow)

    start, end = window.time_range
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start <= before
    assert after <= end + timedelta(seconds=1)
    expected_span = timedelta(days=budget.signal_lookback_days)
    actual_span = end - start
    assert abs(actual_span - expected_span) < timedelta(seconds=1)

    expected_keys = {
        "observations",
        "pending_candidates",
        "historical_truths",
        "low_success_skills",
        "repeat_search_hits",
    }
    assert set(window.dimensions.keys()) == expected_keys

    for key, dim in window.dimensions.items():
        assert isinstance(dim, ReplayDimension), key
        assert dim.selected_ids == []
        assert dim.truncated is False
        assert dim.total_seen == 0

    assert window.signal_ids == []
    assert window.notes == [f"soft_token_budget: 0/{budget.max_total_tokens}"]


@pytest.mark.anyio
async def test_select_replay_window_one_per_dimension(
    backend: LocalMemoryBackend,
) -> None:
    """One row per dimension + three search-hit signals on the same target."""
    project_name = "replay-dim-smoke"
    now = datetime.now(timezone.utc)

    # 1) recent observation
    observation = Observation(
        session_id="sess-replay-001",
        client="claude-code",
        raw_content="Recent observation for replay window smoke test.",
        content_type="transcript",
        timestamp=now - timedelta(hours=1),
        metadata={"project_name": project_name},
        tags=["smoke"],
    )
    await backend.verbatim_store.save(observation)

    # 2) stale pending rule candidate (created 8 days ago)
    stale_candidate = RuleCandidate(
        project_name=project_name,
        session_id="sess-replay-001",
        pattern="Always parameterize SQL",
        trigger="When writing data access code",
        status="pending",
        created_at=now - timedelta(days=8),
    )
    await backend.structured_store.save_rule_candidate(stale_candidate)

    # 3) historical confirmed rule (valid_to set 1 day ago)
    confirmed_rule = ConfirmedRule(
        project_name=project_name,
        pattern="Old rule that has been superseded",
        trigger="Legacy condition",
        source_candidate_id="seed-candidate-id",
        confirmed_at=now - timedelta(days=10),
        valid_to=now - timedelta(days=1),
    )
    await backend.structured_store.save_confirmed_rule(confirmed_rule)

    # 4) low-success skill: usage_count=5, success_count=0
    skill = Skill(
        project_name=project_name,
        name="Flaky validation loop",
        activation_condition="Need to validate runtime behavior",
        steps=["Step one", "Step two"],
        termination_condition="Validation passes",
        usage_count=5,
        success_count=0,
        failure_count=5,
        success_rate=0.0,
    )
    await backend.structured_store.save_skill(skill)

    # 5) three search_hit signals on the same target_id
    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    repeated_target_id = "memory-entry-replayed"
    for offset in range(3):
        signal = RetrievalSignal(
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=repeated_target_id,
            recorded_at=now - timedelta(hours=offset + 1),
        )
        await structured_store.save_retrieval_signal(signal)

    window = await select_replay_window(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    observations = window.dimensions["observations"]
    assert observations.selected_ids == [observation.id]
    assert observations.total_seen == 1
    assert observations.truncated is False

    pending = window.dimensions["pending_candidates"]
    assert pending.selected_ids == [stale_candidate.id]
    assert pending.total_seen == 1
    assert pending.truncated is False

    historical = window.dimensions["historical_truths"]
    assert historical.selected_ids == [confirmed_rule.id]
    assert historical.total_seen == 1
    assert historical.truncated is False

    skills = window.dimensions["low_success_skills"]
    assert skills.selected_ids == [skill.id]
    assert skills.total_seen == 1
    assert skills.truncated is False

    repeats = window.dimensions["repeat_search_hits"]
    assert repeats.selected_ids == [repeated_target_id]
    assert repeats.total_seen == 1
    assert repeats.truncated is False

    assert len(window.signal_ids) == 3
    # No hard-cap notes should fire (each dimension has 1 row); only the
    # always-on `soft_token_budget` audit note. v2.3.1 task 3.2 made the
    # estimate content-based, so we no longer pin exact token totals —
    # the tiktoken count varies with the actual fixture text. Assert
    # only the note's shape and that it is the sole note (no trim, no
    # truncation, no tokenizer fallback when tiktoken is available).
    assert len(window.notes) == 1, window.notes
    soft_note = window.notes[0]
    assert soft_note.startswith("soft_token_budget: ")
    assert soft_note.endswith(f"/{ReplayBudget().max_total_tokens}")
    estimate_str = soft_note.removeprefix("soft_token_budget: ").split("/")[0]
    estimate_value = int(estimate_str)
    assert estimate_value > 0
    assert estimate_value <= ReplayBudget().max_total_tokens


@pytest.mark.anyio
async def test_observations_hard_cap_with_real_pool_denominator(
    backend: LocalMemoryBackend,
) -> None:
    """When observations overflow the cap, the note carries the true pool size."""
    project_name = "replay-obs-cap"
    now = datetime.now(timezone.utc)

    for index in range(12):
        observation = Observation(
            session_id="sess-cap-001",
            client="claude-code",
            raw_content=f"Observation #{index} for cap test.",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
            tags=["cap"],
        )
        await backend.verbatim_store.save(observation)

    budget = ReplayBudget(max_observations=10)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    obs_dim = window.dimensions["observations"]
    assert len(obs_dim.selected_ids) == 10
    assert obs_dim.truncated is True
    assert obs_dim.total_seen == 12

    assert "truncated_within_observations: 10/12" in window.notes
    assert any(note.startswith("soft_token_budget: ") for note in window.notes)


@pytest.mark.anyio
async def test_repeat_signals_query_cap_note(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the retrieval-signals query hits its 10000 cap, emit the note."""
    project_name = "replay-signals-cap"
    now = datetime.now(timezone.utc)

    # 100 unique target_ids x 100 hits each = 10000 signals, all repeats.
    fake_signals: list[RetrievalSignal] = []
    for target_index in range(100):
        target_id = f"target-{target_index:03d}"
        for hit_index in range(100):
            fake_signals.append(
                RetrievalSignal(
                    project_name=project_name,
                    signal_type="search_hit",
                    target_kind="memory_entry",
                    target_id=target_id,
                    recorded_at=now - timedelta(minutes=hit_index + 1),
                )
            )
    assert len(fake_signals) == 10000

    async def fake_query_retrieval_signals(*args: object, **kwargs: object) -> list[RetrievalSignal]:
        return fake_signals

    monkeypatch.setattr(
        backend.structured_store,
        "query_retrieval_signals",
        fake_query_retrieval_signals,
    )

    window = await select_replay_window(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    assert "retrieval_signals_query_capped" in window.notes


@pytest.mark.anyio
async def test_soft_token_cap_trims_in_priority_order(
    backend: LocalMemoryBackend,
) -> None:
    """Cross-dimension trim drops cheap signals first, observations last."""
    project_name = "replay-soft-cap"
    now = datetime.now(timezone.utc)

    # 3 observations
    observation_ids: list[str] = []
    for index in range(3):
        observation = Observation(
            session_id="sess-soft-001",
            client="claude-code",
            raw_content=f"Soft cap obs #{index}.",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
            tags=["soft"],
        )
        await backend.verbatim_store.save(observation)
        observation_ids.append(observation.id)

    # 2 stale pending rule candidates (8 days old)
    for index in range(2):
        candidate = RuleCandidate(
            project_name=project_name,
            session_id="sess-soft-001",
            pattern=f"Rule #{index}",
            trigger=f"Trigger #{index}",
            status="pending",
            created_at=now - timedelta(days=8, hours=index),
        )
        await backend.structured_store.save_rule_candidate(candidate)

    # 2 historical confirmed rules (valid_to = now - 1 day)
    for index in range(2):
        rule = ConfirmedRule(
            project_name=project_name,
            pattern=f"Historical rule #{index}",
            trigger=f"Trigger #{index}",
            source_candidate_id=f"seed-{index}",
            confirmed_at=now - timedelta(days=10),
            valid_to=now - timedelta(days=1, minutes=index),
        )
        await backend.structured_store.save_confirmed_rule(rule)

    # 2 low-success skills (usage_count=5, success_count=0)
    for index in range(2):
        skill = Skill(
            project_name=project_name,
            name=f"Flaky skill #{index}",
            activation_condition="cond",
            steps=["step"],
            termination_condition="done",
            usage_count=5,
            success_count=0,
            failure_count=5,
            success_rate=0.0,
        )
        await backend.structured_store.save_skill(skill)

    # 4 repeat-search-hit targets, each with 2 signals
    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)
    for target_index in range(4):
        target_id = f"repeat-target-{target_index}"
        for hit_index in range(2):
            signal = RetrievalSignal(
                project_name=project_name,
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id=target_id,
                recorded_at=now - timedelta(hours=hit_index + 1),
            )
            await structured_store.save_retrieval_signal(signal)

    # v2.3.1 task 3.2: estimate is content-based, not per-id constant,
    # so the exact 800/1000 arithmetic from v2.3.0 no longer holds.
    # We still want to verify the trim cascade: cheap-signals-first,
    # observations-last. Set a tiny budget so trim definitely fires
    # all the way through and most dims drain; then assert on shape
    # and trim order rather than on the exact estimate value.
    budget = ReplayBudget(max_total_tokens=1)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    # Trim walks _TRIM_ORDER draining cheaper dims to empty before
    # touching observations. With max_total_tokens=1 every cheaper
    # dim ends up empty.
    assert window.dimensions["repeat_search_hits"].selected_ids == []
    assert window.dimensions["low_success_skills"].selected_ids == []
    assert window.dimensions["historical_truths"].selected_ids == []
    assert window.dimensions["pending_candidates"].selected_ids == []
    # Observations are the last dim in _TRIM_ORDER. Some — possibly
    # all — get popped depending on per-id token counts; the contract
    # is "trim from the tail until budget is met, but never go below
    # zero ids" (the loop stops at empty).
    assert len(window.dimensions["observations"].selected_ids) <= len(observation_ids)

    # All repeats trimmed -> all supporting signal ids dropped.
    assert window.signal_ids == []

    assert (
        "trimmed_for_token_budget: "
        "repeat_search_hits,low_success_skills,historical_truths,"
        "pending_candidates,observations"
    ) in window.notes
    # Soft-budget audit note carries an exact post-trim integer; we
    # don't pin the exact number anymore (content-based) but verify
    # the format and that the value is non-negative.
    soft_note = next(
        note for note in window.notes if note.startswith("soft_token_budget: ")
    )
    assert soft_note.endswith("/1")
    estimate_value = int(
        soft_note.removeprefix("soft_token_budget: ").split("/")[0]
    )
    assert estimate_value >= 0


@pytest.mark.anyio
async def test_soft_token_cap_no_trim_when_under_budget(
    backend: LocalMemoryBackend,
) -> None:
    """When the estimate fits, only the audit note is emitted."""
    project_name = "replay-soft-cap-quiet"
    now = datetime.now(timezone.utc)

    observation = Observation(
        session_id="sess-quiet",
        client="claude-code",
        raw_content="One single observation.",
        content_type="transcript",
        timestamp=now - timedelta(hours=1),
        metadata={"project_name": project_name},
        tags=["quiet"],
    )
    await backend.verbatim_store.save(observation)

    window = await select_replay_window(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    assert not any(note.startswith("trimmed_for_token_budget") for note in window.notes)
    # v2.3.1 task 3.2: estimate is content-based, so we don't pin a
    # specific token count. Just verify the audit note shape and that
    # the estimate fits the budget.
    soft_note = next(
        note for note in window.notes if note.startswith("soft_token_budget: ")
    )
    assert soft_note.endswith(f"/{ReplayBudget().max_total_tokens}")
    estimate_value = int(
        soft_note.removeprefix("soft_token_budget: ").split("/")[0]
    )
    assert 0 < estimate_value <= ReplayBudget().max_total_tokens


# ---------------------------------------------------------------------------
# Task 3.4 — per-dimension hard-cap fixtures + integration test
# ---------------------------------------------------------------------------


def _assert_other_dims_empty(
    window: ReplayWindow, *, except_dim: str
) -> None:
    """Helper: every dimension except ``except_dim`` is empty + un-truncated."""
    for name, dim in window.dimensions.items():
        if name == except_dim:
            continue
        assert dim.selected_ids == [], name
        assert dim.truncated is False, name


@pytest.mark.anyio
async def test_observations_hard_cap_truncates_at_dim_boundary(
    backend: LocalMemoryBackend,
) -> None:
    """observations: cap=3, seed 5 → kept=3, true pool=5."""
    project_name = "replay-3-4-obs"
    now = datetime.now(timezone.utc)

    for index in range(5):
        observation = Observation(
            session_id="sess-3-4-obs",
            client="claude-code",
            raw_content=f"Obs #{index} for dim cap test.",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
        )
        await backend.verbatim_store.save(observation)

    budget = ReplayBudget(max_observations=3, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    obs = window.dimensions["observations"]
    assert len(obs.selected_ids) == 3
    assert obs.truncated is True
    assert obs.total_seen == 5

    assert "truncated_within_observations: 3/5" in window.notes
    _assert_other_dims_empty(window, except_dim="observations")


@pytest.mark.anyio
async def test_pending_candidates_hard_cap_truncates_at_dim_boundary(
    backend: LocalMemoryBackend,
) -> None:
    """pending_candidates: cap=3, seed 5 stale RuleCandidates → kept=3, pool=5."""
    project_name = "replay-3-4-pending"
    now = datetime.now(timezone.utc)

    for index in range(5):
        candidate = RuleCandidate(
            project_name=project_name,
            session_id="sess-3-4-pending",
            pattern=f"Pattern #{index}",
            trigger=f"Trigger #{index}",
            status="pending",
            # Spread 8d to 12d to make sort deterministic (oldest first).
            created_at=now - timedelta(days=8, hours=index),
        )
        await backend.structured_store.save_rule_candidate(candidate)

    budget = ReplayBudget(max_pending_candidates=3, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    pending = window.dimensions["pending_candidates"]
    assert len(pending.selected_ids) == 3
    assert pending.truncated is True
    assert pending.total_seen == 5

    assert "truncated_within_pending_candidates: 3/5" in window.notes
    _assert_other_dims_empty(window, except_dim="pending_candidates")


@pytest.mark.anyio
async def test_historical_truths_hard_cap_truncates_at_dim_boundary(
    backend: LocalMemoryBackend,
) -> None:
    """historical_truths: cap=3, seed 5 superseded ConfirmedRules → kept=3, pool=5."""
    project_name = "replay-3-4-historical"
    now = datetime.now(timezone.utc)

    for index in range(5):
        rule = ConfirmedRule(
            project_name=project_name,
            pattern=f"Historical pattern #{index}",
            trigger=f"Trigger #{index}",
            source_candidate_id=f"seed-{index}",
            confirmed_at=now - timedelta(days=15),
            # 1d apart so sort by valid_to DESC is deterministic.
            valid_to=now - timedelta(days=index + 1),
        )
        await backend.structured_store.save_confirmed_rule(rule)

    budget = ReplayBudget(max_historical_truths=3, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    historical = window.dimensions["historical_truths"]
    assert len(historical.selected_ids) == 3
    assert historical.truncated is True
    assert historical.total_seen == 5

    assert "truncated_within_historical_truths: 3/5" in window.notes
    _assert_other_dims_empty(window, except_dim="historical_truths")


@pytest.mark.anyio
async def test_low_success_skills_hard_cap_truncates_at_dim_boundary(
    backend: LocalMemoryBackend,
) -> None:
    """low_success_skills: cap=3, seed 5 zero-success Skills → kept=3, pool=5."""
    project_name = "replay-3-4-skills"

    for index in range(5):
        skill = Skill(
            project_name=project_name,
            name=f"Flaky skill #{index}",
            activation_condition="cond",
            steps=["step"],
            termination_condition="done",
            usage_count=5,
            success_count=0,
            failure_count=5,
            success_rate=0.0,
        )
        await backend.structured_store.save_skill(skill)

    budget = ReplayBudget(max_low_success_skills=3, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    skills = window.dimensions["low_success_skills"]
    assert len(skills.selected_ids) == 3
    assert skills.truncated is True
    assert skills.total_seen == 5

    assert "truncated_within_low_success_skills: 3/5" in window.notes
    _assert_other_dims_empty(window, except_dim="low_success_skills")


@pytest.mark.anyio
async def test_repeat_search_hits_hard_cap_truncates_at_dim_boundary(
    backend: LocalMemoryBackend,
) -> None:
    """repeat_search_hits: cap=3, seed 5 targets x 2 hits → kept=3, pool=5."""
    project_name = "replay-3-4-repeats"
    now = datetime.now(timezone.utc)

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)

    for target_index in range(5):
        target_id = f"repeat-target-{target_index}"
        for hit_index in range(2):
            signal = RetrievalSignal(
                project_name=project_name,
                signal_type="search_hit",
                target_kind="memory_entry",
                target_id=target_id,
                recorded_at=now - timedelta(hours=hit_index + 1),
            )
            await structured_store.save_retrieval_signal(signal)

    budget = ReplayBudget(max_repeat_search_hits=3, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    repeats = window.dimensions["repeat_search_hits"]
    assert len(repeats.selected_ids) == 3
    assert repeats.truncated is True
    assert repeats.total_seen == 5

    assert "truncated_within_repeat_search_hits: 3/5" in window.notes
    _assert_other_dims_empty(window, except_dim="repeat_search_hits")


@pytest.mark.anyio
async def test_cap_zero_means_dimension_disabled(
    backend: LocalMemoryBackend,
) -> None:
    """cap=0 disables a dimension: no ids kept, but the pool is still counted."""
    project_name = "replay-3-4-cap-zero"
    now = datetime.now(timezone.utc)

    for index in range(3):
        observation = Observation(
            session_id="sess-3-4-cap-zero",
            client="claude-code",
            raw_content=f"Obs #{index}.",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
        )
        await backend.verbatim_store.save(observation)

    budget = ReplayBudget(max_observations=0, max_total_tokens=1_000_000)
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )

    obs = window.dimensions["observations"]
    assert obs.selected_ids == []
    assert obs.truncated is True
    assert obs.total_seen == 3

    assert "truncated_within_observations: 0/3" in window.notes


@pytest.mark.anyio
async def test_select_replay_window_realistic_mixed_counts(
    backend: LocalMemoryBackend,
) -> None:
    """Integration: realistic counts trigger soft trim but no hard cap.

    v2.3.1 task 3.2: estimate is now content-based, so the v2.3.0
    arithmetic (50*400 + 30*350 + ... = 38020) no longer holds. The
    test still locks in the cross-dim trim contract: cheaper signals
    drain first, observations last; total_seen is preserved through
    the soft-cap walk; no hard-cap note fires when dim caps are
    generous. We use a small ``max_total_tokens`` to force the trim
    cascade regardless of how the actual content tokenizes.
    """
    project_name = "replay-3-4-integration"
    now = datetime.now(timezone.utc)

    structured_store = backend.structured_store
    assert isinstance(structured_store, LocalStructuredStore)

    # 50 observations (within default 30d lookback).
    for index in range(50):
        observation = Observation(
            session_id="sess-3-4-int",
            client="claude-code",
            raw_content=f"Integration obs #{index}.",
            content_type="transcript",
            timestamp=now - timedelta(hours=index + 1),
            metadata={"project_name": project_name},
        )
        await backend.verbatim_store.save(observation)

    # 30 stale pending candidates: 10 each of rule/supersede/procedural,
    # all created 8d+ ago.
    for index in range(10):
        await structured_store.save_rule_candidate(
            RuleCandidate(
                project_name=project_name,
                session_id="sess-3-4-int",
                pattern=f"Rule pattern #{index}",
                trigger=f"Rule trigger #{index}",
                status="pending",
                created_at=now - timedelta(days=8, hours=index),
            )
        )
    for index in range(10):
        await structured_store.save_supersede_candidate(
            SupersedeCandidate(
                project_name=project_name,
                target_type="memory_entry",
                target_id=f"target-entry-{index}",
                replacement_type="memory_entry",
                replacement_id=f"replacement-entry-{index}",
                reason=f"Reason #{index}",
                evidence=f"Evidence #{index}",
                status="pending",
                created_at=now - timedelta(days=8, hours=index + 12),
            )
        )
    for index in range(10):
        await structured_store.save_procedural_candidate(
            ProceduralCandidate(
                project_name=project_name,
                activation_condition=f"When stale procedural #{index} fires",
                steps=[f"step {index}-a", f"step {index}-b"],
                termination_condition="terminates",
                status="pending",
                created_at=now - timedelta(days=9, hours=index),
            )
        )

    # 20 historical truths: 7 entries + 7 rules + 6 facts, valid_to spread
    # across the last 25 days (well within the 30d lookback).
    for index in range(7):
        await structured_store.save_memory_entry(
            MemoryEntry(
                project_name=project_name,
                category="convention",
                content=f"Historical entry #{index}",
                source="manual",
                created_at=now - timedelta(days=40),
                valid_to=now - timedelta(days=index + 1),
            )
        )
    for index in range(7):
        await structured_store.save_confirmed_rule(
            ConfirmedRule(
                project_name=project_name,
                pattern=f"Historical rule #{index}",
                trigger=f"Trigger #{index}",
                source_candidate_id=f"seed-rule-{index}",
                confirmed_at=now - timedelta(days=40),
                valid_to=now - timedelta(days=index + 8),
            )
        )
    for index in range(6):
        await structured_store.save_relation_fact(
            RelationFact(
                project_name=project_name,
                source_entity=f"src-{index}",
                target_entity=f"tgt-{index}",
                relation_type="depends_on",
                evidence=f"Evidence #{index}",
                source="manual",
                created_at=now - timedelta(days=40),
                valid_to=now - timedelta(days=index + 15),
            )
        )

    # 10 low-success skills: 5 with success_rate=0.3, 5 with success_rate=0.0.
    for index in range(5):
        await structured_store.save_skill(
            Skill(
                project_name=project_name,
                name=f"Mid-flaky skill #{index}",
                activation_condition="cond",
                steps=["step"],
                termination_condition="done",
                usage_count=10,
                success_count=3,
                failure_count=7,
                success_rate=0.3,
            )
        )
    for index in range(5):
        await structured_store.save_skill(
            Skill(
                project_name=project_name,
                name=f"Zero-success skill #{index}",
                activation_condition="cond",
                steps=["step"],
                termination_condition="done",
                usage_count=10,
                success_count=0,
                failure_count=10,
                success_rate=0.0,
            )
        )

    # 8 repeat-search-hit targets, each with 2 hits = 16 signals.
    for target_index in range(8):
        target_id = f"int-repeat-target-{target_index}"
        for hit_index in range(2):
            await structured_store.save_retrieval_signal(
                RetrievalSignal(
                    project_name=project_name,
                    signal_type="search_hit",
                    target_kind="memory_entry",
                    target_id=target_id,
                    recorded_at=now - timedelta(hours=hit_index + 1),
                )
            )

    # Force trim cascade with a small budget — content-based token
    # totals depend on actual fixture text, so we don't rely on the
    # default 16000 budget triggering a specific arithmetic outcome.
    target = 100
    window = await select_replay_window(
        backend,
        project_name=project_name,
        budget=ReplayBudget(max_total_tokens=target),
    )

    # Sanity: selector saw the full pool — total_seen is preserved across
    # soft trim (only selected_ids shrinks).
    assert window.dimensions["observations"].total_seen == 50
    assert window.dimensions["pending_candidates"].total_seen == 30
    assert window.dimensions["historical_truths"].total_seen == 20
    assert window.dimensions["low_success_skills"].total_seen == 10
    assert window.dimensions["repeat_search_hits"].total_seen == 8

    # Soft cap drains all four cheaper dims; observations may keep some
    # ids depending on per-id content tokens (the loop stops once the
    # estimate fits the budget).
    obs_dim = window.dimensions["observations"]
    assert obs_dim.truncated is True
    assert len(obs_dim.selected_ids) <= 50
    for cheaper in (
        "pending_candidates",
        "historical_truths",
        "low_success_skills",
        "repeat_search_hits",
    ):
        dim = window.dimensions[cheaper]
        assert dim.selected_ids == [], cheaper
        assert dim.truncated is True, cheaper

    # All repeat targets dropped -> all supporting signal ids dropped.
    assert window.signal_ids == []

    # Notes: the trim chain ran top-to-bottom across all five dims.
    assert (
        "trimmed_for_token_budget: "
        "repeat_search_hits,low_success_skills,historical_truths,"
        "pending_candidates,observations"
    ) in window.notes
    soft_note = next(
        note for note in window.notes if note.startswith("soft_token_budget: ")
    )
    assert soft_note.endswith(f"/{target}")

    # No hard cap hit anywhere — all dim caps are well above the seeded
    # pool; every "truncated" flag here came from the soft-cap walk.
    for note in window.notes:
        assert not note.startswith("truncated_within_"), note


# ---------------------------------------------------------------------------
# Task 3.4 — third-tier dim-weight fallback (selector-level)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dim_weight_fallback_when_content_fetch_returns_none(
    backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-id token cost falls back to ``_DIM_TOKEN_WEIGHT[dim]`` on fetch miss.

    Validates the third leg of the token-estimate fallback chain:
    tiktoken → char-heuristic (both inside ``count_tokens``) →
    dim-weight constant (selector-side). When ``_fetch_content_for_id``
    returns ``None`` for every selected id (deleted blob, mid-flight
    schema change, or any other resolution failure), the soft-cap
    estimate must still be sensible — it falls back to the per-dim
    constant from ``_DIM_TOKEN_WEIGHT``.
    """
    from harness_mem.commands import replay_window

    project_name = "v231-3-4-fallback"
    now = datetime.now(timezone.utc)

    # Seed exactly one observation so the observations dim has a
    # selected id; we then force its content fetch to fail.
    observation = Observation(
        session_id="sess-fallback",
        client="claude-code",
        raw_content="One observation seed for dim-weight fallback.",
        content_type="transcript",
        timestamp=now - timedelta(hours=1),
        metadata={"project_name": project_name},
    )
    await backend.verbatim_store.save(observation)

    async def fake_fetch(
        *_args: object, **_kwargs: object
    ) -> str | None:
        return None

    monkeypatch.setattr(replay_window, "_fetch_content_for_id", fake_fetch)

    window = await select_replay_window(
        backend, project_name=project_name, budget=ReplayBudget()
    )

    # Sanity: only the observations dim has a selected id (one).
    assert window.dimensions["observations"].selected_ids == [observation.id]

    soft_note = next(
        note for note in window.notes if note.startswith("soft_token_budget: ")
    )
    estimate_value = int(
        soft_note.removeprefix("soft_token_budget: ").split("/")[0]
    )

    # With one id in observations and content fetch returning None for
    # every dim, the estimate equals exactly the per-dim weight for
    # observations (400). No tokenizer fallback note fires because
    # ``count_tokens`` was never called (count_tokens_calls == 0).
    expected = replay_window._DIM_TOKEN_WEIGHT["observations"]
    assert estimate_value == expected
    assert not any(
        note.startswith("tokenizer_fallback") for note in window.notes
    )
