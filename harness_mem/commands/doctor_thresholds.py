"""Single source of truth for v2.4.2 doctor diagnostic thresholds.

Every threshold the doctor helpers (candidate_health, signal_freshness, and
maintenance_hints) compare against lives here and ONLY here. The CLI doctor
blocks consume the helper output, so future tuning lands in one place.
"""

from __future__ import annotations

from datetime import timedelta

__all__ = [
    "STALE_THRESHOLDS",
    "HIGH_RISK_CONFIDENCE_CUTOFFS",
    "DORMANT_SIGNAL_AGE",
    "WAL_SIZE_THRESHOLD_BYTES",
]

# ---- Stale candidate thresholds (Req 2.1) ----
STALE_THRESHOLDS = {
    "rule_candidates":      timedelta(days=60),
    "memory_entries":       timedelta(days=30),
    "relation_facts":       timedelta(days=30),
    "procedural_candidates":timedelta(days=60),
    "supersede_candidates": timedelta(days=14),
}

# ---- High-risk-stale confidence cutoffs (Req 2.2) ----
HIGH_RISK_CONFIDENCE_CUTOFFS = {
    "rule_candidates":       0.5,
    "memory_entries":        0.6,
    "relation_facts":        0.6,
    "procedural_candidates": 0.5,
}

# ---- Signal freshness (Req 3.2) ----
DORMANT_SIGNAL_AGE = timedelta(days=30)

# ---- Maintenance hints (Req 5.1) ----
WAL_SIZE_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB
