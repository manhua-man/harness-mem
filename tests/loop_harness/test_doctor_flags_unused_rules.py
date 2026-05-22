"""Loop harness scenario 7 — doctor flags rules that wake-up never surfaces.

Question answered: "after a user confirms a rule and time passes, does
``harness-mem doctor`` actually surface that the rule is dead weight?"

This closes the loop scenario 5 opened. Scenario 5 nailed down the
**fact** layer: ConfirmedRule now carries usage_count + last_surfaced_at
that wake-up increments. Scenario 7 nails down the **policy** layer:
those numbers actually drive a visible doctor signal so the user has
something to act on.

Scope (deliberately narrow): doctor *flags* unused rules with HM-401 and
points at ``harness-mem rules`` for review. doctor does **not** delete
anything — deletion is always a deliberate human action via
reject/supersede. The retention window default (90 days) is encoded as
``UNUSED_RULE_DAYS`` in ``harness_mem/commands/doctor.py`` and is a
straightforward edit when product feedback says it should change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.doctor import UNUSED_RULE_DAYS, cmd_doctor
from harness_mem.commands.support import set_active_project
from harness_mem.core.schemas import ConfirmedRule
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def _seed_rule(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    rule_id: str,
    pattern: str,
    confirmed_at: datetime,
    usage_count: int,
    last_surfaced_at: datetime | None,
) -> str:
    rule = ConfirmedRule(
        id=rule_id,
        project_name=project_name,
        trigger="When editing related code",
        pattern=pattern,
        source_candidate_id=f"seed-{rule_id}",
        confirmed_at=confirmed_at,
        usage_count=usage_count,
        last_surfaced_at=last_surfaced_at,
    )
    return run(backend.structured_store.save_confirmed_rule(rule))


def test_doctor_flags_never_surfaced_rule(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """A confirmed rule with usage_count=0 must trigger HM-401 in doctor output."""
    project_name = "loop-harness-doctor-unused"
    set_active_project(project_name)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Confirmed yesterday, never surfaced. The "yesterday" timestamp
        # rules out the stale-by-age path so we can isolate the
        # never-surfaced signal.
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-never-used",
            pattern="A rule confirmed yesterday but wake-up never showed it.",
            confirmed_at=datetime.now(timezone.utc) - timedelta(days=1),
            usage_count=0,
            last_surfaced_at=None,
        )
    finally:
        run(backend.close())

    assert run(cmd_doctor(project_name)) == 0
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_unused_rules_never_surfaced",
        values={
            "hm_401_emitted": float("HM-401" in captured),
            "rule_quality_line_present": float("Rule quality:" in captured),
        },
    ).report()

    assert "Rule quality:" in captured, (
        "doctor should print Rule quality line whenever any confirmed rules exist"
    )
    assert "1 never surfaced" in captured, (
        f"expected '1 never surfaced' in Rule quality line; captured: {captured!r}"
    )
    assert "HM-401" in captured, (
        "doctor should emit HM-401 when any confirmed rule has usage_count == 0"
    )


def test_doctor_flags_stale_rule(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """A rule whose last_surfaced_at is older than UNUSED_RULE_DAYS triggers HM-401."""
    project_name = "loop-harness-doctor-stale"
    set_active_project(project_name)

    cutoff_age = UNUSED_RULE_DAYS + 7  # comfortably past the cutoff
    long_ago = datetime.now(timezone.utc) - timedelta(days=cutoff_age)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-stale",
            pattern="A rule that was useful long ago but the project has moved on.",
            confirmed_at=long_ago,
            usage_count=3,
            last_surfaced_at=long_ago,
        )
    finally:
        run(backend.close())

    assert run(cmd_doctor(project_name)) == 0
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_unused_rules_stale",
        values={
            "hm_401_emitted": float("HM-401" in captured),
            "stale_count_visible": float(f">{UNUSED_RULE_DAYS}d" in captured),
        },
    ).report()

    assert "1 stale" in captured, (
        f"expected stale count in Rule quality line; captured: {captured!r}"
    )
    assert "HM-401" in captured


def test_doctor_silent_when_rules_are_healthy(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """Recently confirmed and surfaced rules must NOT trigger HM-401.

    Guards against false positives: a project where rules are doing
    their job should not get nagged.
    """
    project_name = "loop-harness-doctor-healthy"
    set_active_project(project_name)

    now = datetime.now(timezone.utc)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-healthy",
            pattern="A rule that wake-up surfaced this morning.",
            confirmed_at=now - timedelta(days=10),
            usage_count=5,
            last_surfaced_at=now - timedelta(hours=2),
        )
    finally:
        run(backend.close())

    assert run(cmd_doctor(project_name)) == 0
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_unused_rules_healthy",
        values={
            "hm_401_emitted": float("HM-401" in captured),
        },
    ).report()

    assert "HM-401" not in captured, (
        f"doctor wrongly flagged a healthy rule as unused; captured:\n{captured}"
    )
    # Rule quality line should still print, just without the HM-401 follow-up.
    assert "0 stale" in captured and "0 never surfaced" in captured


def test_doctor_reports_relation_graph_count_without_nagging(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """v1.7.2 graph traversal: doctor surfaces the count as info, not warning.

    The relation graph is rarely populated by heuristic distill (see
    scenario 6). doctor must therefore *show* the count so users aren't
    confused when ``trace_relations`` returns empty, but it must *not*
    emit a warning code or fix command — there's nothing actionable a
    user can do without an LLM-driven distiller or manual entity work.
    """
    project_name = "loop-harness-doctor-relation-info"
    set_active_project(project_name)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Seed a rule so the project has something to inspect; we only
        # care about the relation graph line here.
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-side",
            pattern="A rule that exists so doctor has a project to walk.",
            confirmed_at=datetime.now(timezone.utc) - timedelta(days=1),
            usage_count=1,
            last_surfaced_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    finally:
        run(backend.close())

    assert run(cmd_doctor(project_name)) == 0
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_relation_graph_info",
        values={
            "info_line_emitted": float("Relation graph:" in captured),
            "no_warning_code": float("HM-4" not in captured.replace("HM-401", "")),
        },
    ).report()

    assert "Relation graph: 0 facts" in captured, (
        f"doctor must report relation graph count for v1.7.2 transparency; "
        f"captured:\n{captured}"
    )
    # The relation-graph line itself must be info-only — no inline warning
    # code, no Fix: command attached to it. Other unrelated checks
    # (HM-201 vector index, HM-401 unused rules, etc.) may still emit
    # their own Fix: commands later in the output, and that's fine.
    relation_line_start = captured.find("Relation graph:")
    next_section_start = captured.find("\n", relation_line_start) + 1
    relation_line = captured[relation_line_start:next_section_start]
    assert "Fix:" not in relation_line, (
        f"Relation graph line itself must be info-only; got: {relation_line!r}"
    )
    assert "HM-" not in relation_line, (
        f"Relation graph line must not carry an HM-xxx code; got: {relation_line!r}"
    )


def test_doctor_flags_unused_in_mixed_population(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """Mixed real-world projects: some healthy rules, some dead weight.

    Real projects don't look like the isolation scenarios above — they have
    a mix of rules that get surfaced often and rules that quietly rotted.
    HM-401 must still fire and the counts must be honest: 1 stale + 1
    never-surfaced, not collapsed into a single number, and not silenced
    by the presence of healthy rules.
    """
    project_name = "loop-harness-doctor-mixed"
    set_active_project(project_name)

    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(days=UNUSED_RULE_DAYS + 14)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Healthy rule: surfaced this morning, recently confirmed.
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-healthy",
            pattern="A rule wake-up just surfaced.",
            confirmed_at=now - timedelta(days=20),
            usage_count=8,
            last_surfaced_at=now - timedelta(hours=3),
        )
        # Stale rule: surfaced once, but last surface predates the cutoff.
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-stale",
            pattern="A rule that worked once but the project moved on.",
            confirmed_at=long_ago,
            usage_count=2,
            last_surfaced_at=long_ago,
        )
        # Never-surfaced rule: confirmed yesterday, no surface ever.
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-never",
            pattern="A rule confirmed in haste, never invoked.",
            confirmed_at=now - timedelta(days=1),
            usage_count=0,
            last_surfaced_at=None,
        )
    finally:
        run(backend.close())

    assert run(cmd_doctor(project_name)) == 0
    captured = capsys.readouterr().out

    LoopMetrics(
        name="doctor_unused_rules_mixed",
        values={
            "hm_401_emitted": float("HM-401" in captured),
            "stale_count_visible": float("1 stale" in captured),
            "never_surfaced_count_visible": float("1 never surfaced" in captured),
            "rule_quality_line_present": float("Rule quality:" in captured),
        },
    ).report()

    assert "Rule quality:" in captured, (
        "doctor must print Rule quality line when any confirmed rules exist"
    )
    assert "1 stale" in captured, (
        f"doctor must report 1 stale rule despite the presence of healthy "
        f"and never-surfaced rules; captured:\n{captured}"
    )
    assert "1 never surfaced" in captured, (
        f"doctor must report 1 never-surfaced rule despite the presence of "
        f"healthy and stale rules; captured:\n{captured}"
    )
    assert "HM-401" in captured, (
        "doctor must emit HM-401 when any rule (stale OR never-surfaced) "
        "qualifies, even if other rules are healthy"
    )
