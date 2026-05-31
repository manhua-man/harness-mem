"""Loop harness scenario 10 — wake exposes per-rule usage so users can see value.

Question answered: "after a confirmed rule has been around for a while,
can the user tell from wake-up output whether wake-up has actually
been showing it to anyone — or is it dead weight?"

The instrumentation has existed since v1.7.x (``usage_count`` /
``last_surfaced_at`` on ConfirmedRule), but until now the values were
locked in storage and only doctor surfaced them, and only as an
aggregate "rule quality" line. Real users sit in the wake-up output
itself and need each rule's signal next to it.

This scenario verifies two things at once:

1. The pure helper ``_format_usage_badge`` turns the (count, timestamp)
   pair into the right suffix shape, including the never-surfaced and
   recent-surface edge cases.
2. ``cmd_wake_up`` emits the **pre-touch** snapshot — the counter
   shown to the user reflects the rule's history *before* the current
   wake, so the first wake of a brand new rule reads "never surfaced
   before" rather than the misleading "used 1× just now".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands.support import set_active_project
from harness_mem.commands.wake import _format_usage_badge, cmd_wake_up
from harness_mem.core.schemas import ConfirmedRule
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


# ---------------------------------------------------------------------------
# Pure helper — fast unit-style checks for the formatting contract
# ---------------------------------------------------------------------------


def test_badge_shows_never_surfaced_when_count_is_zero():
    """A confirmed rule that no wake has ever shown gets a clear marker.

    This is the "dead weight" signal — without it, users assume every
    rule in the list is actively helping, and stale rules pile up
    unnoticed.
    """
    badge = _format_usage_badge(0, None)
    assert "never surfaced" in badge


def test_badge_shows_never_surfaced_when_timestamp_missing_even_with_count():
    """Defensive: the schema allows usage_count > 0 with no timestamp via
    legacy blobs. We treat that as 'never surfaced' rather than crash."""
    badge = _format_usage_badge(3, None)
    assert "never surfaced" in badge


def test_badge_uses_minute_resolution_for_recent_surfaces():
    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    badge = _format_usage_badge(2, now - timedelta(minutes=15), now=now)
    assert "used 2" in badge
    assert "15m ago" in badge


def test_badge_rolls_up_to_hours_then_days():
    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert "3h ago" in _format_usage_badge(1, now - timedelta(hours=3), now=now)
    assert "5d ago" in _format_usage_badge(1, now - timedelta(days=5), now=now)
    assert "2mo ago" in _format_usage_badge(1, now - timedelta(days=70), now=now)


def test_badge_handles_naive_timestamps_without_crashing():
    """Old blobs sometimes round-trip naive datetimes. We must accept them."""
    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 5, 24, 11, 0, 0)
    badge = _format_usage_badge(4, naive, now=now)
    assert "used 4" in badge
    assert "ago" in badge


# ---------------------------------------------------------------------------
# Integration — wake-up output renders the badge end-to-end
# ---------------------------------------------------------------------------


def _seed_rule(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    rule_id: str,
    pattern: str,
    trigger: str,
    usage_count: int,
    last_surfaced_at: datetime | None,
    confirmed_at: datetime,
) -> None:
    rule = ConfirmedRule(
        id=rule_id,
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        source_candidate_id=f"seed-{rule_id}",
        confirmed_at=confirmed_at,
        usage_count=usage_count,
        last_surfaced_at=last_surfaced_at,
    )
    run(backend.structured_store.save_confirmed_rule(rule))


def test_wake_renders_pre_touch_usage_badges(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """v2.5.1: confirmed rules surface in wake and each surfaced rule is touched.

    The inline per-rule usage badge (``never surfaced before`` / ``used N×, last
    …``) was an artifact of the superseded ad-hoc ``# Confirmed Rules`` wake
    block; the plan-backed L1 renderer surfaces the rule's content without that
    rendered badge. The badge-formatting contract itself is still covered by the
    pure ``_format_usage_badge`` unit tests above. What survives end-to-end here
    is the underlying behavior the badge depended on: every surfaced confirmed
    rule is *touched* (its ``usage_count`` increments), so this test now pins the
    touch side effect via the persisted record instead of the removed badge text.
    """
    project_name = "loop-harness-wake-badge"
    set_active_project(project_name)

    now = datetime.now(timezone.utc)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-fresh",
            pattern="A rule confirmed today, never surfaced.",
            trigger="When using foo",
            usage_count=0,
            last_surfaced_at=None,
            confirmed_at=now - timedelta(hours=1),
        )
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-veteran",
            pattern="A rule that wake-up has shown a few times.",
            trigger="When using bar",
            usage_count=4,
            last_surfaced_at=now - timedelta(hours=2),
            confirmed_at=now - timedelta(days=20),
        )
    finally:
        run(backend.close())

    # no_auto_ingest keeps the test hermetic
    exit_code = run(cmd_wake_up(project_name, no_auto_ingest=True))
    assert exit_code == 0
    captured = capsys.readouterr().out

    # Read the touched counters back from storage to verify the side effect.
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        fresh_after = run(backend.structured_store.get_confirmed_rule("rule-fresh"))
        veteran_after = run(
            backend.structured_store.get_confirmed_rule("rule-veteran")
        )
    finally:
        run(backend.close())
    assert fresh_after is not None and veteran_after is not None

    both_surfaced = (
        "A rule confirmed today, never surfaced." in captured
        and "A rule that wake-up has shown a few times." in captured
    )

    LoopMetrics(
        name="wake_renders_usage_badges",
        values={
            "both_rules_surfaced": float(both_surfaced),
            "fresh_rule_touched": float(fresh_after.usage_count == 1),
            "veteran_rule_touched": float(veteran_after.usage_count == 5),
        },
    ).report()

    # Both rules surface under the plan-backed L1 essential-truth section.
    assert "# Essential Truth  (L1 · confirmed current)" in captured
    assert both_surfaced, (
        "both confirmed rules must surface in wake output; captured:\n" + captured
    )
    # The wake touch fired once per surfaced rule (pre-touch 0 -> 1, 4 -> 5).
    assert fresh_after.usage_count == 1, (
        "fresh rule should be touched exactly once by wake; "
        f"got usage_count={fresh_after.usage_count}"
    )
    assert veteran_after.usage_count == 5, (
        "veteran rule should be touched exactly once by wake; "
        f"got usage_count={veteran_after.usage_count}"
    )


def test_wake_increments_after_rendering_pre_touch_value(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """The wake touch side effect bumps the persisted counter on each wake.

    v2.5.1: the rendered ``used N×`` badge is superseded by the plan-backed
    renderer, but the touch side effect it depended on still fires — each wake
    that surfaces a confirmed rule increments its ``usage_count``. This test
    preserves the original intent ("the counter advances across consecutive
    wakes") by asserting the persisted record's ``usage_count`` instead of the
    removed rendered badge text.
    """
    project_name = "loop-harness-wake-badge-increment"
    set_active_project(project_name)

    now = datetime.now(timezone.utc)
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_rule(
            backend,
            project_name,
            rule_id="rule-counter",
            pattern="A rule whose counter we expect to bump.",
            trigger="When using counter",
            usage_count=2,
            last_surfaced_at=now - timedelta(hours=1),
            confirmed_at=now - timedelta(days=5),
        )
    finally:
        run(backend.close())

    # First wake: surfaces the rule and bumps the counter 2 -> 3.
    exit_code = run(cmd_wake_up(project_name, no_auto_ingest=True))
    assert exit_code == 0
    first_output = capsys.readouterr().out
    assert "A rule whose counter we expect to bump." in first_output, (
        "first wake should surface the rule under L1; captured:\n" + first_output
    )

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        after_first = run(
            backend.structured_store.get_confirmed_rule("rule-counter")
        )
    finally:
        run(backend.close())
    assert after_first is not None
    assert after_first.usage_count == 3, (
        "first wake should bump the pre-touch counter (2) to 3; "
        f"got usage_count={after_first.usage_count}"
    )

    # Second wake: surfaces the rule again and bumps the counter 3 -> 4.
    exit_code = run(cmd_wake_up(project_name, no_auto_ingest=True))
    assert exit_code == 0
    second_output = capsys.readouterr().out
    assert "A rule whose counter we expect to bump." in second_output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        after_second = run(
            backend.structured_store.get_confirmed_rule("rule-counter")
        )
    finally:
        run(backend.close())
    assert after_second is not None
    assert after_second.usage_count == 4, (
        "second wake should bump the counter to 4, proving the touch ran; "
        f"got usage_count={after_second.usage_count}"
    )
