"""Loop harness scenario 2 — auto-review calibration against hand labels.

Question answered: "of the candidates the auto-reviewer auto-confirms as
low-risk, how many are actually labeled noise (false positives)? And of
the candidates it auto-rejects, how many are actually labeled signal
(false negatives)?"

Scoring model:

- A candidate is "labeled noise" when its content matches any
  ``expected_noise`` substring across the loop_harness fixtures.
- A candidate is "labeled signal" when its content matches any
  ``expected_signals`` substring **and** does not match any noise label.
- ``false_positive_rate`` = labeled-noise auto-confirmed / total auto-confirmed
- ``false_negative_rate`` = labeled-signal auto-rejected / total auto-rejected
- Candidates the auto-reviewer defers are not scored — that's the human
  review queue working as intended.

v2.0 note: this scenario used to feed candidates into the auto-reviewer
through ``cmd_distill`` (heuristic regex distill). v2.0 removed that
code path because heuristic distill produced low-confidence pseudo-AI
candidates that violated the "AI memory runtime" promise. The calibration
now seeds candidates **directly** to test the auto-review decision logic
in isolation, mirroring the kind of input an LLM-driven distiller (the
session-distill skill, or any future agent that calls
``suggest_memory_entry`` / ``suggest_rule``) would produce.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.core.schemas import MemoryEntry, RuleCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics
from tests.loop_harness.fixtures import LOOP_FIXTURES

pytestmark = pytest.mark.loop_harness


def _matches_any(text: str, fragments: list[str]) -> bool:
    lowered = text.lower()
    return any(f.lower() in lowered for f in fragments)


def _seed_signal_and_noise_entries(
    backend: LocalMemoryBackend, project_name: str
) -> dict[str, str]:
    """Materialize one MemoryEntry per fixture signal and noise fragment.

    Returns ``{entry_id: content}`` so callers can score auto-review
    decisions against ``LOOP_FIXTURES`` hand labels without running the
    real distill pipeline (which is LLM-driven post-v2.0).
    """
    content_by_id: dict[str, str] = {}
    for fixture in LOOP_FIXTURES:
        # Signal entries: long, decision-flavored, high confidence.
        # An LLM-driven distiller producing one entry per fixture signal
        # would land roughly in this shape.
        for signal in fixture.expected_signals:
            entry = MemoryEntry(
                id=str(uuid4()),
                project_name=project_name,
                category="decision",
                content=(
                    f"Signal carrier for the {signal} fixture: "
                    f"the project established a clear convention around "
                    f"{signal} and we recorded it as a long-term decision."
                ),
                confidence=0.85,
                status="pending",
                source=f"agent:{fixture.fixture_id}",
            )
            run(backend.structured_store.save_memory_entry(entry))
            content_by_id[entry.id] = entry.content

        # Noise entries: short, chatty, but high confidence — exactly the
        # kind of "AI got too excited" output that auto-review should
        # catch. We deliberately bump confidence above the heuristic floor
        # so the auto-confirm path could fire if the noise pattern check
        # were missing.
        for noise in fixture.expected_noise:
            entry = MemoryEntry(
                id=str(uuid4()),
                project_name=project_name,
                category="decision",
                content=noise,
                confidence=0.85,
                status="pending",
                source=f"agent:{fixture.fixture_id}",
            )
            run(backend.structured_store.save_memory_entry(entry))
            content_by_id[entry.id] = entry.content
    return content_by_id


def test_auto_review_calibration_against_hand_labels(data_dir: Path):
    """Score auto-review decisions on directly-seeded labeled candidates."""
    project_name = "loop-harness-auto-review-calibration"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        content_by_id = _seed_signal_and_noise_entries(backend, project_name)

        all_signals = [s for f in LOOP_FIXTURES for s in f.expected_signals]
        all_noise = [n for f in LOOP_FIXTURES for n in f.expected_noise]

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )

        confirmed_ids = {
            d.candidate_id
            for d in summary.applied_decisions
            if d.action == "auto_confirm" and d.kind == "memory_entry"
        }
        rejected_ids = {
            d.candidate_id
            for d in summary.applied_decisions
            if d.action == "auto_reject" and d.kind == "memory_entry"
        }

        false_positives = sum(
            1
            for cid in confirmed_ids
            if _matches_any(content_by_id.get(cid, ""), all_noise)
        )
        false_negatives = sum(
            1
            for cid in rejected_ids
            if _matches_any(content_by_id.get(cid, ""), all_signals)
            and not _matches_any(content_by_id.get(cid, ""), all_noise)
        )

        fp_rate = (
            false_positives / len(confirmed_ids) if confirmed_ids else 0.0
        )
        fn_rate = (
            false_negatives / len(rejected_ids) if rejected_ids else 0.0
        )
    finally:
        run(backend.close())

    LoopMetrics(
        name="auto_confirm_calibration",
        values={
            "new_candidates": float(summary.new_candidates),
            "auto_confirmed": float(summary.auto_confirmed),
            "auto_rejected": float(summary.auto_rejected),
            "kept_pending": float(summary.kept_pending),
            "false_positive_rate": fp_rate,
            "false_negative_rate": fn_rate,
        },
    ).report()

    assert summary.auto_confirmed > 0, (
        "auto-review never confirmed any signal — calibration is too strict"
    )
    assert summary.auto_rejected > 0, (
        "auto-review never rejected any noise — calibration is too loose"
    )
    assert fp_rate < 0.2, (
        f"false_positive_rate too high: {fp_rate:.2f} "
        f"(auto-reviewer is confirming labeled noise)"
    )
    assert fn_rate < 0.2, (
        f"false_negative_rate too high: {fn_rate:.2f} "
        f"(auto-reviewer is rejecting labeled signal)"
    )


def test_auto_review_preview_does_not_mutate_storage(data_dir: Path):
    """apply=False must leave every candidate's status untouched."""
    project_name = "loop-harness-auto-review-preview"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_signal_and_noise_entries(backend, project_name)

        before = run(
            backend.structured_store.list_memory_entries(
                project_name, limit=200, status="pending"
            )
        )
        before_ids = {entry.id for entry in before}

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=False)
        )
        # Preview reports decisions but applies nothing, so there should be
        # no entries in applied_decisions either.
        assert summary.applied_decisions == []
        assert (
            summary.auto_confirmed
            + summary.auto_rejected
            + summary.kept_pending
            == summary.new_candidates
        )

        after = run(
            backend.structured_store.list_memory_entries(
                project_name, limit=200, status="pending"
            )
        )
        after_ids = {entry.id for entry in after}
        assert before_ids == after_ids, (
            "preview mode mutated structured store status"
        )
    finally:
        run(backend.close())


def test_auto_review_rejects_noise_and_confirms_high_quality(data_dir: Path):
    """Direct exercise of both apply paths with hand-crafted candidates.

    Mirrors the calibration test above but with explicitly-shaped inputs
    that pin down each branch of the decision tree (auto_confirm vs
    auto_reject vs defer) regardless of what the LOOP_FIXTURES happen to
    cover this version.
    """
    project_name = "loop-harness-auto-review-direct"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store

        # Auto-confirm target: long enough, low-risk category, high confidence.
        confirm_entry = MemoryEntry(
            project_name=project_name,
            category="decision",
            content=(
                "We decided to use invoke for all data-shaped IPC and "
                "reserve emit only for fire-and-forget UI events because "
                "Tauri v1 emit deadlocked on Windows for payloads >1MB."
            ),
            confidence=0.85,
            status="pending",
            source="manual",
        )
        # Auto-reject target: matches a noise pattern.
        noise_entry = MemoryEntry(
            project_name=project_name,
            category="decision",
            content="Glad we got that one nailed down — that was a tricky one.",
            confidence=0.85,
            status="pending",
            source="manual",
        )
        # Defer target: bug category is a hard defer in the heuristic.
        defer_entry = MemoryEntry(
            project_name=project_name,
            category="bug",
            content=(
                "The root cause was a missing JWT exp validation; the fix "
                "was to check the exp claim before any authenticated call."
            ),
            confidence=0.95,
            status="pending",
            source="manual",
        )
        # Auto-confirm rule candidate: high confidence + no noise.
        confirm_rule = RuleCandidate(
            project_name=project_name,
            session_id="manual-session",
            pattern="Use parameterized queries for every dynamic SQL fragment.",
            trigger="Before composing SQL strings with user input",
            confidence=0.9,
            status="pending",
        )

        run(store.save_memory_entry(confirm_entry))
        run(store.save_memory_entry(noise_entry))
        run(store.save_memory_entry(defer_entry))
        run(store.save_rule_candidate(confirm_rule))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )

        confirmed = run(
            store.list_memory_entries(project_name, limit=10, status="accepted")
        )
        rejected = run(
            store.list_memory_entries(project_name, limit=10, status="rejected")
        )
        still_pending = run(
            store.list_memory_entries(project_name, limit=10, status="pending")
        )

        assert {e.id for e in confirmed} == {confirm_entry.id}
        assert {e.id for e in rejected} == {noise_entry.id}
        assert {e.id for e in still_pending} == {defer_entry.id}

        # Rule candidate should be auto-confirmed.
        accepted_rules = run(
            store.list_rule_candidates(project_name, status="accepted")
        )
        assert {r.id for r in accepted_rules} == {confirm_rule.id}

        # Summary numbers add up.
        assert summary.auto_confirmed == 2  # confirm_entry + confirm_rule
        assert summary.auto_rejected == 1  # noise_entry
        assert summary.kept_pending == 1  # defer_entry
        assert summary.new_candidates == 4
    finally:
        run(backend.close())
