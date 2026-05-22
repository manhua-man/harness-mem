"""Loop harness scenario 5 — confirmed rules track when they actually fire.

Question answered: "after a user confirms a rule, can the system tell us
whether the rule has ever been surfaced in a wake-up output, and how many
times?"

Why this matters: the v1.5 product narrative declares rules as the things
"that influence how the agent approaches work in a new session". Without a
counter, that claim is unverifiable: a rule confirmed three months ago
that wake-up never actually emitted is indistinguishable from one that
fires every day. This scenario nails down the **fact** part of the
counter (it increments on each wake-up surface). The downstream policy
("doctor flags rules unused for 90 days") is intentionally not in this
scenario yet — that's a product decision deserving its own slice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.commands.wake import cmd_wake_up
from harness_mem.core.schemas import ConfirmedRule
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def _seed_rule(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    trigger: str,
    pattern: str,
) -> str:
    rule = ConfirmedRule(
        project_name=project_name,
        trigger=trigger,
        pattern=pattern,
        source_candidate_id="seed-candidate",
    )
    return run(backend.structured_store.save_confirmed_rule(rule))


def test_wake_increments_confirmed_rule_usage_count(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    project_name = "loop-harness-rule-counter"
    rule_pattern = (
        "On Windows, prefer Tauri invoke over emit for any IPC payload "
        "larger than the document tree threshold (~1MB)."
    )
    rule_trigger = "Before changing Tauri IPC code on Windows"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        rule_id = _seed_rule(
            backend,
            project_name,
            trigger=rule_trigger,
            pattern=rule_pattern,
        )

        before = run(backend.structured_store.get_confirmed_rule(rule_id))
        assert before is not None
        assert before.usage_count == 0
        assert before.last_surfaced_at is None
    finally:
        run(backend.close())

    # Drive wake-up three times, capturing stdout each round to keep the
    # printed wake context out of pytest's failure tail.
    for _ in range(3):
        assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
        capsys.readouterr()

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        after = run(backend.structured_store.get_confirmed_rule(rule_id))
        assert after is not None

        LoopMetrics(
            name="rule_surface_count",
            values={
                "wake_count": 3.0,
                "usage_count": float(after.usage_count),
                "has_last_surfaced_at": float(after.last_surfaced_at is not None),
            },
        ).report()

        assert after.usage_count == 3, (
            f"expected usage_count to match wake invocations; "
            f"got {after.usage_count}"
        )
        assert after.last_surfaced_at is not None
        # last_surfaced_at lives in UTC; sanity-check it sits in the past.
        assert after.last_surfaced_at <= datetime.now(timezone.utc)
    finally:
        run(backend.close())


def test_legacy_confirmed_rule_blob_loads_with_zero_usage(
    data_dir: Path,
):
    """v1.7-era ConfirmedRule blobs without usage_count must still load."""
    project_name = "loop-harness-rule-legacy"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        rule_id = _seed_rule(
            backend,
            project_name,
            trigger="trigger",
            pattern="pattern body that is long enough.",
        )

        # Simulate an upgrade from a pre-counter installation by stripping
        # the new fields off the on-disk blob.
        store = backend.structured_store
        # Use the structured store's blob path helper if it's exposed;
        # otherwise reconstruct the path the same way LocalStructuredStore
        # does internally. We import the concrete class to access the
        # internal helper without duplicating path layout knowledge.
        from harness_mem.storage.local_structured_store import LocalStructuredStore

        assert isinstance(store, LocalStructuredStore)
        blob_path = store._blob_path("confirmed_rules", rule_id)
        import json

        data = json.loads(blob_path.read_text())
        data.pop("usage_count", None)
        data.pop("last_surfaced_at", None)
        blob_path.write_text(json.dumps(data, indent=2, default=str))

        loaded = run(store.get_confirmed_rule(rule_id))
        assert loaded is not None
        assert loaded.usage_count == 0
        assert loaded.last_surfaced_at is None
    finally:
        run(backend.close())
