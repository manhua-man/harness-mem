"""Dream structural isolation preserves shared validation and final judgment."""
import copy
import json

import pytest

from harness_mem.autonomous.models import AssimilationDecision
from harness_mem.commands import dream
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation, target_version, update_meaning_block,
)


def prepared(count=3):
    truth = []
    candidates = []
    for index in range(count):
        row = dict(id=f"entry-{index}", handle=f"K{index}", title=f"Cache {index}",
                   statement=f"Cache {index} stays local during the trial.",
                   topic_path=["cache"], source_report=None)
        row["version"] = target_version(row)
        truth.append(row)
        candidates.append(dict(candidate_id=f"dream:entry-{index}",
                               statement=f"Cache {index} stays local.", evidence_basis="user_statement"))
    ids = tuple(item["candidate_id"] for item in candidates)
    return SeparatedPreparedAssimilation(
        project_name="demo", project_root="isolated-fixture", candidate_ids=ids,
        eligible_candidate_ids=ids, automatic_points=(),
        answer_status_by_candidate={identity: "ANSWERED" for identity in ids},
        truth_by_handle={row["handle"]: row["id"] for row in truth},
        manifest={"current_truth": truth, "verified_candidates": candidates},
    )


def proposal(count=3):
    return AssimilationDecision.model_validate({"points": [dict(
        candidate_id=f"dream:entry-{index}", disposition="refine",
        matched_truth_handles=[f"K{index}"], knowledge_items=[dict(
            title=f"Cache {index}", statement=f"Cache {index} stays local.",
            topic_path=["cache"], claim_kind="implementation_fact")],
        reason="Keep the scoped cache rule with complete source support.",
    ) for index in range(count)]})


def normalize(decision, *, groups=None, source=None, report_ids=None):
    source = source or prepared(len(decision.points))
    notes = []
    payloads = dream._normalize_dream_proposal_groups(
        source, decision,
        identities={value: key for key, value in zip(source.eligible_candidate_ids,
                                                    source.truth_by_handle.values())},
        groups=groups or [[identity] for identity in source.truth_by_handle.values()],
        report_ids=report_ids or set(), receipts=notes,
    )
    return payloads, [json.loads(note.split(": ", 1)[1]) for note in notes]


def bad_nonwrite(point):
    # The common validator remains responsible even when a provider adapter
    # returns an already-created model object with malformed field contents.
    point.disposition = "no_write"
    point.knowledge_items = []
    point.reason = "PRIVATE_PROPOSAL_REASON_MUST_NOT_PERSIST"


def test_bad_nonwrite_does_not_suppress_independent_group():
    decision = proposal()
    bad_nonwrite(decision.points[0])
    before = copy.deepcopy(decision.model_dump())
    payloads, notes = normalize(decision)
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-1", "dream:entry-2"]
    assert decision.model_dump() == before
    assert notes[0]["code"] == "comparison_group_normalization_failed"
    assert notes[0]["points"] == [dict(candidate_id="dream:entry-0", disposition="no_write",
                                      handle_count=1, known_handle_count=1)]
    assert "PRIVATE_PROPOSAL_REASON" not in json.dumps(notes)


def test_bad_point_blocks_its_complete_original_group():
    decision = proposal()
    bad_nonwrite(decision.points[0])
    payloads, notes = normalize(decision, groups=[["entry-0", "entry-1"], ["entry-2"]])
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-2"]
    assert len(notes[0]["points"]) == 2


def test_cross_group_reference_blocks_all_connected_groups():
    decision = proposal(4)
    decision.points[0].matched_truth_handles.append("K1")
    decision.points[1].matched_truth_handles.append("K2")
    payloads, notes = normalize(decision)
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-3"]
    assert len(notes[0]["points"]) == 3


@pytest.mark.parametrize("invalid", ["unknown_handle", "unknown_candidate", "missing_candidate", "duplicate_candidate"])
def test_global_coverage_and_unknown_handles_fail_closed(invalid):
    decision = proposal()
    source = prepared()
    if invalid == "unknown_handle":
        decision.points[0].matched_truth_handles = ["unknown"]
    elif invalid == "unknown_candidate":
        decision.points[0].candidate_id = "PRIVATE_UNKNOWN_CANDIDATE"
    elif invalid == "missing_candidate":
        decision.points.pop()
    else:
        decision.points[1].candidate_id = decision.points[0].candidate_id
    payloads, notes = normalize(decision, source=source)
    assert payloads == []
    assert notes[0]["code"] == "common_normalization_failed"
    assert "PRIVATE_UNKNOWN_CANDIDATE" not in json.dumps(notes)


def test_reused_mutating_target_still_rejects_whole_original_group():
    decision = proposal()
    decision.points[1].matched_truth_handles.append("K0")
    payloads, notes = normalize(decision, groups=[["entry-0", "entry-1"], ["entry-2"]])
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-2"]
    assert any("validate_separated_assimilation_decision" in location
               for location in notes[0]["failure_details"]["exception_locations"])


@pytest.mark.parametrize("failure", ["missing_own_target", "typed_report"])
def test_payload_boundary_error_is_also_group_local(failure):
    decision = proposal()
    report_ids = set()
    if failure == "missing_own_target":
        decision.points[0].matched_truth_handles = ["K1"]
        decision.points[1].disposition = "defer"
        decision.points[1].matched_truth_handles = []
        decision.points[1].knowledge_items = []
    else:
        report_ids = {"entry-0"}
    payloads, notes = normalize(decision, groups=[["entry-0", "entry-1"], ["entry-2"]], report_ids=report_ids)
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-2"]
    assert len(notes[0]["points"]) == 2


def test_full_common_validation_runs_after_merging_and_can_reject(monkeypatch):
    original = dream.validate_separated_assimilation_decision
    seen = []

    def validator(source, decision):
        seen.append(len(source.eligible_candidate_ids))
        if len(source.eligible_candidate_ids) == 3:
            raise ValueError("one current truth target is reused across points that mutate it")
        return original(source, decision)

    monkeypatch.setattr(dream, "validate_separated_assimilation_decision", validator)
    payloads, notes = normalize(proposal())
    assert seen == [1, 1, 1, 3]
    assert payloads == []
    assert notes[-1]["code"] == "common_normalization_failed"


def test_common_validator_mutations_never_leak_to_proposal_or_prepared(monkeypatch):
    original = dream.validate_separated_assimilation_decision
    decision = proposal()
    source = prepared()
    before = copy.deepcopy((decision.model_dump(), source.manifest))

    def validator(local, proposed):
        result = original(local, proposed)
        proposed.points[0].reason = "LOCAL_NORMALIZATION_MUTATION"
        local.manifest["current_truth"][0]["title"] = "LOCAL_PREPARED_MUTATION"
        return result

    monkeypatch.setattr(dream, "validate_separated_assimilation_decision", validator)
    payloads, _notes = normalize(decision, source=source)
    assert len(payloads) == 3
    assert (decision.model_dump(), source.manifest) == before


def test_surviving_proposal_still_has_no_whole_update_authority():
    decision = proposal()
    bad_nonwrite(decision.points[0])
    payloads, _notes = normalize(decision)
    assert len(payloads) == 2
    assert all(update_meaning_block(payload) == "final_update_meaning_incomplete"
               for _point, payload in payloads)


def test_report_claim_cannot_cross_common_fact_authority_boundary():
    decision = proposal()
    decision.points[0].knowledge_items[0].claim_kind = "source_report"
    payloads, notes = normalize(decision)
    assert [point["candidate_id"] for point, _payload in payloads] == ["dream:entry-1", "dream:entry-2"]
    assert notes[0]["code"] == "comparison_group_normalization_failed"
