"""Pure Doctor classification and threshold helpers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence, cast

from harness_mem.commands.doctor_thresholds import (
    HIGH_RISK_CONFIDENCE_CUTOFFS,
    STALE_THRESHOLDS,
)

logger = logging.getLogger(__name__)

STALE_MEMORY_DAYS = 90
UNUSED_RULE_DAYS = 90
_HM_CODE_PREFIX = re.compile(r"^HM-\d+$")


def _memory_quality_counts(entries: Sequence[object]) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_MEMORY_DAYS)
    stale_count = 0
    never_accessed_count = 0
    for entry in entries:
        usage_count = getattr(entry, "usage_count", 0)
        last_accessed_at = getattr(entry, "last_accessed_at", None)
        if usage_count == 0:
            never_accessed_count += 1
        reference_time = last_accessed_at or getattr(entry, "created_at", None)
        if reference_time is None:
            continue
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if reference_time < stale_cutoff:
            stale_count += 1
    return stale_count, never_accessed_count


def _confirmed_rule_quality_counts(rules: Sequence[object]) -> tuple[int, int]:
    """Mirror of ``_memory_quality_counts`` for ConfirmedRule.

    Returns ``(stale_count, never_surfaced_count)``:

    - ``never_surfaced_count``: rules with ``usage_count == 0``. These rules
      were confirmed but wake-up has never actually emitted them — the
      strongest signal that the rule is dead weight.
    - ``stale_count``: rules whose last surface (or, if never surfaced, the
      confirmation timestamp) is older than ``UNUSED_RULE_DAYS``. Captures
      "this rule was useful once but the project has moved on".
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=UNUSED_RULE_DAYS)
    stale_count = 0
    never_surfaced_count = 0
    for rule in rules:
        usage_count = getattr(rule, "usage_count", 0)
        if usage_count == 0:
            never_surfaced_count += 1
        reference_time = getattr(rule, "last_surfaced_at", None) or getattr(
            rule, "confirmed_at", None
        )
        if reference_time is None:
            continue
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if reference_time < cutoff:
            stale_count += 1
    return stale_count, never_surfaced_count


def detect_cwd_project_mismatch(
    *,
    cwd: Path,
    active_project: str | None,
    known_projects: Sequence[str],
) -> str | None:
    """Return a known-project name when cwd unambiguously points elsewhere.

    Conservative on purpose:

    - If there is no active project, no candidate, or only one known project,
      return None (nothing to disambiguate).
    - The cwd's basename must exactly match a known project name *and* differ
      from the active project. Soft matches ("ink" matching "inkpad") are
      intentionally not enough; users hit those constantly when navigating
      monorepos and we'd cry wolf.
    - Returns the suspected project name so the caller can format its own
      message and Fix: command.

    The function is pure (no I/O) so it's trivial to unit-test from a
    loop-harness scenario.
    """
    if not active_project or not known_projects:
        return None
    candidate = cwd.name
    if not candidate:
        return None
    if candidate == active_project:
        return None
    if candidate in known_projects:
        return candidate
    return None


# ---- candidate-health diagnostics --------------------------------------

# The five pending-candidate tables covered by Candidate_Health (Req 1.1).
# Order is the stable payload contract — callers branch on values, not on
# key existence (Req 1.7), but we still keep insertion order deterministic
# so JSON consumers see a fixed shape.
_CANDIDATE_TABLE_KEYS: tuple[str, ...] = (
    "rule_candidates",
    "memory_entries",
    "relation_facts",
    "procedural_candidates",
    "supersede_candidates",
)

# Over-fetch limit for the two list methods that accept a ``limit`` kwarg
# (``list_memory_entries`` and ``list_relation_facts``). Doctor is a
# diagnostic — if a review queue ever exceeds this, "go drain the queue"
# is the real story, not "doctor under-counted by N rows".
_CANDIDATE_LIST_LIMIT = 100000


def _normalize_created_at(value: datetime) -> datetime:
    """Treat a naive ``created_at`` as UTC before any age comparison.

    Mirrors the ``reference_time.tzinfo is None`` guard in
    ``_memory_quality_counts`` so candidate rows persisted by older code
    paths (which may have stored naive timestamps) compare correctly
    against ``datetime.now(timezone.utc)``.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _candidate_table_summary(
    rows: Sequence[Any],
    table: str,
    now: datetime,
) -> dict[str, Any]:
    """Build the per-table aggregate dict for one candidate table.

    Stale = ``now - created_at`` exceeds ``STALE_THRESHOLDS[table]`` (Req 1.3,
    2.1). High_Risk_Stale = stale AND ``confidence`` below the per-type cutoff
    (Req 2.2); tables without a cutoff entry (supersede_candidates) report
    ``None`` for ``high_risk_stale_count`` to keep the shape stable.
    """
    stale_threshold = STALE_THRESHOLDS[table]
    confidence_cutoff = HIGH_RISK_CONFIDENCE_CUTOFFS.get(table)

    pending_count = len(rows)
    stale_count = 0
    high_risk_stale_count = 0 if confidence_cutoff is not None else None
    for row in rows:
        created_at = _normalize_created_at(row.created_at)
        is_stale = (now - created_at) > stale_threshold
        if is_stale:
            stale_count += 1
            if confidence_cutoff is not None and row.confidence < confidence_cutoff:
                # high_risk_stale_count is an int on every table with a cutoff.
                high_risk_stale_count = cast(int, high_risk_stale_count) + 1

    oldest_pending_id: str | None = None
    oldest_pending_created_at: str | None = None
    if rows:
        oldest = min(rows, key=lambda r: _normalize_created_at(r.created_at))
        oldest_pending_id = oldest.id
        oldest_pending_created_at = _normalize_created_at(oldest.created_at).isoformat()

    return {
        "pending_count": pending_count,
        "stale_count": stale_count,
        "high_risk_stale_count": high_risk_stale_count,
        "oldest_pending_id": oldest_pending_id,
        "oldest_pending_created_at": oldest_pending_created_at,
    }


def _extract_hm_code(message: str, fallback: str) -> str:
    """Pull the ``HM-NNN`` code prefix out of a hint message.

    The existing index health checks embed a stable code at the
    front of their message (e.g. ``"HM-201: Vector index is empty"``). We
    split on the first colon and return the leading token when it matches
    the ``HM-<digits>`` shape; otherwise we fall back to the supplied
    category-derived id (some vector-index messages — model/dimension
    mismatch — have no code prefix).
    """
    head = message.split(":", 1)[0].strip()
    if _HM_CODE_PREFIX.match(head):
        return head
    return fallback
