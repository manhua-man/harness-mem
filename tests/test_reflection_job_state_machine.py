"""State machine tests for ``ReflectionJob`` (Req 3.1-3.11 / Property 2 / 7).

These tests exhaustively cover the transition table declared by
``ALLOWED_TRANSITIONS`` plus the defensive guards on top of it. They are
pure in-memory: no fixtures, no storage, just calls into
``harness_mem.core.schemas`` helpers.
"""

from __future__ import annotations

import pytest

from harness_mem.core.schemas import (
    ALLOWED_TRANSITIONS,
    new_pending_job,
    validate_transition,
)


# Full status set per Req 1.5 / design.md state machine section. Kept as a
# tuple here so parametrize ids stay deterministic.
_ALL_STATUSES = (
    "pending",
    "processing",
    "completed",
    "failed",
    "retryable",
    "needs_distill",
)

_TERMINAL_STATUSES = ("completed", "failed")


# --- enumerate (current, target) pairs ------------------------------------


def _allowed_pairs() -> list[tuple[str, str]]:
    """Every ``(current, target)`` pair declared as legal."""
    return [
        (current, target)
        for current, targets in ALLOWED_TRANSITIONS.items()
        for target in targets
    ]


def _disallowed_pairs() -> list[tuple[str, str]]:
    """Every ``(current, target)`` pair NOT declared as legal.

    ``current`` is restricted to the keys in ``ALLOWED_TRANSITIONS`` (the
    six known statuses). ``target`` ranges over the full status set so
    we also exercise terminal-state outbound rejection.
    """
    return [
        (current, target)
        for current in ALLOWED_TRANSITIONS
        for target in _ALL_STATUSES
        if target not in ALLOWED_TRANSITIONS[current]
    ]


# --- Req 3.1-3.8 / design Property 2: allowed transitions accepted --------


@pytest.mark.parametrize("current,target", _allowed_pairs())
def test_allowed_transitions_do_not_raise(current: str, target: str) -> None:
    """Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8."""
    # ``validate_transition`` returns ``None`` on success; we just want it
    # to not raise. Any exception here would surface as a test failure.
    validate_transition(current, target)


# --- Req 3.9 / design Property 2: invalid transitions rejected ------------


@pytest.mark.parametrize("current,target", _disallowed_pairs())
def test_disallowed_transitions_raise_with_diagnostic_message(
    current: str, target: str
) -> None:
    """Validates: Requirements 3.9 (current + target surfaced in message)."""
    with pytest.raises(ValueError) as exc_info:
        validate_transition(current, target)

    message = str(exc_info.value)
    assert repr(current) in message, message
    assert repr(target) in message, message


# --- Req 3.10 / design Property 7: terminal states reject everything ------


@pytest.mark.parametrize("current", _TERMINAL_STATUSES)
@pytest.mark.parametrize("target", _ALL_STATUSES)
def test_terminal_states_reject_every_outbound_transition(
    current: str, target: str
) -> None:
    """Validates: Requirements 3.10 / Property 7 (terminal immutability)."""
    with pytest.raises(ValueError):
        validate_transition(current, target)


def test_terminal_state_allowed_sets_are_empty() -> None:
    """Sanity check that ``ALLOWED_TRANSITIONS`` declares terminals correctly."""
    for terminal in _TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[terminal] == set()


# --- Req 3.11: factory produces a pending job -----------------------------


def test_new_pending_job_initial_status_is_pending() -> None:
    """Validates: Requirements 3.11 (initial status MUST be pending)."""
    job = new_pending_job(
        project_name="demo",
        project_root="/tmp/demo",
        source="user",
    )

    assert job.status == "pending"


def test_new_pending_job_passes_required_fields_through() -> None:
    """Validates: Requirements 3.11 (required fields wired correctly)."""
    job = new_pending_job(
        project_name="demo",
        project_root="/tmp/demo",
        source="user",
    )

    assert job.project_name == "demo"
    assert job.project_root == "/tmp/demo"
    assert job.source == "user"
    # Defaults the factory inherits from the schema:
    assert job.kind == "reflection"
    assert job.phase == "ingest"
    assert job.input_refs == []


def test_new_pending_job_optional_phase_kwarg_flows_through() -> None:
    """Validates: Requirements 3.11 (optional ``phase`` honoured)."""
    job = new_pending_job(
        project_name="demo",
        project_root="/tmp/demo",
        source="agent",
        phase="prepare",
    )

    assert job.status == "pending"
    assert job.phase == "prepare"


def test_new_pending_job_optional_input_refs_kwarg_flows_through() -> None:
    """Validates: Requirements 3.11 (optional ``input_refs`` honoured)."""
    refs = ["session-a", "session-b"]

    job = new_pending_job(
        project_name="demo",
        project_root="/tmp/demo",
        source="ide_hook",
        input_refs=refs,
    )

    assert job.status == "pending"
    assert job.input_refs == refs
    # Factory must take its own copy so callers can mutate the original
    # list afterwards without affecting the persisted job.
    refs.append("session-c")
    assert job.input_refs == ["session-a", "session-b"]


# --- Defensive guard: unknown source status -------------------------------


def test_validate_transition_rejects_unknown_current_status() -> None:
    """Out-of-set source status surfaces a useful diagnostic.

    The schema only allows the six known statuses, but ``validate_transition``
    is a plain helper that may receive arbitrary strings (e.g. from a stale
    persisted blob). Defensive rejection avoids silently treating an unknown
    state as "no allowed transitions".
    """
    with pytest.raises(ValueError) as exc_info:
        validate_transition("bogus", "processing")

    message = str(exc_info.value)
    assert "bogus" in message, message
