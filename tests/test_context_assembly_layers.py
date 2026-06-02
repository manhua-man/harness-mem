"""Integration tests for the v2.5.0 Plan_Assembler layers (L0..L4).

Each test seeds a ``tmp_path``-isolated backend (via the ``data_dir``
fixture) and drives :func:`assemble_context_plan` end-to-end, asserting that
the layer under test is populated from the *same* read surfaces ``wake`` and
search already use — with correct ``source_ids``, ``why_included`` reasons,
and Truncation_Accounting.

This module grows one section per layer. Each layer's tests live under their
own ``# --- Layer Lx ... ---`` banner and reuse the module-level seed helpers
so later slices (tasks 5.2 / 6.2 / 7.2) can append their tests cleanly without
reworking the file.

All tests create the backend against the ``data_dir`` fixture (never the real
``~/.harness-mem/``, rule P1 数据路径隔离) and close it in a ``finally`` block
(rule P1 异步资源清理).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.context_assembly import DEFAULT_BUDGETS, assemble_context_plan
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


# --------------------------------------------------------------------------- #
# Shared seed helpers
# --------------------------------------------------------------------------- #
def _seed_profile(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    description: str = "",
    stacks: list[str] | None = None,
) -> ProjectProfile:
    """Save a ProjectProfile via the same store surface L0 reads.

    Returns the saved profile so callers can assert against its ``id``
    (which the store round-trips through ``to_dict`` / ``from_dict``).
    """
    profile = ProjectProfile(
        project_name=project_name,
        description=description,
        stacks=stacks or [],
    )
    run(LocalProjectProfileStore(backend.data_dir).save(profile))
    return profile


def _seed_confirmed_rule(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    pattern: str,
    confirmed_at: datetime,
    valid_to: datetime | None = None,
) -> ConfirmedRule:
    """Save a ConfirmedRule via the same store surface L1 reads.

    ``confirmed_at`` is set explicitly so callers can assert the
    ``confirmed_at`` descending ordering L1 applies. ``valid_to`` is left
    ``None`` for current rules and set for historical ones.
    """
    rule = ConfirmedRule(
        project_name=project_name,
        pattern=pattern,
        trigger="when relevant",
        source_candidate_id="seed-candidate",
        confirmed_at=confirmed_at,
        valid_to=valid_to,
    )
    run(backend.structured_store.save_confirmed_rule(rule))
    return rule


def _seed_memory_entry(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    content: str,
    confidence: float,
    status: str = "accepted",
    valid_to: datetime | None = None,
) -> MemoryEntry:
    """Save a MemoryEntry via the same store surface L1 reads.

    Callers vary ``confidence`` to assert the confidence-descending ordering,
    ``status`` to seed pending records, and ``valid_to`` to seed historical
    (superseded) records — both of which L1 must exclude.
    """
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content,
        confidence=confidence,
        status=status,
        source="manual",
        valid_to=valid_to,
    )
    run(backend.structured_store.save_memory_entry(entry))
    return entry


def _seed_handoff(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    summary: str,
    last_activity: datetime,
) -> TaskHandoff:
    """Save a TaskHandoff via the same store surface L2's Part A reads.

    ``last_activity`` is set explicitly because ``get_latest_handoffs`` orders
    by it descending; callers assert the handoff id appears in L2.
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
    """Save a RetrievalSignal pointing at a memory entry (L2's Part B input).

    ``signal_type`` is one of ``wake_surfaced`` / ``search_hit`` and
    ``recorded_at`` is kept inside the recently-surfaced window so the signal
    is in-scope for L2's read-only derivation.
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


def _count_retrieval_signals(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
) -> int:
    """Count all retrieval signals for a project across every signal type.

    L2 asserts this count is unchanged across assembly (Req 4.5, no new
    ``RetrievalSignal`` row).
    """
    return len(run(backend.structured_store.query_retrieval_signals(project_name)))


# --------------------------------------------------------------------------- #
# Layer L0 — profile / identity (Req 2.2, 2.5)
# --------------------------------------------------------------------------- #
def test_l0_populated_from_seeded_profile(data_dir: Path) -> None:
    """L0 carries one identity entry sourced from the seeded profile (Req 2.2)."""
    project_name = "l0-with-profile"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        profile = _seed_profile(
            backend,
            project_name=project_name,
            description="Local-first AI memory runtime",
            stacks=["python", "sqlite"],
        )

        plan = run(assemble_context_plan(backend, project_name=project_name))
    finally:
        run(backend.close())

    l0 = plan.layer("L0")

    # Exactly one always-on identity entry, traceable to the profile id.
    assert len(l0.entries) == 1
    entry = l0.entries[0]
    assert entry.layer == "L0"
    assert entry.source_ids == [profile.id]
    assert entry.why_included == "identity:active_project"
    # Summary carries the profile's identity fields (Req 2.2).
    assert project_name in entry.summary

    # Budget + accounting reflect a single available candidate (Req 2.4, 6.x).
    assert l0.budget.max_entries == DEFAULT_BUDGETS["L0"]
    assert l0.truncation.available == 1
    assert l0.truncation.included == 1
    assert l0.truncation.dropped == 0


def test_l0_empty_when_no_profile(data_dir: Path) -> None:
    """No profile → empty L0 with available=0 and no exception (Req 2.5)."""
    project_name = "l0-no-profile"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        plan = run(assemble_context_plan(backend, project_name=project_name))
    finally:
        run(backend.close())

    l0 = plan.layer("L0")
    assert l0.entries == []
    assert l0.truncation.available == 0
    assert l0.truncation.included == 0
    assert l0.truncation.dropped == 0


# --------------------------------------------------------------------------- #
# Layer L1 — essential truth (Req 3.2, 3.5)
# --------------------------------------------------------------------------- #
def test_l1_confirmed_rules_then_entries_ordering(data_dir: Path) -> None:
    """L1 orders confirmed rules (by confirmed_at desc) before accepted
    current-truth entries (by confidence desc), with correct source_ids /
    why_included, and never surfaces pending or historical records (Req 3.2, 3.5).
    """
    project_name = "l1-essential-truth"
    now = datetime.now(timezone.utc)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Two confirmed rules with distinct confirmed_at — newer must rank first.
        rule_older = _seed_confirmed_rule(
            backend,
            project_name=project_name,
            pattern="always run ruff before commit",
            confirmed_at=now - timedelta(days=2),
        )
        rule_newer = _seed_confirmed_rule(
            backend,
            project_name=project_name,
            pattern="tests must use the tmp_path fixture",
            confirmed_at=now - timedelta(hours=1),
        )

        # Two accepted current-truth entries with distinct confidence —
        # higher confidence must rank first.
        entry_lower_conf = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="SQLite is the storage engine",
            confidence=0.70,
        )
        entry_higher_conf = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="MCP stdout must stay clean",
            confidence=0.95,
        )

        # A pending candidate and a historical (valid_to set) entry — both must
        # be excluded from L1 regardless of their confidence.
        pending_entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="pending: maybe switch to Postgres",
            confidence=0.99,
            status="pending",
        )
        historical_entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="historical: we used JSON files",
            confidence=0.99,
            valid_to=now - timedelta(days=1),
        )

        plan = run(assemble_context_plan(backend, project_name=project_name))
    finally:
        run(backend.close())

    l1 = plan.layer("L1")

    # Confirmed rules first (newer before older), then entries by confidence desc.
    assert [entry.source_ids[0] for entry in l1.entries] == [
        rule_newer.id,
        rule_older.id,
        entry_higher_conf.id,
        entry_lower_conf.id,
    ]

    # why_included distinguishes the two truth sources (Req 3.2).
    assert [entry.why_included for entry in l1.entries] == [
        "essential:confirmed_rule",
        "essential:confirmed_rule",
        "essential:high_confidence_truth",
        "essential:high_confidence_truth",
    ]

    # Pending and historical records NEVER appear in L1 (Req 3.5).
    surfaced_ids = {entry.source_ids[0] for entry in l1.entries}
    assert pending_entry.id not in surfaced_ids
    assert historical_entry.id not in surfaced_ids

    # Budget + accounting reflect the four eligible candidates (Req 3.4, 6.x).
    assert l1.budget.max_entries == DEFAULT_BUDGETS["L1"]
    assert l1.truncation.available == 4
    assert l1.truncation.included == 4
    assert l1.truncation.dropped == 0


# --------------------------------------------------------------------------- #
# Layer L2 — active task (Req 4.1, 4.3, 4.5)
# --------------------------------------------------------------------------- #
def test_l2_handoffs_and_recently_surfaced_entries(data_dir: Path) -> None:
    """L2 surfaces recent handoffs and recently-surfaced accepted current
    truth, and derives the latter read-only — emitting no new RetrievalSignal.

    Part A: a seeded handoff appears as ``active:recent_handoff`` with
    ``source_ids`` = handoff id. Part B: accepted current-truth entries that
    have an in-window ``wake_surfaced`` / ``search_hit`` signal appear as
    ``active:recently_surfaced`` with ``source_ids`` = entry id. The total
    retrieval-signal count is identical before and after assembly (Req 4.5).
    """
    project_name = "l2-active-task"
    now = datetime.now(timezone.utc)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Part A — one recent handoff.
        handoff = _seed_handoff(
            backend,
            project_name=project_name,
            summary="resume wiring the L2 builder",
            last_activity=now - timedelta(hours=1),
        )

        # Part B — accepted current-truth entries, each pointed at by an
        # in-window retrieval signal so L2 re-surfaces them read-only.
        wake_entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="wake surfaced: SQLite FTS5 powers search",
            confidence=0.90,
        )
        _seed_retrieval_signal(
            backend,
            project_name=project_name,
            target_id=wake_entry.id,
            signal_type="wake_surfaced",
            recorded_at=now - timedelta(days=1),
        )
        search_entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="search hit: MCP stdout must stay clean",
            confidence=0.85,
        )
        _seed_retrieval_signal(
            backend,
            project_name=project_name,
            target_id=search_entry.id,
            signal_type="search_hit",
            recorded_at=now - timedelta(days=2),
        )

        # Count signals BEFORE assembly (Req 4.5).
        signals_before = _count_retrieval_signals(backend, project_name=project_name)

        plan = run(assemble_context_plan(backend, project_name=project_name))

        # Count signals AFTER — the L2 derivation must add none (Req 4.5).
        signals_after = _count_retrieval_signals(backend, project_name=project_name)
    finally:
        run(backend.close())

    assert signals_after == signals_before

    l2 = plan.layer("L2")

    # A recent-handoff entry traceable to the handoff id (Req 4.2, 4.3).
    handoff_entries = [e for e in l2.entries if e.why_included == "active:recent_handoff"]
    assert len(handoff_entries) == 1
    assert handoff_entries[0].source_ids == [handoff.id]
    assert handoff_entries[0].layer == "L2"

    # Recently-surfaced entries traceable to their entry ids (Req 4.1, 4.3).
    surfaced_ids = {
        e.source_ids[0]
        for e in l2.entries
        if e.why_included == "active:recently_surfaced"
    }
    assert wake_entry.id in surfaced_ids
    assert search_entry.id in surfaced_ids

    # Budget reflects the L2 default (Req 4.4).
    assert l2.budget.max_entries == DEFAULT_BUDGETS["L2"]


# --------------------------------------------------------------------------- #
# Layer L3 — topic recall (Req 5.1, 5.3, 5.5)
# --------------------------------------------------------------------------- #
# Distinctive step content seeded on the skill below. L3 surfaces skills as
# compact id/title/reason hints only, so this token must NEVER appear in any
# L3 entry's fields (Req 5.3).
_SECRET_STEP_CONTENT = "SECRET_STEP_CONTENT_must_not_leak"


def _seed_skill(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    name: str,
    activation_condition: str,
    steps: list[str],
    scope: str = "project",
) -> Skill:
    """Save a Skill via the same store surface L3's ``search_skills`` reads.

    ``name`` / ``activation_condition`` carry the query term so the skill
    matches; ``steps`` carry the distinctive secret step content L3 must never
    embed (it surfaces id/title/reason hints only, Req 5.3).
    """
    skill = Skill(
        project_name=project_name,
        name=name,
        activation_condition=activation_condition,
        steps=steps,
        termination_condition="done",
        scope=scope,  # type: ignore[arg-type]
    )
    run(backend.structured_store.save_skill(skill))
    return skill


def test_l3_populated_from_search_surfaces_with_skill_hints_only(data_dir: Path) -> None:
    """L3 surfaces matched entries and skills for a query, with skills carried
    as id/title/reason hints only — never their step content (Req 5.1, 5.3).
    """
    project_name = "l3-topic-recall"
    query = "telemetry"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # An accepted current-truth entry whose content matches the query.
        entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="The telemetry pipeline streams events to the dashboard",
            confidence=0.90,
        )
        # A skill whose name / activation_condition match the query, with
        # distinctive secret step content L3 must not embed.
        skill = _seed_skill(
            backend,
            project_name=project_name,
            name="Telemetry validation loop",
            activation_condition="when telemetry needs validation",
            steps=[f"{_SECRET_STEP_CONTENT} run the secret procedure"],
        )

        plan = run(
            assemble_context_plan(backend, project_name=project_name, query=query)
        )
    finally:
        run(backend.close())

    l3 = plan.layer("L3")

    # The matched memory entry surfaces as a search_memory hit, traceable to
    # its entry id (Req 5.1, 5.2).
    search_entries = [
        e for e in l3.entries if e.why_included == "topic_recall:search_memory"
    ]
    assert [e.source_ids[0] for e in search_entries] == [entry.id]

    # The matched skill surfaces as a compact hint, traceable to its skill id,
    # carrying the skill name but NOT the procedural step content (Req 5.3).
    skill_entries = [e for e in l3.entries if e.why_included == "topic_recall:skill"]
    assert len(skill_entries) == 1
    skill_entry = skill_entries[0]
    assert skill_entry.source_ids == [skill.id]
    assert skill.name in skill_entry.summary
    assert _SECRET_STEP_CONTENT not in skill_entry.summary

    # No L3 entry's summary leaks the secret step content anywhere (Req 5.3).
    assert all(_SECRET_STEP_CONTENT not in e.summary for e in l3.entries)

    # Budget reflects the L3 default (Req 5.4).
    assert l3.budget.max_entries == DEFAULT_BUDGETS["L3"]


def test_l3_default_query_excludes_shared_scope_skill(data_dir: Path) -> None:
    """v2.7.0 scope model: default query recall remains project-scoped."""
    project_name = "l3-scope-recall"
    query = "release"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        project_skill = _seed_skill(
            backend,
            project_name=project_name,
            name="Project release validation",
            activation_condition="when release validation is needed",
            steps=["run project release checks"],
        )
        shared_skill = _seed_skill(
            backend,
            project_name=project_name,
            name="Shared release validation",
            activation_condition="when release validation is needed",
            steps=["run shared release checks"],
            scope="global",
        )

        plan = run(
            assemble_context_plan(backend, project_name=project_name, query=query)
        )
    finally:
        run(backend.close())

    skill_entries = [e for e in plan.layer("L3").entries if e.why_included == "topic_recall:skill"]
    skill_source_ids = [entry.source_ids[0] for entry in skill_entries]
    assert project_skill.id in skill_source_ids
    assert shared_skill.id not in skill_source_ids


def test_l3_empty_when_query_off(data_dir: Path) -> None:
    """``query=None`` and ``query=""`` short-circuit L3 to an empty layer with
    ``available=0`` — no search surface is invoked even though matching data
    exists (Req 5.5).
    """
    project_name = "l3-query-off"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Seed data that WOULD match ``query`` if any search ran. If L3 short-
        # circuits correctly, none of this surfaces (available stays 0).
        _seed_memory_entry(
            backend,
            project_name=project_name,
            content="The telemetry pipeline streams events to the dashboard",
            confidence=0.90,
        )
        _seed_skill(
            backend,
            project_name=project_name,
            name="Telemetry validation loop",
            activation_condition="when telemetry needs validation",
            steps=[f"{_SECRET_STEP_CONTENT} run the secret procedure"],
        )

        plan_none = run(
            assemble_context_plan(backend, project_name=project_name, query=None)
        )
        plan_blank = run(
            assemble_context_plan(backend, project_name=project_name, query="")
        )
    finally:
        run(backend.close())

    # query=None → empty L3, no search performed (Req 5.5).
    l3_none = plan_none.layer("L3")
    assert l3_none.entries == []
    assert l3_none.truncation.available == 0
    assert l3_none.truncation.included == 0
    assert l3_none.truncation.dropped == 0

    # query="" → identical short-circuit (Req 5.5).
    l3_blank = plan_blank.layer("L3")
    assert l3_blank.entries == []
    assert l3_blank.truncation.available == 0
