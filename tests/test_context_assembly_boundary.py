"""Boundary tests for the v2.5.0 Plan_Assembler (Tasks 8.2 / 8.3).

This module covers the *boundary* invariants of an assembled
:class:`ContextAssemblyPlan` — the rules about which records may surface in
which layer. Task 8.2 lands **Property 8: L4 Drilldown-Only** here; task 8.3
extends this same file with **Property 7: Accepted-Only Boundary**, so the
module is structured around shared, self-contained seed helpers that both
slices reuse.

Because the L4 layer is produced by the assembler against a *seeded* backend,
these are integration-style property tests: each generated example seeds varied
data (Hypothesis-driven counts, query on/off, distinctive content tokens) and
asserts the boundary property holds for the resulting plan.

Test infrastructure (steering rules P1 数据路径隔离 / 异步资源清理):

* Every backend is created under a ``tmp_path``-isolated directory — never the
  real ``~/.harness-mem/``.
* Hypothesis reuses the function-scoped ``data_dir`` fixture across generated
  examples, which would let state bleed between examples. To keep each example
  isolated, :func:`_fresh_backend` builds the backend against a *unique*
  sub-directory (``ex-<uuid>``) under the function's ``data_dir``.
* Every example initialises and closes its own backend in a ``finally`` block.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


# --------------------------------------------------------------------------- #
# Shared seed helpers (reused by Task 8.3)
# --------------------------------------------------------------------------- #
def _fresh_backend(base_dir: Path) -> LocalMemoryBackend:
    """Build + init a backend under a unique sub-directory of ``base_dir``.

    Hypothesis reuses the function-scoped ``data_dir`` fixture across generated
    examples; a fresh ``ex-<uuid>`` sub-directory per example keeps each
    example's store fully isolated so no state bleeds between examples. The
    caller owns the lifecycle and MUST close the backend in a ``finally`` block.
    """
    backend = LocalMemoryBackend(base_dir / f"ex-{uuid4().hex}")
    run(backend.init())
    return backend


def _seed_observation(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    raw_content: str,
    session_id: str = "boundary-session",
) -> Observation:
    """Save a raw observation via the same store surface L4 expands.

    ``metadata`` carries ``project_name`` so project-scoped observation search
    (L4's ``evidence:topic_match`` source) can match it. ``raw_content`` carries
    the distinctive token the leak assertions search for.
    """
    observation = Observation(
        session_id=session_id,
        client="claude-code",
        raw_content=raw_content,
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session"],
    )
    run(backend.verbatim_store.save(observation))
    return observation


def _seed_accepted_entry(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    content: str,
    confidence: float = 0.9,
    observation_ids: list[str] | None = None,
    valid_to: datetime | None = None,
) -> MemoryEntry:
    """Save an accepted MemoryEntry via the same store surface L1 / L4 read.

    ``observation_ids`` populate ``provenance.observation_ids`` so the entry
    becomes an L1 truth whose backing observations L4 surfaces as
    ``evidence:supports_L1`` drilldowns. ``valid_to`` is left ``None`` for
    current truth and set for historical (superseded) truth, which L4 surfaces
    on its own as a historical drilldown.
    """
    provenance = None
    if observation_ids is not None:
        provenance = {"observation_ids": observation_ids}
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content,
        confidence=confidence,
        status="accepted",
        source="manual",
        provenance=provenance,
        valid_to=valid_to,
    )
    run(backend.structured_store.save_memory_entry(entry))
    return entry


# --------------------------------------------------------------------------- #
# Hypothesis settings + strategies
# --------------------------------------------------------------------------- #
# Integration property: each example spins up an isolated SQLite-backed store,
# so keep the example count modest while still exercising varied shapes. The
# function-scoped ``data_dir`` fixture is reused across examples by design
# (per-example isolation handled via ``_fresh_backend``); suppress the health
# check rather than reset state.
_PBT_SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Distinctive raw-content token: uppercase letters keep it FTS-friendly and
# unlikely to collide with any ``why_included`` / ``read_surface`` literal.
_tokens = st.text(
    alphabet=st.characters(min_codepoint=65, max_codepoint=90),  # A-Z
    min_size=6,
    max_size=10,
)

# Query word embedded verbatim in the topic observations so L4's
# ``evidence:topic_match`` source (project-scoped observation search) matches.
_QUERY_WORD = "telemetry"


def _assert_property8(layer, seeded_raw_texts: list[str]) -> None:
    """Assert Property 8 (L4 Drilldown-Only) on a built L4 layer.

    Every L4 entry must carry a non-null drilldown with a non-empty
    ``source_id`` and ``read_surface``, at least one non-empty ``source_id``,
    and must embed no inline raw observation text in ``summary`` (Req 7.1, 7.6).
    """
    for entry in layer.entries:
        # Pointer present and fully populated (Req 7.1, 7.2, 7.6).
        assert entry.drilldown is not None
        assert isinstance(entry.drilldown.source_id, str)
        assert entry.drilldown.source_id.strip() != ""
        assert isinstance(entry.drilldown.read_surface, str)
        assert entry.drilldown.read_surface.strip() != ""

        # Traceable to at least one non-empty source id (Req 8.1).
        assert len(entry.source_ids) >= 1
        assert all(isinstance(sid, str) and sid != "" for sid in entry.source_ids)

        # No inline raw observation text leaks into the layer (Req 7.1).
        for raw_text in seeded_raw_texts:
            assert raw_text not in entry.summary


# --------------------------------------------------------------------------- #
# Property 8 — L4 Drilldown-Only (Req 7.1, 7.6)
# --------------------------------------------------------------------------- #
@_PBT_SETTINGS
@given(
    n_supporting_obs=st.integers(min_value=0, max_value=4),
    n_topic_obs=st.integers(min_value=0, max_value=4),
    n_historical=st.integers(min_value=0, max_value=4),
    use_query=st.booleans(),
    token=_tokens,
)
def test_property8_l4_drilldown_only(
    data_dir: Path,
    n_supporting_obs: int,
    n_topic_obs: int,
    n_historical: int,
    use_query: bool,
    token: str,
) -> None:
    """Validates: Requirements 7.1, 7.6.

    Across varied seeded data — observations backing accepted L1 truth
    (``evidence:supports_L1``), query-matched observations
    (``evidence:topic_match``), and historical superseded entries — every L4
    entry is a drilldown pointer with a non-empty ``source_id`` /
    ``read_surface`` and carries no inline raw observation text.
    """
    project_name = "l4-drilldown-prop"
    marker = f"ZZRAW{token}RAWZZ"
    now = datetime.now(timezone.utc)
    seeded_raw_texts: list[str] = []

    backend = _fresh_backend(data_dir)
    try:
        # Source 1 — observations backing an accepted current-truth L1 entry.
        if n_supporting_obs > 0:
            supporting_ids: list[str] = []
            for i in range(n_supporting_obs):
                raw = f"{marker} supporting evidence detail {i}"
                seeded_raw_texts.append(raw)
                obs = _seed_observation(
                    backend, project_name=project_name, raw_content=raw
                )
                supporting_ids.append(obs.id)
            _seed_accepted_entry(
                backend,
                project_name=project_name,
                content="accepted truth backed by observations",
                observation_ids=supporting_ids,
            )

        # Source 2 — query-matched observations (only surface when a query is on).
        for i in range(n_topic_obs):
            raw = f"{marker} {_QUERY_WORD} pipeline observation {i}"
            seeded_raw_texts.append(raw)
            _seed_observation(backend, project_name=project_name, raw_content=raw)

        # Source 3 — historical (superseded) accepted entries.
        for i in range(n_historical):
            content = f"{marker} historical decision {i}"
            seeded_raw_texts.append(content)
            _seed_accepted_entry(
                backend,
                project_name=project_name,
                content=content,
                valid_to=now - timedelta(days=i + 1),
            )

        query = _QUERY_WORD if use_query else None
        plan = run(
            assemble_context_plan(backend, project_name=project_name, query=query)
        )
    finally:
        run(backend.close())

    _assert_property8(plan.layer("L4"), seeded_raw_texts)


# --------------------------------------------------------------------------- #
# Populated integration case — guarantees Property 8 is exercised non-vacuously
# --------------------------------------------------------------------------- #
def test_l4_populated_from_all_sources_satisfies_property8(data_dir: Path) -> None:
    """A scenario seeding all three L4 sources yields a non-empty L4 whose
    every entry is a drilldown pointer with no inline raw text (Req 7.1, 7.6).

    This pins the populated case so the property test above is never satisfied
    only by empty L4 layers.
    """
    project_name = "l4-all-sources"
    marker = "ZZRAWFIXEDRAWZZ"
    now = datetime.now(timezone.utc)
    seeded_raw_texts: list[str] = []

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Source 1 — two observations backing an accepted L1 entry.
        supporting_ids = []
        for i in range(2):
            raw = f"{marker} supporting detail {i}"
            seeded_raw_texts.append(raw)
            obs = _seed_observation(
                backend, project_name=project_name, raw_content=raw
            )
            supporting_ids.append(obs.id)
        _seed_accepted_entry(
            backend,
            project_name=project_name,
            content="accepted truth backed by observations",
            observation_ids=supporting_ids,
        )

        # Source 2 — a query-matched observation.
        topic_raw = f"{marker} {_QUERY_WORD} pipeline observation"
        seeded_raw_texts.append(topic_raw)
        _seed_observation(backend, project_name=project_name, raw_content=topic_raw)

        # Source 3 — a historical (superseded) accepted entry.
        historical_content = f"{marker} historical decision"
        seeded_raw_texts.append(historical_content)
        historical_entry = _seed_accepted_entry(
            backend,
            project_name=project_name,
            content=historical_content,
            valid_to=now - timedelta(days=1),
        )

        plan = run(
            assemble_context_plan(
                backend, project_name=project_name, query=_QUERY_WORD
            )
        )
    finally:
        run(backend.close())

    l4 = plan.layer("L4")

    # Non-vacuous: every L4 source contributed at least one drilldown.
    assert len(l4.entries) >= 1
    reasons = {entry.why_included for entry in l4.entries}
    assert "evidence:supports_L1" in reasons
    assert "evidence:topic_match" in reasons

    # The historical entry surfaces only as an L4 drilldown, tagged historical.
    historical_l4 = [
        e for e in l4.entries if e.source_ids == [historical_entry.id]
    ]
    assert len(historical_l4) == 1
    assert historical_l4[0].truth_status == "historical"
    assert historical_l4[0].drilldown is not None
    assert historical_l4[0].drilldown.read_surface == "read_api.get_memory_entry"

    # Property 8 holds for the populated layer.
    _assert_property8(l4, seeded_raw_texts)


# --------------------------------------------------------------------------- #
# Property 7 seed helpers (accepted-only boundary)
# --------------------------------------------------------------------------- #
# These extend the shared helpers above without modifying them: Property 7
# needs sources Property 8 does not (pending candidates, confirmed rules,
# handoffs, retrieval signals) to prove the accepted-only boundary holds across
# every layer that carries truth.
def _seed_pending_entry(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    content: str,
    confidence: float = 0.99,
) -> MemoryEntry:
    """Save a *pending* MemoryEntry — a candidate the human has not accepted.

    A pending candidate must never surface as confirmed truth in L1 or in the
    recently-surfaced (truth) portion of L2 (Req 3.5, 10.2). Confidence is kept
    high on purpose so the boundary — not a low score — is what excludes it.
    """
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content,
        confidence=confidence,
        status="pending",
        source="manual",
    )
    run(backend.structured_store.save_memory_entry(entry))
    return entry


def _seed_confirmed_rule(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    pattern: str,
    confirmed_at: datetime,
) -> ConfirmedRule:
    """Save a current ConfirmedRule via the same store surface L1 reads.

    Confirmed rules are the highest-tier eligible L1 truth; their ids are
    therefore valid L1 ``source_ids`` for Property 7's point 2.
    """
    rule = ConfirmedRule(
        project_name=project_name,
        pattern=pattern,
        trigger="when relevant",
        source_candidate_id="seed-candidate",
        confirmed_at=confirmed_at,
    )
    run(backend.structured_store.save_confirmed_rule(rule))
    return rule


def _seed_handoff(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    summary: str,
    last_activity: datetime,
) -> TaskHandoff:
    """Save a TaskHandoff via the same store surface L2's Part A reads.

    Handoff entries are legitimately referenced by L2 (``active:recent_handoff``
    → handoff id), so they must NOT be treated as forbidden references when
    asserting the accepted-only boundary on L2.
    """
    handoff = TaskHandoff(
        project_name=project_name,
        task_id="seed-task",
        summary=summary,
        last_activity=last_activity,
    )
    run(backend.structured_store.save_task_handoff(handoff))
    return handoff


def _seed_retrieval_signal(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_id: str,
    signal_type: str,
    recorded_at: datetime,
) -> RetrievalSignal:
    """Save an in-window RetrievalSignal pointing at a memory entry.

    Pointing a signal at a pending / historical entry forces the L2
    recently-surfaced derivation to actually consider — and then *exclude* — it,
    so the boundary is tested on the live code path rather than vacuously.
    """
    signal = RetrievalSignal(
        project_name=project_name,
        signal_type=signal_type,
        target_kind="memory_entry",
        target_id=target_id,
        recorded_at=recorded_at,
    )
    run(backend.structured_store.save_retrieval_signal(signal))
    return signal


def _assert_property7(
    plan,
    *,
    pending_ids: list[str],
    historical_ids: list[str],
    eligible_l1_ids: set[str],
) -> None:
    """Assert Property 7 (Accepted-Only Boundary) on an assembled plan.

    1. No L1 entry and no L2 *truth* entry (``active:recently_surfaced``)
       references a pending or historical (``valid_to`` set) record
       (Req 3.5, 10.1, 10.2).
    2. Every L1 truth entry resolves to a confirmed rule or an accepted
       current-truth entry (Req 3.1).
    3. Historical records surface ONLY as L4 drilldowns, tagged
       ``truth_status="historical"`` (Req 10.1).

    L2 handoff entries (``active:recent_handoff``) reference handoff ids, which
    are not memory-entry ids, so they are intentionally outside the forbidden
    set checked in point 1.
    """
    forbidden = set(pending_ids) | set(historical_ids)
    l1 = plan.layer("L1")
    l2 = plan.layer("L2")

    # --- Point 1a: no L1 entry references a pending or historical record. ---
    for entry in l1.entries:
        assert forbidden.isdisjoint(entry.source_ids), (
            f"L1 leaked a forbidden record: {entry.source_ids}"
        )

    # --- Point 1b: no L2 recently-surfaced (truth) entry does either. ---
    for entry in l2.entries:
        if entry.why_included == "active:recently_surfaced":
            assert forbidden.isdisjoint(entry.source_ids), (
                f"L2 recently-surfaced leaked a forbidden record: {entry.source_ids}"
            )

    # --- Point 2: every L1 truth entry resolves to an eligible source. ---
    for entry in l1.entries:
        assert entry.why_included in {
            "essential:confirmed_rule",
            "essential:high_confidence_truth",
        }
        assert len(entry.source_ids) >= 1
        assert all(sid in eligible_l1_ids for sid in entry.source_ids), (
            f"L1 entry resolves to an ineligible source: {entry.source_ids}"
        )

    # --- Point 3: historical records surface ONLY as L4 drilldowns. ---
    for hist_id in historical_ids:
        for layer in plan.layers:
            for entry in layer.entries:
                if hist_id in entry.source_ids:
                    assert layer.layer == "L4", (
                        f"historical {hist_id} surfaced outside L4 in {layer.layer}"
                    )
                    assert entry.truth_status == "historical"
                    assert entry.drilldown is not None
                    assert entry.drilldown.source_id == hist_id


# --------------------------------------------------------------------------- #
# Property 7 — Accepted-Only Boundary (Req 3.1, 3.5, 10.1, 10.2)
# --------------------------------------------------------------------------- #
@_PBT_SETTINGS
@given(
    n_accepted=st.integers(min_value=0, max_value=3),
    n_pending=st.integers(min_value=0, max_value=3),
    n_historical=st.integers(min_value=0, max_value=3),
    n_rules=st.integers(min_value=0, max_value=3),
    use_query=st.booleans(),
    token=_tokens,
)
def test_property7_accepted_only_boundary(
    data_dir: Path,
    n_accepted: int,
    n_pending: int,
    n_historical: int,
    n_rules: int,
    use_query: bool,
    token: str,
) -> None:
    """Validates: Requirements 3.1, 3.5, 10.1, 10.2.

    Across varied seeded data — accepted current truth, pending candidates,
    historical (superseded) truth, and confirmed rules, each pending /
    historical record additionally pointed at by an in-window retrieval signal
    so the L2 recently-surfaced path must actively exclude it — the
    accepted-only boundary holds: no L1 / L2-truth entry references a pending
    or historical record, every L1 truth entry resolves to a confirmed rule or
    accepted current-truth entry, and historical records surface only as L4
    drilldowns.
    """
    project_name = "accepted-only-prop"
    marker = f"ZZ{token}ZZ"
    now = datetime.now(timezone.utc)

    pending_ids: list[str] = []
    historical_ids: list[str] = []
    eligible_l1_ids: set[str] = set()

    backend = _fresh_backend(data_dir)
    try:
        # Confirmed rules (current) — eligible L1 truth.
        for i in range(n_rules):
            rule = _seed_confirmed_rule(
                backend,
                project_name=project_name,
                pattern=f"{marker} rule {i}",
                confirmed_at=now - timedelta(hours=i + 1),
            )
            eligible_l1_ids.add(rule.id)

        # Accepted current-truth entries — eligible L1 truth; an in-window
        # signal makes them eligible for L2's recently-surfaced path too.
        for i in range(n_accepted):
            entry = _seed_accepted_entry(
                backend,
                project_name=project_name,
                content=f"{marker} accepted current truth {i}",
                confidence=0.90 - i * 0.01,
            )
            eligible_l1_ids.add(entry.id)
            _seed_retrieval_signal(
                backend,
                project_name=project_name,
                target_id=entry.id,
                signal_type="wake_surfaced",
                recorded_at=now - timedelta(days=1),
            )

        # Pending candidates — must never surface as L1 / L2 truth. Point a
        # signal at each so L2's recently-surfaced derivation has to drop them.
        for i in range(n_pending):
            pending = _seed_pending_entry(
                backend,
                project_name=project_name,
                content=f"{marker} pending candidate {i}",
            )
            pending_ids.append(pending.id)
            _seed_retrieval_signal(
                backend,
                project_name=project_name,
                target_id=pending.id,
                signal_type="search_hit",
                recorded_at=now - timedelta(days=1),
            )

        # Historical (superseded) truth — surfaces ONLY as an L4 drilldown.
        # Point a signal at each so L2's recently-surfaced derivation also has
        # to drop them (it filters to valid_to is None).
        for i in range(n_historical):
            historical = _seed_accepted_entry(
                backend,
                project_name=project_name,
                content=f"{marker} historical decision {i}",
                confidence=0.99,
                valid_to=now - timedelta(days=i + 1),
            )
            historical_ids.append(historical.id)
            _seed_retrieval_signal(
                backend,
                project_name=project_name,
                target_id=historical.id,
                signal_type="wake_surfaced",
                recorded_at=now - timedelta(days=1),
            )

        # A recent handoff so L2 Part A is non-trivial — handoff ids are
        # legitimately referenced by L2 and are outside the forbidden set.
        _seed_handoff(
            backend,
            project_name=project_name,
            summary=f"{marker} resume work",
            last_activity=now - timedelta(hours=1),
        )

        query = _QUERY_WORD if use_query else None
        plan = run(
            assemble_context_plan(backend, project_name=project_name, query=query)
        )
    finally:
        run(backend.close())

    _assert_property7(
        plan,
        pending_ids=pending_ids,
        historical_ids=historical_ids,
        eligible_l1_ids=eligible_l1_ids,
    )


# --------------------------------------------------------------------------- #
# Populated integration case — guarantees Property 7 is exercised non-vacuously
# --------------------------------------------------------------------------- #
def test_boundary_holds_with_all_truth_layers_populated(data_dir: Path) -> None:
    """Seeding one of each truth-bearing record (accepted-current, pending,
    historical, confirmed rule) yields non-trivial L1 / L2 / L4 layers whose
    accepted-only boundary still holds (Req 3.1, 3.5, 10.1, 10.2).

    This pins the populated case so the property test above is never satisfied
    only by empty truth layers.
    """
    project_name = "accepted-only-all-layers"
    marker = "ZZFIXEDZZ"
    now = datetime.now(timezone.utc)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # L1 truth — one confirmed rule + one accepted current-truth entry.
        rule = _seed_confirmed_rule(
            backend,
            project_name=project_name,
            pattern=f"{marker} always run ruff before commit",
            confirmed_at=now - timedelta(hours=1),
        )
        accepted_entry = _seed_accepted_entry(
            backend,
            project_name=project_name,
            content=f"{marker} SQLite is the storage engine",
            confidence=0.95,
        )
        # In-window signal → accepted entry is also recently-surfaced into L2.
        _seed_retrieval_signal(
            backend,
            project_name=project_name,
            target_id=accepted_entry.id,
            signal_type="wake_surfaced",
            recorded_at=now - timedelta(days=1),
        )

        # A pending candidate, surfaced by a signal — must NOT reach L2 truth.
        pending_entry = _seed_pending_entry(
            backend,
            project_name=project_name,
            content=f"{marker} pending switch to Postgres",
        )
        _seed_retrieval_signal(
            backend,
            project_name=project_name,
            target_id=pending_entry.id,
            signal_type="search_hit",
            recorded_at=now - timedelta(days=1),
        )

        # A historical (superseded) entry — surfaces only as an L4 drilldown.
        historical_entry = _seed_accepted_entry(
            backend,
            project_name=project_name,
            content=f"{marker} we used JSON files",
            confidence=0.99,
            valid_to=now - timedelta(days=1),
        )

        # A recent handoff so L2 Part A is also non-trivial.
        _seed_handoff(
            backend,
            project_name=project_name,
            summary=f"{marker} resume wiring the boundary test",
            last_activity=now - timedelta(hours=1),
        )

        plan = run(assemble_context_plan(backend, project_name=project_name))
    finally:
        run(backend.close())

    l1 = plan.layer("L1")
    l2 = plan.layer("L2")
    l4 = plan.layer("L4")

    # Non-vacuous L1: both confirmed rule and accepted entry are present.
    l1_ids = {sid for entry in l1.entries for sid in entry.source_ids}
    assert rule.id in l1_ids
    assert accepted_entry.id in l1_ids

    # Non-vacuous L2: the accepted current entry surfaces as recently-surfaced
    # truth, while the pending candidate is excluded from that truth portion.
    recently_surfaced_ids = {
        sid
        for entry in l2.entries
        if entry.why_included == "active:recently_surfaced"
        for sid in entry.source_ids
    }
    assert accepted_entry.id in recently_surfaced_ids
    assert pending_entry.id not in recently_surfaced_ids

    # Non-vacuous L4: the historical entry surfaces exactly once, as a
    # drilldown tagged historical.
    historical_l4 = [e for e in l4.entries if historical_entry.id in e.source_ids]
    assert len(historical_l4) == 1
    assert historical_l4[0].truth_status == "historical"

    # The full accepted-only boundary holds for the populated plan.
    _assert_property7(
        plan,
        pending_ids=[pending_entry.id],
        historical_ids=[historical_entry.id],
        eligible_l1_ids={rule.id, accepted_entry.id},
    )
