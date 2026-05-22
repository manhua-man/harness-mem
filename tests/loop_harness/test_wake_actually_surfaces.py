"""Loop harness scenario 3 — wake-up actually surfaces confirmed rules.

Question answered: "after a user confirms a rule, does the next session's
wake-up output really contain it?"

This is the closest thing to ``周明远`` user-card P0: the whole product
pitch is "AI remembers project quirks across sessions". If wake-up does
not actually emit the confirmed rule, the pitch is broken regardless of
how clean every other layer is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands.wake import cmd_wake_up
from harness_mem.core.schemas import ConfirmedRule
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics

pytestmark = pytest.mark.loop_harness


def _seed_confirmed_rule(
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
        source_candidate_id="seed-candidate-id",
    )
    return run(backend.structured_store.save_confirmed_rule(rule))


def test_wake_emits_confirmed_rule_to_stdout(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
):
    project_name = "loop-harness-wake"
    rule_pattern = (
        "On Windows, prefer Tauri invoke over emit for any IPC payload "
        "larger than the document tree threshold (~1MB)."
    )
    rule_trigger = "Before changing Tauri IPC code on Windows"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_confirmed_rule(
            backend,
            project_name,
            trigger=rule_trigger,
            pattern=rule_pattern,
        )
    finally:
        run(backend.close())

    # Run wake-up with auto-ingest disabled so we don't hit the real
    # ~/.claude session tree from this isolated tmp_path test.
    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    captured = capsys.readouterr().out

    pattern_excerpt = "Tauri invoke over emit"
    trigger_excerpt = "Tauri IPC code on Windows"
    surfaced_pattern = pattern_excerpt in captured
    surfaced_trigger = trigger_excerpt in captured
    surface_count = int(surfaced_pattern) + int(surfaced_trigger)

    LoopMetrics(
        name="wake_actually_surfaces",
        values={
            "confirmed_rule_surfaced": float(surfaced_pattern),
            "trigger_surfaced": float(surfaced_trigger),
            "surface_count": float(surface_count),
        },
    ).report()

    assert "# Confirmed Rules" in captured, (
        "wake-up output is missing the Confirmed Rules section header"
    )
    assert surfaced_pattern, (
        f"Confirmed rule pattern not surfaced in wake-up output. "
        f"Looking for: {pattern_excerpt!r}"
    )
    assert surfaced_trigger, (
        f"Confirmed rule trigger not surfaced in wake-up output. "
        f"Looking for: {trigger_excerpt!r}"
    )
