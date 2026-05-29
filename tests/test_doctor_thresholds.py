"""Tests for :mod:`harness_mem.commands.doctor_thresholds` (Req 2.7, 6.6).

This module is the single source of truth for every v2.4.2 doctor threshold.
The tests pin the canonical values so a silent retune fails CI: changing a
threshold without updating the design + these tests is a deliberate decision,
not an accident.
"""

from __future__ import annotations

from datetime import timedelta

from harness_mem.commands import doctor_thresholds
from harness_mem.commands.doctor_thresholds import (
    CHRONIC_FAILURE_LOOKBACK,
    CHRONIC_FAILURE_THRESHOLD,
    DORMANT_SIGNAL_AGE,
    HIGH_RISK_CONFIDENCE_CUTOFFS,
    KNOWN_CHRONIC_PATTERNS,
    STALE_THRESHOLDS,
    WAL_SIZE_THRESHOLD_BYTES,
)


def test_all_seven_names_are_importable() -> None:
    expected = {
        "STALE_THRESHOLDS",
        "HIGH_RISK_CONFIDENCE_CUTOFFS",
        "DORMANT_SIGNAL_AGE",
        "CHRONIC_FAILURE_LOOKBACK",
        "CHRONIC_FAILURE_THRESHOLD",
        "KNOWN_CHRONIC_PATTERNS",
        "WAL_SIZE_THRESHOLD_BYTES",
    }
    assert set(doctor_thresholds.__all__) == expected
    for name in expected:
        assert hasattr(doctor_thresholds, name)


def test_stale_thresholds_has_exactly_five_timedelta_keys() -> None:
    assert set(STALE_THRESHOLDS.keys()) == {
        "rule_candidates",
        "memory_entries",
        "relation_facts",
        "procedural_candidates",
        "supersede_candidates",
    }
    for value in STALE_THRESHOLDS.values():
        assert isinstance(value, timedelta)


def test_stale_thresholds_canonical_day_values() -> None:
    # Pin the canonical values so a silent retune fails the test.
    assert STALE_THRESHOLDS["rule_candidates"] == timedelta(days=60)
    assert STALE_THRESHOLDS["memory_entries"] == timedelta(days=30)
    assert STALE_THRESHOLDS["relation_facts"] == timedelta(days=30)
    assert STALE_THRESHOLDS["procedural_candidates"] == timedelta(days=60)
    assert STALE_THRESHOLDS["supersede_candidates"] == timedelta(days=14)


def test_high_risk_cutoffs_has_exactly_four_float_keys() -> None:
    assert set(HIGH_RISK_CONFIDENCE_CUTOFFS.keys()) == {
        "rule_candidates",
        "memory_entries",
        "relation_facts",
        "procedural_candidates",
    }
    # supersede_candidates intentionally excluded (no comparable confidence field).
    assert "supersede_candidates" not in HIGH_RISK_CONFIDENCE_CUTOFFS
    for value in HIGH_RISK_CONFIDENCE_CUTOFFS.values():
        assert isinstance(value, float)
        assert 0.0 < value < 1.0


def test_high_risk_cutoffs_canonical_values() -> None:
    assert HIGH_RISK_CONFIDENCE_CUTOFFS["rule_candidates"] == 0.5
    assert HIGH_RISK_CONFIDENCE_CUTOFFS["memory_entries"] == 0.6
    assert HIGH_RISK_CONFIDENCE_CUTOFFS["relation_facts"] == 0.6
    assert HIGH_RISK_CONFIDENCE_CUTOFFS["procedural_candidates"] == 0.5


def test_dormant_signal_age() -> None:
    assert DORMANT_SIGNAL_AGE == timedelta(days=30)
    assert isinstance(DORMANT_SIGNAL_AGE, timedelta)


def test_chronic_failure_lookback_and_threshold() -> None:
    assert CHRONIC_FAILURE_LOOKBACK == timedelta(days=7)
    assert isinstance(CHRONIC_FAILURE_LOOKBACK, timedelta)
    assert CHRONIC_FAILURE_THRESHOLD == 3
    assert isinstance(CHRONIC_FAILURE_THRESHOLD, int)
    # bool is a subclass of int; guard against an accidental True/False.
    assert not isinstance(CHRONIC_FAILURE_THRESHOLD, bool)


def test_known_chronic_patterns_exact_order() -> None:
    assert isinstance(KNOWN_CHRONIC_PATTERNS, tuple)
    assert KNOWN_CHRONIC_PATTERNS == (
        "job_store_unavailable",
        "max_retries_exceeded",
        "ingest:",
        "prepare:",
        "distill:",
    )


def test_wal_size_threshold_bytes() -> None:
    assert WAL_SIZE_THRESHOLD_BYTES == 100 * 1024 * 1024
    assert isinstance(WAL_SIZE_THRESHOLD_BYTES, int)
