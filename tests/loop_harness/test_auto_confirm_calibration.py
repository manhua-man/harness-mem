"""Loop harness scenario 2 — auto-confirm calibration (xfail placeholder).

Question this scenario will eventually answer: "of the candidates the AI
auto-confirms as low-risk, how many are actually noise (false positives),
and of the candidates it auto-rejects, how many are actually signal
(false negatives)?"

Why this is xfail right now:

The "AI auto-confirms low-risk candidates" capability currently lives only
in the ``/hm:distill`` slash prompt. There is no programmatic entry point
in ``harness_mem.commands.distill`` (or anywhere else) that takes a list
of pending candidates and returns an auto-confirm / auto-reject decision
per candidate. ``cmd_distill --auto-confirm`` flips *all* pending entries
to accepted indiscriminately — that's the legacy dogfood path, not an
auto-review.

Concretely, this scenario should not move out of xfail until
``commands/distill.py`` (or a sibling module) exposes something like:

    async def auto_review_candidates(
        backend: MemoryBackend, project_name: str
    ) -> list[AutoReviewDecision]: ...

with each ``AutoReviewDecision`` carrying ``{candidate_id, action, reason}``
where ``action in {"confirm", "reject", "defer"}``.

Once that exists, this scenario should:

1. Distill the loop fixtures (status=pending).
2. Call ``auto_review_candidates`` and apply its decisions.
3. Score the resulting (confirmed, rejected) split against the hand-labeled
   signal vs noise tags in ``LOOP_FIXTURES``.
4. Report ``false_positive_rate`` and ``false_negative_rate``.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.loop_harness]


@pytest.mark.xfail(
    reason=(
        "Auto-review capability lives only in the /hm:distill slash prompt; "
        "no programmatic entry point yet. See module docstring for the API "
        "this scenario expects to exist before flipping out of xfail."
    ),
    strict=True,
)
def test_auto_confirm_calibration_against_hand_labels():
    # When the auto-review API lands, replace this with the real flow:
    #
    #   patch_cli_adapters(...)
    #   run(cli.cmd_distill("inkpad"))                    # -> status=pending
    #   decisions = run(auto_review_candidates(backend, "inkpad"))
    #   for decision in decisions:
    #       run(apply_auto_review(backend, decision))
    #
    #   confirmed = run(backend.structured_store.list_memory_entries(
    #       "inkpad", status="accepted"))
    #   rejected = run(backend.structured_store.list_memory_entries(
    #       "inkpad", status="rejected"))
    #
    #   fp = number of confirmed entries containing labeled noise
    #   fn = number of rejected entries containing labeled signal
    #   LoopMetrics(name="auto_confirm_calibration", values={
    #       "false_positive_rate": fp / max(1, len(confirmed)),
    #       "false_negative_rate": fn / max(1, len(rejected)),
    #   }).report()
    #
    #   assert false_positive_rate < 0.2
    #   assert false_negative_rate < 0.2
    raise AssertionError(
        "auto_review_candidates() does not exist yet — see module docstring"
    )
