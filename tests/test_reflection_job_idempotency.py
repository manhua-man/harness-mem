"""Idempotency-key tests for reflection jobs (Req 5.1 / design Property 4).

Pure in-memory tests; no fixtures or storage involved. The autouse
``data_dir`` fixture from ``tests/conftest.py`` is harmless here.
"""

from __future__ import annotations

import pytest

from harness_mem.commands.reflection_jobs import compute_idempotency_key


# --- Req 5.1 / Property 4: determinism ------------------------------------


def test_same_inputs_yield_same_key() -> None:
    """Validates: Requirements 5.1 (deterministic across calls)."""
    args = ("demo", "user", "ingest", ["s1", "s2"], "trig-1")

    assert compute_idempotency_key(*args) == compute_idempotency_key(*args)


def test_key_is_32_hex_characters() -> None:
    """Validates: design.md (32-hex truncation for SQLite indexing)."""
    key = compute_idempotency_key("demo", "user", "ingest", ["s1"], None)

    assert len(key) == 32
    int(key, 16)  # must parse as hex; raises ValueError otherwise


# --- Req 5.1 / Property 4: ordering independence --------------------------


@pytest.mark.parametrize(
    "session_ids",
    [
        ["s1", "s2", "s3"],
        ["s2", "s3", "s1"],
        ["s3", "s1", "s2"],
        ["s3", "s2", "s1"],
    ],
)
def test_session_id_order_does_not_change_key(session_ids: list[str]) -> None:
    """Validates: Requirements 5.1 (sorted before hashing)."""
    canonical = compute_idempotency_key(
        "demo", "user", "ingest", ["s1", "s2", "s3"], "trig"
    )

    assert (
        compute_idempotency_key("demo", "user", "ingest", session_ids, "trig")
        == canonical
    )


def test_empty_session_ids_yields_stable_key() -> None:
    """Validates: Requirements 5.1 (empty input is a normal case)."""
    a = compute_idempotency_key("demo", "user", "ingest", [], None)
    b = compute_idempotency_key("demo", "user", "ingest", [], None)

    assert a == b
    assert len(a) == 32


# --- Req 5.1: trigger_id None == "" ---------------------------------------


def test_none_and_empty_trigger_id_are_equivalent() -> None:
    """Validates: Requirements 5.1 (None normalised to empty string).

    Callers without an explicit trigger get a single canonical key;
    they shouldn't accidentally fork a duplicate by switching None ↔ ''.
    """
    none_key = compute_idempotency_key("demo", "user", "ingest", ["s1"], None)
    empty_key = compute_idempotency_key("demo", "user", "ingest", ["s1"], "")

    assert none_key == empty_key


# --- Req 5.1: different inputs produce different keys ---------------------


@pytest.mark.parametrize(
    "field,a_value,b_value",
    [
        ("project_name", "demo", "other-project"),
        ("source", "user", "agent"),
        ("phase", "ingest", "prepare"),
        ("trigger_id", "trig-a", "trig-b"),
    ],
)
def test_changing_any_input_dimension_changes_the_key(
    field: str, a_value: str, b_value: str
) -> None:
    """Validates: Requirements 5.1 (every dimension is part of the digest)."""
    base = {
        "project_name": "demo",
        "source": "user",
        "phase": "ingest",
        "session_ids": ["s1", "s2"],
        "trigger_id": "trig-a",
    }
    a = dict(base)
    a[field] = a_value
    b = dict(base)
    b[field] = b_value

    a_key = compute_idempotency_key(**a)  # type: ignore[arg-type]
    b_key = compute_idempotency_key(**b)  # type: ignore[arg-type]

    assert a_key != b_key, f"key did not change when {field} did"


def test_changing_session_ids_changes_the_key() -> None:
    """Validates: Requirements 5.1 (session set is part of the digest)."""
    a = compute_idempotency_key("demo", "user", "ingest", ["s1", "s2"], "trig")
    b = compute_idempotency_key("demo", "user", "ingest", ["s1", "s2", "s3"], "trig")

    assert a != b
