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
