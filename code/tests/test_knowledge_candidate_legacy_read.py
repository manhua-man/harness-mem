from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.core.schemas.knowledge import KnowledgeCandidate


def _legacy_payload(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "id": "candidate-1",
        "project_name": "harness-mem",
        "candidate_type": "memory",
        "statement": "A verified statement.",
        "status": "pending",
        "assimilation_disposition": "replace",
        "assimilation_reason": "The current statement is stale.",
        "assimilation_target_id": None,
        "canonical_title": "Verified statement",
        "topic_path": ["project"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_candidate_reader_ignores_null_legacy_target_id() -> None:
    candidate = KnowledgeCandidate.from_dict(_legacy_payload())

    assert candidate.assimilation_target_ids == []


def test_candidate_reader_maps_non_null_legacy_target_id() -> None:
    candidate = KnowledgeCandidate.from_dict(
        _legacy_payload(assimilation_target_id="knowledge-1")
    )

    assert candidate.assimilation_target_ids == ["knowledge-1"]
