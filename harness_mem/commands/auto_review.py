"""Programmatic auto-review for pending candidates.

This module turns the "AI auto-confirms low-risk, auto-rejects noise" promise
from `openspec/specs/mcp/spec.md` into a concrete, testable function. It is a
**conservative heuristic baseline**, not the final word: any future LLM-driven
auto-review can plug into the same return shape and be A/B-compared via
``tests/loop_harness/test_auto_confirm_calibration.py``.

Design contract:

- `decide_candidate(...)` is a pure function: same input -> same output, no
  storage, no LLM. Easy to unit-test, easy to evolve.
- `auto_review_candidates(...)` reads pending candidates, calls the decision
  fn, applies confirm/reject to the structured store, and returns a summary
  in the exact shape `openspec/specs/mcp/spec.md` documents
  (auto_confirmed / auto_rejected / kept_pending / needs_user_confirmation).
- We **never** auto-confirm or auto-reject silently in a way the user can't
  inspect: every applied decision is included in `applied_decisions` so the
  caller (slash /hm:distill, MCP, CLI) can show a final review summary.
- We refuse to apply decisions when the user did not opt in. Callers pass
  ``apply=True`` explicitly; the default is dry-run-style introspection so
  test scenarios and "preview what auto-review would do" flows are safe.

Heuristic rules (mirrored from the loop_harness 周明远 user card):

- ``auto_reject`` for content that is plainly noise:
  - shorter than ``MIN_CONTENT_LENGTH`` characters
  - matches one of ``NOISE_PATTERNS`` (chatty banter, status acknowledgements)
  - looks like a git commit subject line (``fix(...)``/``feat(...)``/...)
- ``auto_confirm`` only for high-recall, low-risk MemoryEntry categories
  ({decision, convention, architecture}) when content is long enough and
  confidence is at or above ``AUTO_CONFIRM_MIN_CONFIDENCE``. ``bug`` and
  ``api`` categories always defer because they are project-specific and
  silently confirming a wrong fix is more harmful than the small saving.
- For RuleCandidate, ``auto_confirm`` requires confidence ≥
  ``RULE_AUTO_CONFIRM_MIN_CONFIDENCE`` (higher floor than memory entries
  because rules are loaded into every wake-up output and have higher blast
  radius). ``auto_reject`` reuses the same noise patterns against
  ``pattern + trigger``.
- Everything else is ``defer``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from harness_mem.core.schemas import MemoryEntry, RuleCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


AutoReviewAction = Literal["auto_confirm", "auto_reject", "defer"]
CandidateKind = Literal["memory_entry", "rule_candidate"]


# --- Heuristic thresholds (module-level so tests + downstream tools can
# read or override them without monkeypatching strings inside functions).

MIN_CONTENT_LENGTH = 30
"""Below this many characters, content is too short to be useful long-term
knowledge. Most legitimate decisions/conventions clear this comfortably."""

AUTO_CONFIRM_MIN_LENGTH = 60
"""Auto-confirm requires substantially longer content than the
auto-reject floor; we want enough context to verify the entry on
glance before it lands in wake-up."""

AUTO_CONFIRM_MIN_CONFIDENCE = 0.75
"""Heuristic patterns assign 0.7 by default; only entries that exceed
that floor get auto-confirmed."""

RULE_AUTO_CONFIRM_MIN_CONFIDENCE = 0.85
"""Confirmed rules surface in every wake-up output, so the bar is
higher than for memory entries."""

AUTO_CONFIRM_CATEGORIES: frozenset[str] = frozenset(
    {"decision", "convention", "architecture"}
)
"""Memory entry categories considered low-risk enough for auto-confirm.
``bug`` and ``api`` defer to humans because incorrect facts in those
categories cause concrete code damage downstream."""

NOISE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bglad\b",
        r"\bnailed (it|that one|down)\b",
        r"\btricky one\b",
        r"\bgreat[!.\s]",
        r"\bawesome[!.\s]",
        r"\bperfect[!.\s]",
        r"\bthanks\b",
        r"\binstalled the dependencies\b",
        r"\blockfile updated\b",
    )
)
"""Substring patterns that almost always mark chatty status updates rather
than reusable knowledge. Conservative on purpose: it is fine to miss noise
and let a human reject it; it is not fine to wrongly auto-reject signal."""

GIT_COMMIT_PREFIX = re.compile(
    r"^\s*(fix|feat|refactor|chore|docs|style|test|perf|build|ci)\(",
    re.IGNORECASE,
)
"""Conventional-commit-style subject lines that occasionally leak into
distilled content (e.g. when a session pasted a commit message verbatim).
These are not reusable project knowledge."""


@dataclass(frozen=True)
class AutoReviewDecision:
    """One auto-review decision per candidate.

    ``reason`` is a short stable string suitable for logging or showing in
    a final review summary; it is not localized.
    """

    candidate_id: str
    kind: CandidateKind
    action: AutoReviewAction
    reason: str


@dataclass
class AutoReviewSummary:
    """Aggregate result returned to MCP / slash callers.

    Mirrors the shape documented in ``openspec/specs/mcp/spec.md`` so a
    slash command can render it directly without per-call mapping code.
    """

    new_candidates: int = 0
    auto_confirmed: int = 0
    auto_rejected: int = 0
    kept_pending: int = 0
    needs_user_confirmation: int = 0
    next_user_action: str = ""
    applied_decisions: list[AutoReviewDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_candidates": self.new_candidates,
            "auto_confirmed": self.auto_confirmed,
            "auto_rejected": self.auto_rejected,
            "kept_pending": self.kept_pending,
            "needs_user_confirmation": self.needs_user_confirmation,
            "next_user_action": self.next_user_action,
            "applied_decisions": [
                {
                    "candidate_id": d.candidate_id,
                    "kind": d.kind,
                    "action": d.action,
                    "reason": d.reason,
                }
                for d in self.applied_decisions
            ],
        }


def _is_noise(text: str) -> bool:
    """Return True when ``text`` matches any noise pattern."""
    if GIT_COMMIT_PREFIX.search(text):
        return True
    return any(pattern.search(text) for pattern in NOISE_PATTERNS)


def decide_memory_entry(entry: MemoryEntry) -> AutoReviewDecision:
    """Pure auto-review decision for a single MemoryEntry."""
    content = (entry.content or "").strip()
    if len(content) < MIN_CONTENT_LENGTH:
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_reject",
            f"content shorter than {MIN_CONTENT_LENGTH} chars",
        )
    if _is_noise(content):
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_reject",
            "matches noise pattern (chatty / commit-message-like)",
        )
    if (
        entry.category in AUTO_CONFIRM_CATEGORIES
        and entry.confidence >= AUTO_CONFIRM_MIN_CONFIDENCE
        and len(content) >= AUTO_CONFIRM_MIN_LENGTH
    ):
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_confirm",
            f"low-risk {entry.category} with confidence>={AUTO_CONFIRM_MIN_CONFIDENCE}",
        )
    return AutoReviewDecision(
        entry.id,
        "memory_entry",
        "defer",
        "needs human review",
    )


def decide_rule_candidate(candidate: RuleCandidate) -> AutoReviewDecision:
    """Pure auto-review decision for a single RuleCandidate."""
    combined = f"{candidate.pattern or ''} {candidate.trigger or ''}".strip()
    if len(combined) < MIN_CONTENT_LENGTH:
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_reject",
            f"pattern+trigger shorter than {MIN_CONTENT_LENGTH} chars",
        )
    if _is_noise(combined):
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_reject",
            "matches noise pattern (chatty / commit-message-like)",
        )
    if candidate.confidence >= RULE_AUTO_CONFIRM_MIN_CONFIDENCE:
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_confirm",
            f"high confidence (>={RULE_AUTO_CONFIRM_MIN_CONFIDENCE})",
        )
    return AutoReviewDecision(
        candidate.id,
        "rule_candidate",
        "defer",
        "needs human review",
    )


async def auto_review_candidates(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    apply: bool = False,
) -> AutoReviewSummary:
    """Review every pending candidate for ``project_name`` once.

    When ``apply=True``, applies confirm/reject decisions through the
    structured store mutators. When ``apply=False`` (the default) the function
    returns the same summary but leaves storage untouched — useful for "what
    would happen" previews from slash commands and from
    ``tests/loop_harness/test_auto_confirm_calibration.py``.

    Note: this function only handles ``MemoryEntry`` and ``RuleCandidate``.
    ``RelationFact`` candidates are left alone because their signal/noise
    judgment differs enough that mixing rules would dilute both. They will
    get their own decision function in a later slice.
    """
    store = backend.structured_store

    pending_entries = await store.list_memory_entries(
        project_name, limit=1000, status="pending"
    )
    pending_rules = await store.list_rule_candidates(
        project_name, status="pending"
    )

    decisions: list[AutoReviewDecision] = []
    decisions.extend(decide_memory_entry(entry) for entry in pending_entries)
    decisions.extend(decide_rule_candidate(rule) for rule in pending_rules)

    summary = AutoReviewSummary(
        new_candidates=len(pending_entries) + len(pending_rules),
    )

    for decision in decisions:
        if decision.action == "auto_confirm":
            summary.auto_confirmed += 1
            if apply:
                if decision.kind == "memory_entry":
                    await store.update_memory_entry_status(
                        decision.candidate_id, "accepted"
                    )
                else:
                    await store.update_rule_candidate_status(
                        decision.candidate_id, "accepted"
                    )
                summary.applied_decisions.append(decision)
        elif decision.action == "auto_reject":
            summary.auto_rejected += 1
            if apply:
                if decision.kind == "memory_entry":
                    await store.update_memory_entry_status(
                        decision.candidate_id, "rejected"
                    )
                else:
                    await store.update_rule_candidate_status(
                        decision.candidate_id, "rejected"
                    )
                summary.applied_decisions.append(decision)
        else:
            summary.kept_pending += 1
            summary.needs_user_confirmation += 1

    if summary.kept_pending:
        summary.next_user_action = (
            "review the deferred candidates and mention any incorrect item id"
        )
    elif summary.auto_confirmed or summary.auto_rejected:
        summary.next_user_action = (
            "review the auto-review summary and mention any incorrect item id"
        )
    else:
        summary.next_user_action = "no pending candidates"

    return summary
