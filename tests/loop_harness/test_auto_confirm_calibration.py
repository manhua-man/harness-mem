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

Why thresholds are loose: the heuristic auto-reviewer is **the floor**, not
the ceiling. A future LLM-driven auto-reviewer should slot into the same
function signature and beat these numbers; the harness is here to make that
comparison visible, not to gate the heuristic at a specific score.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import patch_cli_adapters, run
from tests.loop_harness.conftest import LoopMetrics
from tests.loop_harness.fixtures import LOOP_FIXTURES

pytestmark = pytest.mark.loop_harness


def _matches_any(text: str, fragments: list[str]) -> bool:
    lowered = text.lower()
    return any(f.lower() in lowered for f in fragments)


def test_auto_review_calibration_against_hand_labels(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root_with_fixtures: Path,
):
    """Distill -> auto-review (apply) -> score confirmed/rejected vs labels."""
    patch_cli_adapters(
        monkeypatch, claude_sessions_root=claude_sessions_root_with_fixtures
    )

    project_name = LOOP_FIXTURES[0].project_name
    # Default cmd_distill writes status='pending', which is exactly what
    # auto-review expects to operate on.
    assert run(cli.cmd_distill(project_name)) == 0

    all_signals = [s for f in LOOP_FIXTURES for s in f.expected_signals]
    all_noise = [n for f in LOOP_FIXTURES for n in f.expected_noise]

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # Snapshot pending candidates by id so we can score after status flips.
        pending_before = run(
            backend.structured_store.list_memory_entries(
                project_name, limit=200, status="pending"
            )
        )
        content_by_id = {entry.id: entry.content for entry in pending_before}

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
            false_positives / len(confirmed_ids)
            if confirmed_ids
            else 0.0
        )
        fn_rate = (
            false_negatives / len(rejected_ids)
            if rejected_ids
            else 0.0
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

    # Conservative floors. The heuristic baseline must not silently confirm
    # noise (FP rate stays low) or silently reject signal (FN rate stays
    # low). Both bars are looser than what an LLM-driven reviewer should
    # eventually clear.
    assert fp_rate < 0.2, (
        f"false_positive_rate too high: {fp_rate:.2f} "
        f"(auto-reviewer is confirming labeled noise)"
    )
    assert fn_rate < 0.2, (
        f"false_negative_rate too high: {fn_rate:.2f} "
        f"(auto-reviewer is rejecting labeled signal)"
    )


def test_auto_review_preview_does_not_mutate_storage(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root_with_fixtures: Path,
):
    """apply=False must leave every candidate's status untouched."""
    patch_cli_adapters(
        monkeypatch, claude_sessions_root=claude_sessions_root_with_fixtures
    )
    project_name = LOOP_FIXTURES[0].project_name
    assert run(cli.cmd_distill(project_name)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
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
        assert summary.auto_confirmed + summary.auto_rejected + summary.kept_pending == summary.new_candidates

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

    The fixture-driven calibration test above runs through the heuristic
    distiller, which currently emits every entry at the default confidence
    floor (0.7) — below the auto-confirm threshold (0.75). That is fine and
    expected: heuristic distill is intentionally below the auto-confirm bar
    so a human or LLM-driven distill must clear it.

    This test directly seeds candidates that exercise both ends of the
    decision tree so the auto-review mutator path itself is covered.
    """
    from harness_mem.core.schemas import MemoryEntry, RuleCandidate

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
        assert summary.auto_rejected == 1   # noise_entry
        assert summary.kept_pending == 1    # defer_entry
        assert summary.new_candidates == 4
    finally:
        run(backend.close())
