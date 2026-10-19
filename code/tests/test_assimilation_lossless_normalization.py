"""Shared qualifiers must not erase distinct facts or enable destructive repair."""
from copy import deepcopy

import pytest

from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.autonomous.worker import _repair_invalid_writing_with_source_clauses
from harness_mem.commands.separated_assimilation import _normalize_split_knowledge_items


@pytest.mark.parametrize("separator", [", ", "，", "、"])
def test_independent_items_with_shared_subject_and_qualifiers_survive(separator):
    suffix = separator.join(["approval is required", "discussion is not approval", "current rules remain"])
    statements = [
        "Cedar retries Timeout and ServerFault. " + suffix,
        "Cedar disables text messages. " + suffix,
        "Cedar availability is explicitly undecided. " + suffix,
    ]
    items = [{"title": str(index), "statement": statement,
              "topic_path": ["Cedar", str(index)], "claim_kind": "design_requirement"}
             for index, statement in enumerate(statements)]
    before = deepcopy(items)
    assert _normalize_split_knowledge_items(items) == items
    assert items == before


def test_only_value_identical_payloads_are_deduplicated():
    item = {"title": "Cedar policy", "statement": "Cedar keeps source evidence.",
            "topic_path": ["Cedar"], "claim_kind": "procedure"}
    same_statement_different_scope = {**item, "topic_path": ["Pilot evidence"]}
    assert _normalize_split_knowledge_items([item, deepcopy(item), same_statement_different_scope]) == [
        item, same_statement_different_scope,
    ]


@pytest.mark.parametrize("disposition", ["refine", "replace"])
def test_candidate_only_wording_repair_cannot_retire_existing_truth(disposition):
    candidate_id = "new-proposal-status"
    manifest = {
        "verified_candidates": [{"candidate_id": candidate_id,
                                 "statement": "Cedar's proposed setting requires explicit approval."}],
        "current_truth": [{"handle": "T-existing",
                           "statement": "Cedar retries Timeout and ServerFault."}],
    }
    decision = AssimilationDecision.model_validate({"points": [{
        "candidate_id": candidate_id, "disposition": disposition,
        "matched_truth_handles": ["T-existing"], "reason": "Add the approval qualification.",
        "knowledge_items": [{"title": "Cedar retry rule",
            "statement": "Cedar retries Timeout and ServerFault; its proposed setting requires explicit approval.",
            "topic_path": ["Cedar"], "claim_kind": "design_requirement"}],
    }]})
    before = decision.model_dump(mode="json")
    assert _repair_invalid_writing_with_source_clauses(
        decision, manifest=manifest, error=ValueError("canonical knowledge has invalid wording"),
    ) is None
    assert decision.model_dump(mode="json") == before
