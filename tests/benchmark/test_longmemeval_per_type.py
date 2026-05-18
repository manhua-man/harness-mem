"""Tests for the LongMemEval question-type registry introduced in v1.6.0.

Focus is on the registry constant and the unknown-dimension warning path —
the full eval loop is not exercised here (that is covered by manual
benchmark runs documented in ``docs/benchmark/v160-baseline.md``).
"""
from __future__ import annotations

import warnings

import pytest

from harness_mem.tools import longmemeval

pytestmark = pytest.mark.benchmark


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_registered_question_types_match_v160_baseline() -> None:
    """The six dimensions documented in docs/benchmark/v160-baseline.md."""
    assert longmemeval.LONGMEMEVAL_QUESTION_TYPES == frozenset({
        "single-session-user",
        "single-session-preference",
        "single-session-assistant",
        "multi-session",
        "temporal-reasoning",
        "knowledge-update",
    })


def test_registry_is_immutable_frozenset() -> None:
    """Operators must not mutate the canonical set at runtime."""
    assert isinstance(longmemeval.LONGMEMEVAL_QUESTION_TYPES, frozenset)


# ---------------------------------------------------------------------------
# Validator behavior
# ---------------------------------------------------------------------------


def _make_entry(question_type: str) -> dict:
    return {
        "question_id": f"q-{question_type}",
        "question_type": question_type,
        "question": "stub",
        "answer_session_ids": [],
        "haystack_session_ids": [],
        "haystack_sessions": [],
    }


def test_validator_silent_for_known_types() -> None:
    data = [_make_entry(t) for t in longmemeval.LONGMEMEVAL_QUESTION_TYPES]
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        longmemeval._validate_question_types(data)
    assert captured == []


def test_validator_warns_once_for_unknown_type() -> None:
    data = [
        _make_entry("multi-session"),
        _make_entry("abstention-style"),  # not registered
        _make_entry("abstention-style"),  # duplicate — must NOT re-warn
    ]
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        longmemeval._validate_question_types(data)

    unknown_warnings = [
        w for w in captured
        if issubclass(w.category, UserWarning)
        and "abstention-style" in str(w.message)
    ]
    assert len(unknown_warnings) == 1, (
        "Expected exactly one warning for unknown question_type, "
        f"got: {[str(w.message) for w in captured]}"
    )


def test_validator_warns_per_distinct_unknown_type() -> None:
    data = [
        _make_entry("alpha-type"),
        _make_entry("beta-type"),
        _make_entry("multi-session"),  # known, no warning
    ]
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        longmemeval._validate_question_types(data)

    unknown_messages = {
        str(w.message) for w in captured
        if issubclass(w.category, UserWarning)
    }
    # Both unknowns warn; multi-session does not.
    assert any("alpha-type" in m for m in unknown_messages)
    assert any("beta-type" in m for m in unknown_messages)
    assert not any("multi-session" in m for m in unknown_messages)


def test_validator_does_not_raise_on_missing_question_type() -> None:
    """A malformed entry without question_type must not blow up the run."""
    data = [{"question_id": "broken"}]
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        longmemeval._validate_question_types(data)
    # No exception, no warning (None is treated as "skip")
    assert all("question_type" not in str(w.message) for w in captured)
