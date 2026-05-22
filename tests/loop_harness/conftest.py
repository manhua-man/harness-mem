"""Shared fixtures and metric helpers for the loop_harness scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

from tests.helpers import write_claude_session
from tests.loop_harness.fixtures import LOOP_FIXTURES, LoopFixture


@dataclass(frozen=True)
class LoopMetrics:
    """A small container so scenarios can pretty-print their numbers.

    Each scenario calls ``LoopMetrics.report()`` from inside its test so the
    actual values surface in pytest stdout. We deliberately do not write to
    disk yet — the cross-version artifact pipeline can layer on later once
    the harness has real consumers.
    """

    name: str
    values: dict[str, float]

    def report(self) -> None:
        body = json.dumps(self.values, indent=2, sort_keys=True)
        print(f"\n[loop_harness:{self.name}] {body}")


def precision_recall_f1(
    *,
    extracted: Iterable[str],
    expected_signals: Iterable[str],
    expected_noise: Iterable[str],
) -> dict[str, float]:
    """Compute precision / recall / F1 against substring labels.

    A piece of extracted text is considered:
    - a true positive when it contains any of ``expected_signals``;
    - a false positive when it contains any of ``expected_noise``;
    - silently ignored otherwise (we don't have a label, so we don't score).
    """
    extracted = list(extracted)
    signals = list(expected_signals)
    noise = list(expected_noise)

    true_positives = sum(
        1 for text in extracted if any(s.lower() in text.lower() for s in signals)
    )
    false_positives = sum(
        1 for text in extracted if any(n.lower() in text.lower() for n in noise)
    )
    # A signal counts as recalled when *some* extracted text contains it.
    recalled_signals = sum(
        1
        for s in signals
        if any(s.lower() in text.lower() for text in extracted)
    )

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    recall = recalled_signals / len(signals) if signals else 0.0
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


@pytest.fixture
def claude_sessions_root_with_fixtures(tmp_path: Path) -> Path:
    """Materialize every LOOP_FIXTURES sample as a real Claude jsonl session.

    Returns the sessions_root that ClaudeCodeAdapter expects (one level above
    the per-project directory). Tests typically pair this with
    ``patch_cli_adapters(monkeypatch, claude_sessions_root=...)``.
    """
    sessions_root = tmp_path / "claude-projects"
    for fixture in LOOP_FIXTURES:
        write_claude_session(
            sessions_root,
            fixture.project_name,
            fixture.session_id,
            fixture.user_text,
            fixture.assistant_texts,
        )
    return sessions_root


@pytest.fixture
def loop_fixtures() -> list[LoopFixture]:
    return list(LOOP_FIXTURES)
