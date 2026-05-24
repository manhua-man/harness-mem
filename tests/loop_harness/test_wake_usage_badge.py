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
    monkeypatch: pytest.MonkeyPatch,
):
    """A user looking at wake output should see one rule marked
    'never surfaced before' (just confirmed, not yet shown) and one
    rule marked with its previous usage count and recency."""
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

    LoopMetrics(
        name="wake_renders_usage_badges",
        values={
            "fresh_rule_marked_never_surfaced": float(
                "never surfaced before" in captured
            ),
            "veteran_rule_shows_count": float("used 4" in captured),
            "veteran_rule_shows_recency": float("h ago" in captured),
        },
    ).report()

    assert "never surfaced before" in captured, (
        "fresh rule must be marked as never surfaced; captured:\n" + captured
    )
    assert "used 4" in captured, (
        "veteran rule should expose its pre-touch usage_count; captured:\n"
        + captured
    )
    assert "2h ago" in captured or "h ago" in captured, (
        "veteran rule should show recency in human terms; captured:\n"
        + captured
    )


def test_wake_increments_after_rendering_pre_touch_value(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    """The badge shows the count *before* this wake. After this wake
    completes, the persisted count should be one higher — so the next
    wake shows the bumped value, not the stale one. This is what makes
    the badge honest across consecutive wakes."""
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

    # First wake: should display "used 2" and bump counter to 3
    exit_code = run(cmd_wake_up(project_name, no_auto_ingest=True))
    assert exit_code == 0
    first_output = capsys.readouterr().out
    assert "used 2" in first_output, (
        "first wake should show pre-touch counter (2); captured:\n"
        + first_output
    )

    # Second wake: should now display "used 3" — proves the touch ran
    exit_code = run(cmd_wake_up(project_name, no_auto_ingest=True))
    assert exit_code == 0
    second_output = capsys.readouterr().out
    assert "used 3" in second_output, (
        "second wake should show count bumped to 3; captured:\n"
        + second_output
    )
