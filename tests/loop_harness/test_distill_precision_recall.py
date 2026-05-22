"""Loop harness scenario 1 — distill extraction precision / recall / F1.

Question answered: "given a real-style session transcript, how much of what
the heuristic distiller produces is actually long-term knowledge, and how
much is noise?"

Why this matters: every other scenario downstream (auto-confirm calibration,
wake surfacing) only matters if distill itself is producing reasonable
candidates. If distill is 50% noise, the human review queue will collapse
under its own weight regardless of how clean the rest of the loop is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run
from tests.loop_harness.conftest import LoopMetrics, precision_recall_f1
from tests.loop_harness.fixtures import LOOP_FIXTURES

pytestmark = pytest.mark.loop_harness


def test_distill_extraction_precision_recall(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root_with_fixtures: Path,
):
    """Distill the loop_harness fixture set and score against hand labels."""
    patch_cli_adapters(
        monkeypatch, claude_sessions_root=claude_sessions_root_with_fixtures
    )

    project_name = LOOP_FIXTURES[0].project_name
    # Use --auto-confirm so we can read the entries from the default
    # status='accepted' listing; this scenario scores extraction quality,
    # not the candidate-layer review path (that's scenario 2).
    assert run(cli.cmd_distill(project_name, auto_confirm=True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entries = run(
            backend.structured_store.list_memory_entries(project_name, limit=200)
        )
    finally:
        run(backend.close())

    extracted_contents = [entry.content for entry in entries]
    all_signals = [s for f in LOOP_FIXTURES for s in f.expected_signals]
    all_noise = [n for f in LOOP_FIXTURES for n in f.expected_noise]

    scores = precision_recall_f1(
        extracted=extracted_contents,
        expected_signals=all_signals,
        expected_noise=all_noise,
    )

    metrics = LoopMetrics(
        name="distill_precision_recall",
        values={
            "extracted_count": float(len(extracted_contents)),
            "signal_count": float(len(all_signals)),
            "noise_count": float(len(all_noise)),
            **scores,
        },
    )
    metrics.report()

    # Loose floors. The point of this scenario is the printed numbers, not
    # to be a tight regression gate. We only fail when something is clearly
    # broken (zero extractions, all noise, etc) so the harness stays useful
    # while heuristic patterns evolve.
    assert len(extracted_contents) > 0, "distill produced no entries at all"
    assert scores["recall"] >= 0.3, (
        f"recall fell below 0.3: distill is missing core signals "
        f"(actual={scores['recall']:.2f})"
    )
    assert scores["precision"] >= 0.5, (
        f"precision fell below 0.5: more than half of extractions hit "
        f"labeled noise (actual={scores['precision']:.2f})"
    )
