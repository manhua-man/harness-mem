"""Tests for the host-entry output shape (v2.4.1 Task 3, Req 5)."""

from __future__ import annotations

import json

import pytest

from harness_mem.commands.reflection_jobs import ReflectionResult
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult, parse_error_payload

_ALL_STATUSES = [
    "needs_distill",
    "completed",
    "retryable",
    "failed",
    "skipped_default_off",
]


def _representative(status: str) -> HostEntryResult:
    if status == "skipped_default_off":
        return HostEntryResult.skipped_default_off()
    error = {"stage": "ingest", "reason": "boom"} if status == "failed" else None
    return HostEntryResult(
        phase="ingest" if status != "completed" else "done",
        status=status,  # type: ignore[arg-type]
        next_step=f"{status}: hint",
        job_id="job-123",
        candidates_written=3 if status == "completed" else 0,
        observations_written=7 if status == "completed" else 0,
        error=error,
    )


def test_exit_codes_values() -> None:
    assert ExitCode.SUCCESS == 0
    assert ExitCode.ARG_VALIDATION_ERROR == 2
    assert ExitCode.CONFIG_LOAD_ERROR == 3
    assert ExitCode.REFLECTION_FAILED == 4


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_to_json_valid_and_status_field_matches(status: str) -> None:
    result = _representative(status)
    payload = json.loads(result.to_json())
    assert payload["status"] == status


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_next_step_first_token_rule(status: str) -> None:
    result = _representative(status)
    next_step = result.next_step
    if status == "skipped_default_off":
        assert next_step == "" or next_step.split()[0] == "skipped_default_off:"
    else:
        assert next_step.split()[0] == f"{status}:"


@pytest.mark.parametrize("status", ["needs_distill", "completed", "retryable", "failed"])
def test_canonical_hint_table_first_token(status: str) -> None:
    rr = _make_result(status, error="ingest: boom" if status == "failed" else None)
    adapted = HostEntryResult.from_reflection_result(rr)
    assert adapted.next_step.split()[0] == f"{status}:"


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_round_trip_from_dict_to_json(status: str) -> None:
    result = _representative(status)
    restored = HostEntryResult.from_dict(json.loads(result.to_json()))
    assert restored == result


def test_round_trip_with_varied_phases_and_counts() -> None:
    cases = [
        HostEntryResult("ingest", "needs_distill", "needs_distill: x", "j1", 0, 0, None),
        HostEntryResult("done", "completed", "completed: x", "j2", 5, 11, None),
        HostEntryResult("prepare", "retryable", "retryable: x", "j3", 0, 0, None),
        HostEntryResult(
            "metabolism",
            "failed",
            "failed: x",
            "j4",
            0,
            0,
            {"stage": "distill", "reason": "exploded: twice"},
        ),
        HostEntryResult(None, "skipped_default_off", "", None, 0, 0, None),
    ]
    for r in cases:
        assert HostEntryResult.from_dict(json.loads(r.to_json())) == r


@pytest.mark.parametrize("status", _ALL_STATUSES)
def test_to_json_is_single_line(status: str) -> None:
    out = _representative(status).to_json()
    assert "\n" not in out
    assert "\r" not in out


def test_to_json_keys_are_sorted() -> None:
    out = _representative("completed").to_json()
    expected_order = [
        "candidates_written",
        "error",
        "job_id",
        "next_step",
        "observations_written",
        "phase",
        "status",
    ]
    positions = [out.index(f'"{k}"') for k in expected_order]
    assert positions == sorted(positions)


def test_skipped_default_off_canonical_fields() -> None:
    r = HostEntryResult.skipped_default_off()
    assert r.phase is None
    assert r.status == "skipped_default_off"
    assert r.next_step == ""
    assert r.job_id is None
    assert r.candidates_written == 0
    assert r.observations_written == 0
    assert r.error is None


def _make_result(status: str, *, error: str | None = None) -> ReflectionResult:
    job_status = {
        "needs_distill": "needs_distill",
        "completed": "completed",
        "retryable": "retryable",
        "failed": "failed",
    }[status]
    job = ReflectionJob(
        project_name="proj",
        project_root="/tmp/proj",
        source="ide_hook",
        phase="ingest",
        status=job_status,  # type: ignore[arg-type]
        error=error,
    )
    return ReflectionResult(
        job=job,
        status=status,  # type: ignore[arg-type]
        candidates_written=3 if status == "completed" else 0,
        observations_written=7 if status == "completed" else 0,
        created=True,
    )


@pytest.mark.parametrize("status", ["needs_distill", "completed", "retryable"])
def test_from_reflection_result_non_failed(status: str) -> None:
    rr = _make_result(status)
    adapted = HostEntryResult.from_reflection_result(rr)
    assert adapted.status == status
    assert adapted.phase == rr.job.phase
    assert adapted.job_id == rr.job.id
    assert adapted.candidates_written == rr.candidates_written
    assert adapted.observations_written == rr.observations_written
    assert adapted.error is None
    assert adapted.next_step.split()[0] == f"{status}:"


def test_from_reflection_result_failed_parses_error() -> None:
    rr = _make_result("failed", error="ingest: session bundle missing field")
    adapted = HostEntryResult.from_reflection_result(rr)
    assert adapted.status == "failed"
    assert adapted.error == {
        "stage": "ingest",
        "reason": "session bundle missing field",
    }
    assert adapted.next_step.split()[0] == "failed:"


def test_from_reflection_result_failed_with_none_error() -> None:
    rr = _make_result("failed", error=None)
    adapted = HostEntryResult.from_reflection_result(rr)
    assert adapted.error == {"stage": "unknown", "reason": ""}


def test_parse_error_payload_with_separator() -> None:
    assert parse_error_payload("ingest: boom") == {
        "stage": "ingest",
        "reason": "boom",
    }


def test_parse_error_payload_splits_on_first_separator_only() -> None:
    assert parse_error_payload("distill: failed: twice") == {
        "stage": "distill",
        "reason": "failed: twice",
    }


def test_parse_error_payload_no_separator() -> None:
    assert parse_error_payload("no separator") == {
        "stage": "unknown",
        "reason": "no separator",
    }


def test_parse_error_payload_none() -> None:
    assert parse_error_payload(None) == {"stage": "unknown", "reason": ""}
