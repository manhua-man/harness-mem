"""Golden checks for the 0.9.13 read-only assimilation baseline."""

from __future__ import annotations

import pytest

from harness_mem.qualification.assimilation_shadow import (
    project_clean_memory,
    shadow_fixture,
)
from harness_mem.qualification.distill_fixture_catalog import fixture


def _dispositions(fixture_id: str) -> dict[str, str]:
    report = shadow_fixture(fixture(fixture_id)["shadow"])
    assert report.mutation_count == 0
    return {item.candidate_id: item.disposition for item in report.dispositions}


def test_f8_multi_promotion_points_terminate_independently() -> None:
    assert _dispositions("F8") == {
        "f8-add": "add",
        "f8-refine": "refine",
        "f8-confirm": "confirm",
        "f8-no-write": "no_write",
        "f8-handoff": "handoff",
    }


def test_f9_separates_a_one_off_request_from_a_durable_preference() -> None:
    assert _dispositions("F9") == {
        "f9-list-now": "no_write",
        "f9-future-audit-preference": "add",
    }


def test_f10_preserves_confirm_refine_and_conflict_as_distinct_outcomes() -> None:
    assert _dispositions("F10") == {
        "f10-confirm": "confirm",
        "f10-refine": "refine",
        "f10-conflict": "conflict",
    }


def test_f11_clean_projection_excludes_audit_metadata() -> None:
    item = fixture("F11")["shadow"]["retrieval_record"]
    projected = project_clean_memory(item)

    assert projected == {
        "title": "Archive cleanup safety",
        "statement": "When destructive source cleanup cannot be verified as safe, fail closed and retain the source.",
        "scope": "harness-mem maintenance",
    }
    assert set(projected).isdisjoint(fixture("F11")["shadow"]["forbidden_projection_fields"])


def test_shadow_fails_closed_when_a_fixture_targets_missing_current_truth() -> None:
    invalid = fixture("F10")["shadow"]
    invalid["promotion_points"][0]["matched_truth_id"] = "missing-current-truth"

    report = shadow_fixture(invalid)
    first = report.dispositions[0]
    assert first.disposition == "defer"
    assert first.matched_truth_ids == ()


def test_shadow_rejects_a_forbidden_write_fixture_that_is_not_non_mutating() -> None:
    invalid = fixture("F9")["shadow"]
    invalid["forbidden_write_ids"] = ["f9-future-audit-preference"]

    with pytest.raises(ValueError, match="forbidden write"):
        shadow_fixture(invalid)
