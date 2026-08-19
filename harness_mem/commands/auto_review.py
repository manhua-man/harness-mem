"""Programmatic auto-review for pending candidates.

This module turns the "AI auto-confirms low-risk, auto-rejects noise" policy
into a concrete function. It is a
**conservative heuristic baseline**, not the final word: any future LLM-driven
auto-review can plug into the same return shape and be A/B-compared via
calibration fixtures.

Shared policy contract
----------------------

This module is the **single source of truth** for low-risk auto-review
judgment across every entrypoint that writes candidates:

- the ``/hm:distill`` slash command (Claude Code ``code/plugins/harness-mem/commands/hm/daily/distill.md``),
- the ``hm-distill`` skill (``tools/hm-distill/SKILL.md``), and
- the MCP ``auto_review_candidates`` tool exposed by
  ``harness_mem/mcp/tool_handlers.py::tool_auto_review_candidates``.

All three call ``auto_review_candidates(...)`` (or the pure ``decide_*``
functions) — none of them re-implement category lists, confidence floors, or
noise patterns. If a future caller needs different behaviour, extend this
module rather than copying its logic; calibration probes catch regressions in
either direction.

Design contract:

- `decide_candidate(...)` is a pure function: same input -> same output, no
  storage, no LLM. Easy to unit-test, easy to evolve.
- `auto_review_candidates(...)` reads pending candidates, calls the decision
  fn, applies confirm/reject to the structured store, and returns a summary
  shaped for MCP/slash callers
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
  - matches one of the v2.2 noise category patterns: tool failure,
    cross-project workflow leakage, generic advice, distill-process
    self-reference
  - looks like a git commit subject line (``fix(...)``/``feat(...)``/...)
- ``auto_confirm`` only for high-recall, low-risk MemoryEntry categories
  ({decision, convention, architecture}) when content is long enough,
  confidence is at or above ``AUTO_CONFIRM_MIN_CONFIDENCE``, **and** the
  entry carries an evidence id (``source != 'manual'`` and non-empty).
  ``bug`` and ``api`` categories always defer because they are
  project-specific and silently confirming a wrong fix is more harmful
  than the small saving.
- For RuleCandidate, ``auto_confirm`` requires confidence ≥
  ``RULE_AUTO_CONFIRM_MIN_CONFIDENCE`` (higher floor than memory entries
  because rules are loaded into every wake-up output and have higher blast
  radius) **and** at least one example as evidence. ``auto_reject`` reuses
  the same noise patterns against ``pattern + trigger``.
- Duplicate detection happens after individual decisions are computed: if
  two candidates in the same pass share a normalized
  ``(project, category, content[:200])`` key, the first keeps its decision
  and subsequent ones are demoted to ``auto_reject`` with reason
  ``duplicate of <first_id>``.
- Everything else is ``defer``. Defers split into two buckets:
  - **silent kept-pending**: low-risk defers that do not need to bother
    the user this turn (they only increment ``kept_pending``).
  - **needs-user-confirmation**: defers that would change long-term agent
    behaviour (rule candidates) or that fell short of auto-confirm only
    because of missing evidence (high-impact memory categories). These
    increment both ``kept_pending`` and ``needs_user_confirmation``.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from harness_mem.commands.evidence_admission import (
    ANSWER_GATE_STATUSES,
    answer_gate_status,
    apply_validation,
    evidence_summary_key,
    uses_evidence_admission,
    validate_candidate_evidence,
)
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RelationFact,
    RuleCandidate,
    StaleTruthSuggestionCandidate,
)
from harness_mem.event_log import StateEventType, append_state_event
from harness_mem.governance_status import resolve_promotion_status
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.retrieval_signals import record_retrieval_signal


AutoReviewAction = Literal["auto_confirm", "auto_reject", "defer"]
CandidateKind = Literal["memory_entry", "rule_candidate", "relation_fact"]


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

HIGH_IMPACT_MEMORY_CATEGORIES: frozenset[str] = frozenset(
    {"decision", "architecture"}
)
"""Memory entry categories whose defers should surface to the user.
These directly shape long-term project understanding; an unreviewed
defer here is more costly than a deferred bug or convention note."""

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


# --- v2.2 noise categories -------------------------------------------------
#
# Each category has a regex and a stable reason string. We keep them as
# (pattern, reason) tuples rather than a single big alternation so the
# decision functions can return a precise reason like
# "matches noise pattern (tool failure)" — the reason is the answer to the
# user's "why was this rejected?" question, so specificity matters.

TOOL_FAILURE_PATTERN = re.compile(
    r"\b("
    r"TeamCreate|SendMessage|TeamDelete|ToolSearch"
    r"|MCP\s+parameter\s+error"
    r"|agent\s+(?:was\s+|went\s+)?idle"
    r")\b",
    re.IGNORECASE,
)
"""Tool orchestration failures (multi-agent worker errors, MCP parameter
errors, idle-agent log lines). These are runtime telemetry, not project
knowledge."""

CROSS_PROJECT_WORKFLOW_PATTERN = re.compile(
    r"(?:^|\s)/plan-(?:eng|ceo|design|devex|market|cli)-review\b"
    r"|\b(?:KISS|YAGNI)\b"
    r"|don't\s+break\s+userspace"
    r"|do\s+one\s+thing\s+well",
    re.IGNORECASE,
)
"""Generic AI-workflow names (``/plan-eng-review`` etc.) and broad
software-engineering principles (KISS / YAGNI / Unix philosophy). Useful
in conversation, but they are not project-specific facts and pollute
search results when treated as memory."""

DISTILL_SELF_REFERENCE_PATTERN = re.compile(
    r"\bprepare_session_distill\b"
    r"|\bhm-distill\b"
    r"|\bdistill\s+process\b",
    re.IGNORECASE,
)
"""Entries about the distill mechanism itself (``prepare_session_distill``,
the ``hm-distill`` skill, "the distill process"). Recording the
distill workflow as project memory is a recursive trap that fills the
review queue without producing project understanding."""

GENERIC_ADVICE_PATTERN = re.compile(
    r"\bwrite\s+good\s+code\b"
    r"|\btest\s+your\s+code\b"
    r"|\buse\s+clear\s+names\b"
    r"|\bfollow\s+best\s+practices\b",
    re.IGNORECASE,
)
"""Generic advice that any project would already follow. Too broad to be
a useful project fact and crowds out the specific decisions auto-review
exists to surface."""

# Order matters only for the reason string; matches are mutually exclusive
# in practice, but if a candidate ever matches two categories we report
# the first and let a human disambiguate.
NOISE_CATEGORY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (TOOL_FAILURE_PATTERN, "tool failure"),
    (CROSS_PROJECT_WORKFLOW_PATTERN, "cross-project workflow leakage"),
    (DISTILL_SELF_REFERENCE_PATTERN, "distill-process self-reference"),
    (GENERIC_ADVICE_PATTERN, "generic advice"),
)


@dataclass(frozen=True)
class AutoReviewDecision:
    """One auto-review decision per candidate.

    ``reason`` is a short stable string suitable for logging or showing in
    a final review summary; it is not localized.

    ``evidence_id`` carries the source identifier the decision relied on
    (``MemoryEntry.source`` for entries, the first
    ``RuleCandidate.examples`` entry for rules). It is ``None`` when
    evidence is missing — that case forces a defer in the decision fn.

    ``is_high_risk`` flags defers that should surface to the user as
    "needs your confirmation" rather than be silently kept pending.
    """

    candidate_id: str
    kind: CandidateKind
    action: AutoReviewAction
    reason: str
    evidence_id: str | None = None
    is_high_risk: bool = False


@dataclass
class AutoReviewSummary:
    """Aggregate result returned to MCP / slash callers.

    Keeps a stable shape so a slash command can render it directly without
    per-call mapping code.
    """

    new_candidates: int = 0
    auto_confirmed: int = 0
    auto_provisional: int = 0
    auto_rejected: int = 0
    auto_deferred: int = 0
    kept_pending: int = 0
    needs_user_confirmation: int = 0
    repository_verified: int = 0
    user_stated: int = 0
    unverified_blocked: int = 0
    contradicted: int = 0
    legacy_or_unknown: int = 0
    answer_gate: dict[str, int] = field(
        default_factory=lambda: {status: 0 for status in ANSWER_GATE_STATUSES}
    )
    next_user_action: str = ""
    applied_decisions: list[AutoReviewDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_candidates": self.new_candidates,
            "auto_confirmed": self.auto_confirmed,
            "auto_provisional": self.auto_provisional,
            "auto_rejected": self.auto_rejected,
            "auto_deferred": self.auto_deferred,
            "kept_pending": self.kept_pending,
            "needs_user_confirmation": self.needs_user_confirmation,
            "evidence_admission": {
                "repository_verified": self.repository_verified,
                "user_stated": self.user_stated,
                "unverified_blocked": self.unverified_blocked,
                "contradicted": self.contradicted,
                "legacy_or_unknown": self.legacy_or_unknown,
            },
            "answer_gate": dict(self.answer_gate),
            "next_user_action": self.next_user_action,
            "applied_decisions": [
                {
                    "candidate_id": d.candidate_id,
                    "kind": d.kind,
                    "action": d.action,
                    "reason": d.reason,
                    "evidence_id": d.evidence_id,
                    "is_high_risk": d.is_high_risk,
                }
                for d in self.applied_decisions
            ],
        }


def _is_chatty_noise(text: str) -> bool:
    """Return True when ``text`` matches a chatty/banter pattern."""
    if GIT_COMMIT_PREFIX.search(text):
        return True
    return any(pattern.search(text) for pattern in NOISE_PATTERNS)


def _match_noise_category(text: str) -> str | None:
    """Return the v2.2 noise category name for ``text`` or None."""
    for pattern, reason in NOISE_CATEGORY_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def _assimilation_policy_decision(
    candidate: Any,
    *,
    kind: CandidateKind,
    evidence_id: str | None,
) -> AutoReviewDecision | None:
    """Enforce a provider-proposed post-verification outcome before truth writes.

    Legacy candidates have no field and continue through the historical review
    path. New autonomous rows always persist an explicit value, so a source
    being authentic can no longer, by itself, authorize a durable write.
    """

    disposition = getattr(candidate, "assimilation_disposition", None)
    if disposition is None:
        return None
    value = str(disposition).strip()
    reason = str(getattr(candidate, "assimilation_reason", "") or "").strip()
    suffix = f": {reason}" if reason else ""
    if value == "add":
        return None
    if value in {"no_write", "handoff", "reject"}:
        return AutoReviewDecision(
            candidate.id,
            kind,
            "auto_reject",
            f"assimilation disposition is {value}{suffix}",
            evidence_id=evidence_id,
            is_high_risk=value == "reject",
        )
    if value in {"defer", "conflict", "confirm", "refine", "supersede"}:
        return AutoReviewDecision(
            candidate.id,
            kind,
            "defer",
            f"assimilation disposition is {value}{suffix}",
            evidence_id=evidence_id,
            is_high_risk=value == "conflict",
        )
    return AutoReviewDecision(
        candidate.id,
        kind,
        "auto_reject",
        f"invalid assimilation disposition: {value or 'missing'}",
        evidence_id=evidence_id,
        is_high_risk=True,
    )


def decide_memory_entry(entry: MemoryEntry) -> AutoReviewDecision:
    """Pure auto-review decision for a single MemoryEntry."""
    content = (entry.content or "").strip()
    source = (entry.source or "").strip()
    evidence_id = source if source and source != "manual" else None

    if len(content) < MIN_CONTENT_LENGTH:
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_reject",
            f"content shorter than {MIN_CONTENT_LENGTH} chars",
            evidence_id=evidence_id,
        )
    noise_reason = _match_noise_category(content)
    if noise_reason is not None:
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_reject",
            f"matches noise pattern ({noise_reason})",
            evidence_id=evidence_id,
        )
    if _is_chatty_noise(content):
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_reject",
            "matches noise pattern (chatty / commit-message-like)",
            evidence_id=evidence_id,
        )
    assimilation_decision = _assimilation_policy_decision(
        entry,
        kind="memory_entry",
        evidence_id=evidence_id,
    )
    if assimilation_decision is not None:
        return assimilation_decision
    evidence_decision = _evidence_policy_decision(
        entry,
        kind="memory_entry",
        evidence_id=evidence_id,
    )
    if evidence_decision is not None:
        return evidence_decision
    if (
        entry.category in AUTO_CONFIRM_CATEGORIES
        and entry.confidence >= AUTO_CONFIRM_MIN_CONFIDENCE
        and len(content) >= AUTO_CONFIRM_MIN_LENGTH
    ):
        # Auto-confirm requires concrete evidence (source != 'manual'); an
        # entry that would otherwise auto-confirm but has no evidence id
        # is a high-risk defer because it affects long-term understanding.
        if evidence_id is None:
            return AutoReviewDecision(
                entry.id,
                "memory_entry",
                "defer",
                "auto-confirm requires evidence id (source != 'manual')",
                evidence_id=None,
                is_high_risk=True,
            )
        return AutoReviewDecision(
            entry.id,
            "memory_entry",
            "auto_confirm",
            f"low-risk {entry.category} with confidence>={AUTO_CONFIRM_MIN_CONFIDENCE}",
            evidence_id=evidence_id,
        )
    # Plain defer. Categories that materially shape project understanding
    # (decision / architecture) escalate to "needs your confirmation"; the
    # rest stay silent in the kept_pending bucket.
    is_high_risk = entry.category in HIGH_IMPACT_MEMORY_CATEGORIES
    return AutoReviewDecision(
        entry.id,
        "memory_entry",
        "defer",
        "needs human review",
        evidence_id=evidence_id,
        is_high_risk=is_high_risk,
    )


def decide_rule_candidate(candidate: RuleCandidate) -> AutoReviewDecision:
    """Pure auto-review decision for a single RuleCandidate."""
    combined = f"{candidate.pattern or ''} {candidate.trigger or ''}".strip()
    examples = list(candidate.examples or [])
    evidence_id = examples[0] if examples else None

    if len(combined) < MIN_CONTENT_LENGTH:
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_reject",
            f"pattern+trigger shorter than {MIN_CONTENT_LENGTH} chars",
            evidence_id=evidence_id,
        )
    noise_reason = _match_noise_category(combined)
    if noise_reason is not None:
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_reject",
            f"matches noise pattern ({noise_reason})",
            evidence_id=evidence_id,
        )
    if _is_chatty_noise(combined):
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_reject",
            "matches noise pattern (chatty / commit-message-like)",
            evidence_id=evidence_id,
        )
    assimilation_decision = _assimilation_policy_decision(
        candidate,
        kind="rule_candidate",
        evidence_id=evidence_id,
    )
    if assimilation_decision is not None:
        return assimilation_decision
    evidence_decision = _evidence_policy_decision(
        candidate,
        kind="rule_candidate",
        evidence_id=evidence_id,
    )
    if evidence_decision is not None:
        return evidence_decision
    if candidate.confidence >= RULE_AUTO_CONFIRM_MIN_CONFIDENCE:
        # Rule candidates always change long-term agent behaviour, so
        # missing evidence forces a high-risk defer rather than a silent
        # confirm.
        if evidence_id is None:
            return AutoReviewDecision(
                candidate.id,
                "rule_candidate",
                "defer",
                "auto-confirm requires evidence id (examples must be non-empty)",
                evidence_id=None,
                is_high_risk=True,
            )
        return AutoReviewDecision(
            candidate.id,
            "rule_candidate",
            "auto_confirm",
            f"high confidence (>={RULE_AUTO_CONFIRM_MIN_CONFIDENCE})",
            evidence_id=evidence_id,
        )
    # Every rule candidate defer is high-risk: rules surface in every
    # wake-up output, so an unreviewed pending rule will eventually
    # influence the agent.
    return AutoReviewDecision(
        candidate.id,
        "rule_candidate",
        "defer",
        "needs human review",
        evidence_id=evidence_id,
        is_high_risk=True,
    )


def decide_relation_fact(fact: RelationFact) -> AutoReviewDecision:
    """Apply the same evidence admission contract to RelationFact."""

    combined = (
        f"{fact.source_entity} {fact.relation_type} {fact.target_entity} "
        f"{fact.evidence}"
    ).strip()
    evidence_id = (fact.source or "").strip() or None
    if len(combined) < MIN_CONTENT_LENGTH:
        return AutoReviewDecision(
            fact.id,
            "relation_fact",
            "auto_reject",
            f"relation content shorter than {MIN_CONTENT_LENGTH} chars",
            evidence_id=evidence_id,
        )
    noise_reason = _match_noise_category(combined)
    if noise_reason is not None or _is_chatty_noise(combined):
        return AutoReviewDecision(
            fact.id,
            "relation_fact",
            "auto_reject",
            f"matches noise pattern ({noise_reason or 'chatty'})",
            evidence_id=evidence_id,
        )
    assimilation_decision = _assimilation_policy_decision(
        fact,
        kind="relation_fact",
        evidence_id=evidence_id,
    )
    if assimilation_decision is not None:
        return assimilation_decision
    evidence_decision = _evidence_policy_decision(
        fact,
        kind="relation_fact",
        evidence_id=evidence_id,
    )
    if evidence_decision is not None:
        return evidence_decision
    return AutoReviewDecision(
        fact.id,
        "relation_fact",
        "defer",
        "legacy relation lacks evidence admission envelope",
        evidence_id=evidence_id,
        is_high_risk=True,
    )


def _evidence_policy_decision(
    candidate: Any,
    *,
    kind: CandidateKind,
    evidence_id: str | None,
) -> AutoReviewDecision | None:
    if not uses_evidence_admission(candidate):
        return None
    basis = getattr(candidate, "evidence_basis", None)
    outcome = getattr(candidate, "verification_outcome", None)
    gate_status = answer_gate_status(candidate)
    if gate_status in {"CONTRADICTED", "STALE"}:
        return AutoReviewDecision(
            candidate.id,
            kind,
            "auto_reject",
            f"answer gate is {gate_status}: evidence conflicts with current source",
            evidence_id=evidence_id,
            is_high_risk=True,
        )
    if gate_status != "ANSWERED":
        return AutoReviewDecision(
            candidate.id,
            kind,
            "auto_reject",
            f"answer gate is {gate_status}: durable truth requires an answered evidence question",
            evidence_id=evidence_id,
            is_high_risk=kind in {"rule_candidate", "relation_fact"},
        )
    eligible = (
        basis == "repository" and outcome == "verified"
    ) or (basis == "user_statement" and outcome == "verified")
    if not eligible:
        return AutoReviewDecision(
            candidate.id,
            kind,
            "auto_reject",
            "evidence admission envelope is not eligible",
            evidence_id=evidence_id,
            is_high_risk=True,
        )
    confidence = float(getattr(candidate, "confidence", 0.0) or 0.0)
    floor = 0.5 if basis == "user_statement" else 0.7
    if kind == "rule_candidate":
        floor = 0.5 if basis == "user_statement" else 0.75
    elif kind == "relation_fact":
        floor = 0.6 if basis == "user_statement" else 0.7
    if confidence < floor:
        return AutoReviewDecision(
            candidate.id,
            kind,
            "auto_reject",
            f"verified evidence confidence below {floor}",
            evidence_id=evidence_id,
            is_high_risk=True,
        )
    return AutoReviewDecision(
        candidate.id,
        kind,
        "auto_confirm",
        f"{basis} evidence passed current-source verification",
        evidence_id=evidence_id,
        is_high_risk=(
            kind in {"rule_candidate", "relation_fact"}
            or getattr(candidate, "category", "") in {"bug", "api"}
        ),
    )


def _dedup_key(
    project_name: str, category: str, content: str
) -> tuple[str, str, str]:
    """Stable normalized key for in-pass duplicate detection."""
    return (
        project_name,
        category,
        " ".join((content or "").lower().split())[:200],
    )


async def _materialize_autonomous_rule(
    backend: LocalMemoryBackend,
    candidate: RuleCandidate,
) -> str:
    """Materialize an autonomous rule into the normal wake read model.

    The deterministic id makes a finalize replay reuse the same truth record;
    a RuleCandidate status alone is never treated as a readable rule.
    """

    confirmed_id = str(
        uuid5(NAMESPACE_URL, f"harness-mem:auto-confirmed-rule:{candidate.id}")
    )
    existing = await backend.structured_store.get_confirmed_rule(confirmed_id)
    if existing is not None:
        return existing.id
    confirmed = ConfirmedRule(
        id=confirmed_id,
        project_name=candidate.project_name,
        pattern=candidate.pattern,
        trigger=candidate.trigger,
        examples=list(candidate.examples),
        source_candidate_id=candidate.id,
        source_session_id=candidate.session_id,
        tags=list(candidate.topic_path),
        provenance={
            "distill_job_id": candidate.distill_job_id,
            "assimilation_disposition": candidate.assimilation_disposition,
        },
    )
    return await backend.structured_store.save_confirmed_rule(confirmed)


async def auto_review_candidates(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    apply: bool = False,
    candidate_ids: Collection[str] | None = None,
) -> AutoReviewSummary:
    """Review pending candidates for ``project_name`` once.

    When ``apply=True``, applies confirm/reject decisions through the
    structured store mutators. When ``apply=False`` (the default) the function
    returns the same summary but leaves storage untouched — useful for "what
    would happen" previews from slash commands and calibration runs.

    v0.9.5 applies one evidence policy across ``MemoryEntry``,
    ``RuleCandidate``, and ``RelationFact`` while preserving legacy heuristic
    behavior for pre-envelope memory/rule rows.
    """
    store = backend.structured_store

    requested_ids = {str(value) for value in candidate_ids} if candidate_ids is not None else None
    pending_entries = await store.list_memory_entries(
        project_name, limit=1000, status="pending"
    )
    pending_rules = await store.list_rule_candidates(
        project_name, status="pending"
    )
    pending_relations = await store.list_relation_facts(
        project_name,
        limit=1000,
        status="pending",
    )
    if requested_ids is not None:
        pending_entries = [entry for entry in pending_entries if entry.id in requested_ids]
        pending_rules = [rule for rule in pending_rules if rule.id in requested_ids]
        pending_relations = [
            fact for fact in pending_relations if fact.id in requested_ids
        ]

    all_candidates: list[Any] = [
        *pending_entries,
        *pending_rules,
        *pending_relations,
    ]
    for item in all_candidates:
        validation = await validate_candidate_evidence(backend, item)
        apply_validation(item, validation)
        if apply and uses_evidence_admission(item):
            if isinstance(item, MemoryEntry):
                await store.save_memory_entry(item)
            elif isinstance(item, RuleCandidate):
                await store.save_rule_candidate(item)
            else:
                await store.save_relation_fact(item)

    decisions: list[AutoReviewDecision] = []
    decisions.extend(decide_memory_entry(entry) for entry in pending_entries)
    decisions.extend(decide_rule_candidate(rule) for rule in pending_rules)
    decisions.extend(decide_relation_fact(fact) for fact in pending_relations)

    # In-pass duplicate detection. We only dedup MemoryEntry candidates
    # because that's where the spec calls out the noise category; rule
    # candidates already get a near-equivalent dedup via session_id +
    # pattern in the structured store. Iteration order matches the
    # decisions list above, so the first occurrence keeps its action.
    seen: dict[tuple[str, str, str], str] = {}
    deduped: list[AutoReviewDecision] = []
    entry_lookup = {entry.id: entry for entry in pending_entries}
    rule_lookup = {rule.id: rule for rule in pending_rules}
    relation_lookup = {fact.id: fact for fact in pending_relations}
    for decision in decisions:
        if decision.kind == "memory_entry":
            entry = entry_lookup.get(decision.candidate_id)
            if entry is not None:
                key = _dedup_key(project_name, entry.category, entry.content)
                first_id = seen.get(key)
                if first_id is None:
                    seen[key] = decision.candidate_id
                else:
                    decision = AutoReviewDecision(
                        candidate_id=decision.candidate_id,
                        kind=decision.kind,
                        action="auto_reject",
                        reason=f"duplicate of {first_id}",
                        evidence_id=decision.evidence_id,
                        is_high_risk=False,
                    )
        deduped.append(decision)

    summary = AutoReviewSummary(
        new_candidates=len(all_candidates),
    )

    for decision in deduped:
        confidence = 0.0
        if decision.kind == "memory_entry":
            entry = entry_lookup.get(decision.candidate_id)
            confidence = entry.confidence if entry is not None else 0.0
            candidate: Any | None = entry
        elif decision.kind == "rule_candidate":
            rule = rule_lookup.get(decision.candidate_id)
            confidence = rule.confidence if rule is not None else 0.0
            candidate = rule
        else:
            relation = relation_lookup.get(decision.candidate_id)
            confidence = relation.confidence if relation is not None else 0.0
            candidate = relation
        if candidate is not None:
            summary_key = evidence_summary_key(candidate)
            setattr(summary, summary_key, getattr(summary, summary_key) + 1)
            if uses_evidence_admission(candidate):
                summary.answer_gate[answer_gate_status(candidate)] += 1

        if decision.action == "auto_confirm":
            target_status = resolve_promotion_status(
                action=decision.action,
                kind=decision.kind,
                is_high_risk=decision.is_high_risk,
                confidence=confidence,
                allow_provisional=not bool(
                    getattr(candidate, "distill_job_id", None)
                ),
            )
            if target_status == "auto_confirmed":
                summary.auto_confirmed += 1
            else:
                summary.auto_provisional += 1
            if apply:
                canonical_truth_id: str | None = None
                if (
                    decision.kind == "rule_candidate"
                    and target_status == "auto_confirmed"
                    and isinstance(candidate, RuleCandidate)
                ):
                    canonical_truth_id = await _materialize_autonomous_rule(
                        backend,
                        candidate,
                    )
                if decision.kind == "memory_entry":
                    await store.update_memory_entry_status(
                        decision.candidate_id, target_status
                    )
                elif decision.kind == "rule_candidate":
                    await store.update_rule_candidate_status(
                        decision.candidate_id, target_status
                    )
                else:
                    await store.update_relation_fact_status(
                        decision.candidate_id, target_status
                    )
                summary.applied_decisions.append(decision)
                append_state_event(
                    backend.data_dir,
                    event_type=StateEventType.CANDIDATE_REVIEWED,
                    project_name=project_name,
                    target_kind=decision.kind,
                    target_id=decision.candidate_id,
                    status=target_status,
                    source_surface="auto_review_candidates",
                    actor="auto_review",
                    payload={
                        "action": decision.action,
                        "reason": decision.reason,
                        "evidence_id": decision.evidence_id,
                        "canonical_truth_id": canonical_truth_id,
                    },
                )
                await record_retrieval_signal(
                    backend,
                    project_name=project_name,
                    signal_type="confirmed",
                    target_kind=(
                        "memory_entry"
                        if decision.kind == "memory_entry"
                        else decision.kind
                    ),
                    target_id=decision.candidate_id,
                    context={
                        "reason": decision.reason,
                        "evidence_id": decision.evidence_id,
                        "governance_status": target_status,
                    },
                )
        elif decision.action == "auto_reject":
            summary.auto_rejected += 1
            if apply:
                if (
                    candidate is not None
                    and getattr(candidate, "verification_outcome", None)
                    == "contradicted"
                ):
                    # Persist the non-destructive historicalization proposal
                    # before terminally rejecting the source candidate. A
                    # crash can then retry the still-pending candidate instead
                    # of losing the only path that handles current truth.
                    await _propose_contradicted_truth(backend, candidate)
                if decision.kind == "memory_entry":
                    await store.update_memory_entry_status(
                        decision.candidate_id, "rejected"
                    )
                elif decision.kind == "rule_candidate":
                    await store.update_rule_candidate_status(
                        decision.candidate_id, "rejected"
                    )
                else:
                    await store.update_relation_fact_status(
                        decision.candidate_id, "rejected"
                    )
                summary.applied_decisions.append(decision)
                append_state_event(
                    backend.data_dir,
                    event_type=StateEventType.TRUTH_REJECTED,
                    project_name=project_name,
                    target_kind=decision.kind,
                    target_id=decision.candidate_id,
                    status="rejected",
                    source_surface="auto_review_candidates",
                    actor="auto_review",
                    payload={
                        "action": decision.action,
                        "reason": decision.reason,
                        "evidence_id": decision.evidence_id,
                    },
                )
                await record_retrieval_signal(
                    backend,
                    project_name=project_name,
                    signal_type="rejected",
                    target_kind=(
                        "memory_entry"
                        if decision.kind == "memory_entry"
                        else decision.kind
                    ),
                    target_id=decision.candidate_id,
                    context={
                        "reason": decision.reason,
                        "evidence_id": decision.evidence_id,
                    },
                )
        else:
            if apply:
                target_status = resolve_promotion_status(
                    action=decision.action,
                    kind=decision.kind,
                    is_high_risk=decision.is_high_risk,
                    confidence=confidence,
                    allow_provisional=not bool(
                        getattr(candidate, "distill_job_id", None)
                    ),
                )
                if decision.kind == "memory_entry":
                    updated = await store.update_memory_entry_status(
                        decision.candidate_id, target_status
                    )
                elif decision.kind == "rule_candidate":
                    updated = await store.update_rule_candidate_status(
                        decision.candidate_id, target_status
                    )
                else:
                    updated = await store.update_relation_fact_status(
                        decision.candidate_id, target_status
                    )
                if updated:
                    summary.auto_deferred += 1
                    summary.applied_decisions.append(decision)
                    append_state_event(
                        backend.data_dir,
                        event_type=StateEventType.CANDIDATE_REVIEWED,
                        project_name=project_name,
                        target_kind=decision.kind,
                        target_id=decision.candidate_id,
                        status=target_status,
                        source_surface="auto_review_candidates",
                        actor="auto_review",
                        payload={
                            "action": decision.action,
                            "reason": decision.reason,
                            "evidence_id": decision.evidence_id,
                        },
                    )
                else:
                    summary.kept_pending += 1
            else:
                summary.kept_pending += 1
            if decision.is_high_risk:
                summary.needs_user_confirmation += 1

    if summary.needs_user_confirmation:
        summary.next_user_action = (
            "review the deferred candidates and mention any incorrect item id"
        )
    elif summary.kept_pending:
        summary.next_user_action = (
            "no action needed; deferred items are kept silently for later review"
        )
    elif summary.auto_confirmed or summary.auto_rejected:
        summary.next_user_action = (
            "review the auto-review summary and mention any incorrect item id"
        )
    else:
        summary.next_user_action = "no pending candidates"

    return summary


async def _propose_contradicted_truth(
    backend: LocalMemoryBackend,
    candidate: Any,
) -> list[str]:
    """Create audited stale suggestions for exact matching current truth."""

    store = backend.structured_store
    targets: list[tuple[str, str]] = []
    if isinstance(candidate, MemoryEntry):
        normalized = " ".join(candidate.content.casefold().split())
        for status in ("auto_confirmed", "provisional", "user_confirmed"):
            entries = await store.list_memory_entries(
                candidate.project_name,
                limit=1000,
                status=status,
            )
            targets.extend(
                ("memory_entry", entry.id)
                for entry in entries
                if entry.id != candidate.id
                and " ".join(entry.content.casefold().split()) == normalized
            )
    elif isinstance(candidate, RuleCandidate):
        normalized_rule = (
            " ".join(candidate.pattern.casefold().split()),
            " ".join(candidate.trigger.casefold().split()),
        )
        rules = await store.list_confirmed_rules(
            candidate.project_name,
            include_history=False,
        )
        targets.extend(
            ("confirmed_rule", rule.id)
            for rule in rules
            if (
                " ".join(rule.pattern.casefold().split()),
                " ".join(rule.trigger.casefold().split()),
            )
            == normalized_rule
        )
    elif isinstance(candidate, RelationFact):
        facts = await store.list_relation_facts(
            candidate.project_name,
            limit=1000,
            include_provisional=True,
        )
        targets.extend(
            ("relation_fact", fact.id)
            for fact in facts
            if fact.id != candidate.id
            and (
                fact.source_entity.casefold(),
                fact.relation_type.casefold(),
                fact.target_entity.casefold(),
            )
            == (
                candidate.source_entity.casefold(),
                candidate.relation_type.casefold(),
                candidate.target_entity.casefold(),
            )
        )
    existing = await store.list_stale_truth_suggestion_candidates(
        candidate.project_name,
        status="pending",
    )
    existing_targets = {(item.target_kind, item.target_id) for item in existing}
    created: list[str] = []
    for target_kind, target_id in dict.fromkeys(targets):
        if (target_kind, target_id) in existing_targets:
            continue
        proposal = StaleTruthSuggestionCandidate(
            project_name=candidate.project_name,
            target_id=target_id,
            target_kind=target_kind,  # type: ignore[arg-type]
            last_surfaced_at=None,
            days_since_last_surface=0,
            evidence_signal_ids=[],
            metabolism_run_id=f"evidence-admission:{candidate.id}",
            created_at=datetime.now(timezone.utc),
            reason="contradicted_by_current_evidence",
            source_candidate_id=candidate.id,
        )
        await store.save_stale_truth_suggestion_candidate(proposal)
        created.append(proposal.id)
        append_state_event(
            backend.data_dir,
            event_type=StateEventType.CANDIDATE_CREATED,
            project_name=candidate.project_name,
            target_kind="stale_truth_suggestion_candidate",
            target_id=proposal.id,
            status="pending",
            source_surface="dream.evidence_admission",
            actor="dream",
            payload={
                "target_kind": target_kind,
                "target_id": target_id,
                "reason_code": "contradicted_by_current_evidence",
            },
        )
    return created


def explain_decision(
    summary: AutoReviewSummary, candidate_id: str
) -> dict[str, Any] | None:
    """Look up an applied decision by ``candidate_id``.

    Returns the same shape ``AutoReviewSummary.to_dict()`` emits per
    decision (``candidate_id``, ``kind``, ``action``, ``reason``,
    ``evidence_id``), or ``None`` when no matching decision exists. This
    is the helper ``/hm:distill`` quotes when the user asks "why was X
    confirmed/rejected?".
    """
    for decision in summary.applied_decisions:
        if decision.candidate_id == candidate_id:
            return {
                "candidate_id": decision.candidate_id,
                "kind": decision.kind,
                "action": decision.action,
                "reason": decision.reason,
                "evidence_id": decision.evidence_id,
            }
    return None
