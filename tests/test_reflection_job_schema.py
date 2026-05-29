"""Schema tests for ``ReflectionJob`` (Req 1.8 / 1.9 / 1.10 / 1.11).

These tests are pure in-memory: they exercise ``to_dict`` / ``from_dict``,
default application, Pydantic ``Literal`` validation errors and the
forward-compatible ``extra="allow"`` behaviour. No fixtures or storage are
touched — the autouse ``data_dir`` fixture from ``tests/conftest.py`` still
reroutes any incidental writes away from ``~/.harness-mem/``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from harness_mem.core.schemas import ReflectionJob


# --- field list used by the round-trip equality assertion -----------------

_FIELDS = (
    "id",
    "project_name",
    "project_root",
    "kind",
    "phase",
    "status",
    "source",
    "input_refs",
    "output_candidate_ids",
    "error",
    "attempt_count",
    "lease_owner",
    "lease_until",
    "created_at",
    "updated_at",
    "completed_at",
)


def _fully_populated_job() -> ReflectionJob:
    """Build a ReflectionJob with every optional field set to a non-default."""
    base = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    return ReflectionJob(
        id="11111111-2222-3333-4444-555555555555",
        project_name="harness-mem",
        project_root="/tmp/harness-mem",
        kind="reflection",
        phase="prepare",
        status="processing",
        source="ide_hook",
        input_refs=["session-a", "session-b"],
        output_candidate_ids=["cand-1", "cand-2", "cand-3"],
        error="prepare: backend timed out",
        attempt_count=2,
        lease_owner="worker-7",
        lease_until=base + timedelta(seconds=300),
        created_at=base,
        updated_at=base + timedelta(seconds=10),
        completed_at=base + timedelta(seconds=42),
    )


# --- Req 1.9 / design Property 1: round-trip ------------------------------


def test_round_trip_fully_populated_preserves_every_field() -> None:
    """Validates: Requirements 1.9 (round-trip property)."""
    original = _fully_populated_job()

    restored = ReflectionJob.from_dict(original.to_dict())

    for field in _FIELDS:
        assert getattr(restored, field) == getattr(original, field), field


@pytest.mark.parametrize(
    "case",
    [
        # Minimal-but-valid: only required fields, all optionals at defaults.
        {
            "project_name": "p1",
            "project_root": "/tmp/p1",
            "source": "user",
        },
        # Mid case: a couple of optionals filled, datetimes defaulted.
        {
            "project_name": "p2",
            "project_root": "/tmp/p2",
            "source": "agent",
            "phase": "distill",
            "status": "needs_distill",
            "input_refs": ["s1"],
            "attempt_count": 1,
        },
        # Edge case: empty strings for project_name / project_root are still
        # legal Pydantic str values; round-trip should still hold.
        {
            "project_name": "",
            "project_root": "",
            "source": "scheduler",
        },
    ],
)
def test_round_trip_handrolled_cases(case: dict) -> None:
    """Validates: Requirements 1.9 across a few representative shapes."""
    original = ReflectionJob(**case)

    restored = ReflectionJob.from_dict(original.to_dict())

    for field in _FIELDS:
        assert getattr(restored, field) == getattr(original, field), field


# --- Req 1.10: default application via from_dict --------------------------


def test_from_dict_applies_defaults_for_missing_optional_fields() -> None:
    """Validates: Requirements 1.10 (defaults survive ``from_dict``)."""
    job = ReflectionJob.from_dict(
        {
            "project_name": "demo",
            "project_root": "/tmp/demo",
            "source": "user",
        }
    )

    assert job.input_refs == []
    assert job.output_candidate_ids == []
    assert job.error is None
    assert job.attempt_count == 0
    assert job.lease_owner is None
    assert job.lease_until is None
    assert job.completed_at is None
    # Field defaults set on the model itself must also survive ``from_dict``.
    assert job.kind == "reflection"
    assert job.phase == "ingest"
    assert job.status == "pending"


# --- Req 1.11: Literal validation errors ----------------------------------


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("kind", "metabolism"),  # only "reflection" is allowed in v2.4.0
        ("phase", "bogus_phase"),
        ("status", "in_progress"),
        ("source", "cron"),
    ],
)
def test_from_dict_rejects_invalid_literal_values(
    field: str, bad_value: str
) -> None:
    """Validates: Requirements 1.11 (offending field surfaced in error)."""
    payload: dict = {
        "project_name": "demo",
        "project_root": "/tmp/demo",
        "source": "user",
        field: bad_value,
    }

    with pytest.raises(ValidationError) as exc_info:
        ReflectionJob.from_dict(payload)

    assert field in str(exc_info.value)


# --- Req 1.8: datetime serialization round-trip ---------------------------


def test_to_dict_emits_iso8601_strings_for_datetime_fields() -> None:
    """Validates: Requirements 1.8 (datetime fields serialize as ISO 8601)."""
    job = _fully_populated_job()

    blob = job.to_dict()

    for field in ("created_at", "updated_at", "lease_until", "completed_at"):
        value = blob[field]
        assert isinstance(value, str), field
        # Parsing back must succeed; mirrors ``from_dict``'s own behaviour.
        datetime.fromisoformat(value)


# --- Req 1.7 / forward compatibility (extra="allow") ----------------------


def test_from_dict_preserves_unknown_keys_via_extra_allow() -> None:
    """Validates: Requirements 1.7 (unknown keys round-trip via extra=allow)."""
    job = ReflectionJob.from_dict(
        {
            "project_name": "demo",
            "project_root": "/tmp/demo",
            "source": "user",
            "future_field": "something",
        }
    )

    assert job.future_field == "something"  # type: ignore[attr-defined]
