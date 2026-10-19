"""Saved source states and unfinished actions have separate completion effects."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from harness_mem.commands.distill_result import (
    current_distill_result,
    distill_display_review,
    distill_unfinished_work,
)
from harness_mem.core.schemas.session_distill import (
    RetainedStateRef,
    SessionDistillJob,
    SessionSemanticReview,
)


STATE = "The venue choice has not been settled."
ACTION = "Ask the venue manager for available dates."
STATEMENT = "The choir's rehearsal venue remains explicitly undecided."


def _job(*, status="completed", disposition="add", refs=True):
    return SessionDistillJob(
        id="job", idempotency_key="job-key", project_name="choir",
        project_root="", client="codex", session_id="session",
        source_id="source", source_revision="sha256:fixture", status=status,
        completion_disposition="promoted",
        semantic_review={
            "session_summary": "Retained the choir's explicitly unsettled venue choice.",
            "final_user_request": "Remember the current venue status.",
            "final_outcome": "Saved the venue status.", "last_turn_status": "answered",
            "contradictions": [], "unfinished_work": [STATE],
            "evidence_status": "answered", "promotion_decision": "promote",
            **({"retained_state_refs": [{"candidate_id": "state", "unfinished_work_item": STATE}]}
               if refs else {}),
        },
        promotion_summary={
            "promoted": 1, "points": [{
                "candidate_id": "state", "answer_status": "ANSWERED",
                "disposition": disposition, "canonical_truth_ids": ["current"],
            }],
            "answer_packet": {"answer_status": "ANSWERED"},
            "readback": {"verified": True, "handoff_ids": []},
        },
    )


def _backend(*, include_current=True):
    entry = SimpleNamespace(id="current", to_dict=lambda: {
        "title": "Rehearsal venue", "statement": STATEMENT,
        "module_path": ["Rehearsals"],
    })
    return SimpleNamespace(structured_store=SimpleNamespace(
        knowledge_store=SimpleNamespace(list_entries=AsyncMock(
            return_value=[entry] if include_current else [],
        )),
    ))


def test_not_applicable_no_write_note_never_repeats_agent_saved_claim():
    job = _job(refs=False)
    job.completion_disposition = "no_candidate"
    job.semantic_review["unfinished_work"] = []
    job.semantic_review["final_outcome"] = "Saved all the rules."
    job.promotion_summary = {"promoted": 0, "points": [],
                             "answer_packet": {"answer_status": "NOT_APPLICABLE"}}
    projected = distill_display_review(job)
    assert projected["final_outcome"] == "本次未新增或替换长期记忆。"
    assert job.semantic_review["final_outcome"] == "Saved all the rules."


@pytest.mark.parametrize("disposition", ["add", "confirm", "refine", "replace"])
def test_explicitly_bound_saved_state_is_completed_without_deciding_its_value(disposition):
    job = _job(disposition=disposition)
    original = deepcopy(job.semantic_review)

    result = asyncio.run(current_distill_result(_backend(), job))

    assert result["organization_status"] == "completed"
    assert result["unfinished_work"] == []
    if disposition != "confirm":
        assert result["knowledge_changes"][0]["statement"] == STATEMENT
    assert distill_display_review(job)["unfinished_work"] == []
    assert job.semantic_review == original  # The stored review stays intact.


def test_saved_state_does_not_swallow_a_real_unfinished_action():
    job = _job()
    job.semantic_review["unfinished_work"].append(ACTION)

    result = asyncio.run(current_distill_result(_backend(), job))

    assert result["organization_status"] == "partial"
    assert result["unfinished_work"] == [ACTION]
    assert result["knowledge_changes"][0]["statement"] == STATEMENT


def test_legacy_free_text_is_preserved_without_semantic_guessing():
    job = _job(refs=False)
    # Even identical saved wording cannot silently reclassify a task list item.
    job.semantic_review["unfinished_work"] = [STATEMENT, ACTION]

    result = asyncio.run(current_distill_result(_backend(), job))

    assert result["organization_status"] == "partial"
    assert result["unfinished_work"] == [STATEMENT, ACTION]
    assert SessionSemanticReview.model_validate(job.semantic_review).retained_state_refs == []


@pytest.mark.parametrize("status", ["queued", "reviewing", "retryable", "failed", "stale"])
def test_unfinalized_job_cannot_clear_an_explicitly_bound_item(status):
    assert distill_unfinished_work(_job(status=status)) == [STATE]


@pytest.mark.parametrize("disposition", ["pending", "defer", "handoff", "conflict", "reject", "no_write"])
def test_unsettled_or_nonwriting_candidate_cannot_clear_a_bound_item(disposition):
    job = _job(disposition=disposition)
    result = asyncio.run(current_distill_result(_backend(), job))
    assert result["organization_status"] == "partial"
    assert result["unfinished_work"] == [STATE]


@pytest.mark.parametrize("failure", ["missing_candidate", "missing_truth", "invalid_truth", "unanswered", "mixed_points", "wrong_item", "malformed_ref", "unverified_readback"])
def test_state_binding_requires_the_exact_completed_candidate_receipt(failure):
    job = _job()
    point = job.promotion_summary["points"][0]
    if failure == "missing_candidate":
        job.promotion_summary["points"] = []
    elif failure == "missing_truth":
        point["canonical_truth_ids"] = []
    elif failure == "invalid_truth":
        point["canonical_truth_ids"] = [""]
    elif failure == "unanswered":
        point["answer_status"] = "PARTIAL"
    elif failure == "mixed_points":
        job.promotion_summary["points"].append({
            "candidate_id": "state", "answer_status": "PARTIAL", "disposition": "defer",
        })
    elif failure == "wrong_item":
        job.semantic_review["retained_state_refs"][0]["unfinished_work_item"] = "A different item."
    elif failure == "unverified_readback":
        job.promotion_summary["readback"]["verified"] = False
    else:
        job.semantic_review["retained_state_refs"][0]["force"] = True
    assert distill_unfinished_work(job) == [STATE]


@pytest.mark.parametrize("persisted", ["work_item", "handoff", "deferred_point"])
def test_persisted_work_is_never_erased_by_an_agent_state_binding(persisted):
    job = _job()
    if persisted == "work_item":
        job.promotion_summary["unfinished_work"] = [STATE, ACTION]
    elif persisted == "handoff":
        job.promotion_summary["readback"]["handoff_ids"] = ["task"]
    else:
        job.promotion_summary["points"].append({
            "candidate_id": "other", "answer_status": "PARTIAL", "disposition": "defer",
        })
    result = asyncio.run(current_distill_result(_backend(), job))
    assert result["organization_status"] == "partial"
    assert result["unfinished_work"]
    if persisted == "work_item":
        assert result["unfinished_work"] == [STATE, ACTION]


def test_finalized_replay_uses_the_persisted_binding_and_still_checks_current_rows():
    job = SessionDistillJob.model_validate(_job().model_dump(mode="json"))
    first = asyncio.run(current_distill_result(_backend(), job))
    assert asyncio.run(current_distill_result(_backend(), job)) == first
    with pytest.raises(ValueError, match="missing current knowledge"):
        asyncio.run(current_distill_result(_backend(include_current=False), job))


@pytest.mark.parametrize("payload", [
    {"candidate_id": "", "unfinished_work_item": STATE},
    {"candidate_id": "state", "unfinished_work_item": "   "},
    {"candidate_id": "state", "unfinished_work_item": STATE, "force": True},
])
def test_retained_state_reference_rejects_blank_or_unrecognized_fields(payload):
    with pytest.raises(ValidationError):
        RetainedStateRef.model_validate(payload)
