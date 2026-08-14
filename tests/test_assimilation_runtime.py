"""Isolated persistence checks for per-point autonomous assimilation."""

from __future__ import annotations

import asyncio

from harness_mem.commands.assimilation import apply_assimilation
from harness_mem.core.schemas import MemoryEntry, RuleCandidate
from harness_mem.qualification.memory_assimilation_outcome_probe import (
    run_memory_assimilation_outcome_probe,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _run(coro):
    return asyncio.run(coro)


def test_apply_assimilation_keeps_points_independent_and_materializes_rules(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        current = MemoryEntry(
            id="current-memory",
            project_name="demo",
            category="decision",
            content="The project keeps audit details separate from normal retrieval.",
            source="fixture",
            status="auto_confirmed",
        )
        addition = MemoryEntry(
            id="addition",
            project_name="demo",
            category="decision",
            content="placeholder",
            source="fixture",
            distill_job_id="job-1",
        )
        duplicate = MemoryEntry(
            id="duplicate",
            project_name="demo",
            category="decision",
            content="placeholder",
            source="fixture",
            distill_job_id="job-1",
        )
        one_off = MemoryEntry(
            id="one-off",
            project_name="demo",
            category="decision",
            content="Show the current list now.",
            source="fixture",
            distill_job_id="job-1",
        )
        rule = RuleCandidate(
            id="rule-add",
            project_name="demo",
            session_id="session-1",
            pattern="Provide an itemized list.",
            trigger="When presenting a memory audit.",
            distill_job_id="job-1",
        )
        handoff = MemoryEntry(
            id="handoff",
            project_name="demo",
            category="decision",
            content="Run the remaining rollout after verification.",
            source="fixture",
            distill_job_id="job-1",
        )
        for candidate in (current, addition, duplicate, one_off, rule, handoff):
            if isinstance(candidate, RuleCandidate):
                _run(backend.structured_store.save_rule_candidate(candidate))
            else:
                _run(backend.structured_store.save_memory_entry(candidate))

        plan = {
            "version": "v1",
            "points": [
                {
                    "candidate_id": "addition",
                    "answer_status": "ANSWERED",
                    "disposition": "add",
                    "matched_truth_ids": [],
                    "matched_truth_kinds": [],
                    "canonical_title": "Audit boundary",
                    "canonical_statement": "Normal retrieval excludes audit metadata.",
                    "topic_path": ["memory", "retrieval"],
                    "reason": "New project retrieval rule.",
                },
                {
                    "candidate_id": "duplicate",
                    "answer_status": "ANSWERED",
                    "disposition": "confirm",
                    "matched_truth_ids": ["current-memory"],
                    "matched_truth_kinds": ["memory_entry"],
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "reason": "Current truth already represents the point.",
                },
                {
                    "candidate_id": "one-off",
                    "answer_status": "ANSWERED",
                    "disposition": "no_write",
                    "matched_truth_ids": [],
                    "matched_truth_kinds": [],
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "reason": "This is an output request for the current task.",
                },
                {
                    "candidate_id": "rule-add",
                    "answer_status": "ANSWERED",
                    "disposition": "add",
                    "matched_truth_ids": [],
                    "matched_truth_kinds": [],
                    "canonical_title": "Memory audit presentation",
                    "canonical_statement": "When presenting a memory audit, provide an itemized list.",
                    "topic_path": ["memory", "audit"],
                    "reason": "Explicit future preference with condition and behavior.",
                },
                {
                    "candidate_id": "handoff",
                    "answer_status": "PARTIAL",
                    "disposition": "handoff",
                    "matched_truth_ids": [],
                    "matched_truth_kinds": [],
                    "canonical_title": None,
                    "canonical_statement": "Run the remaining rollout after verification.",
                    "topic_path": [],
                    "reason": "Work remains unfinished.",
                },
            ],
        }
        result = _run(
            apply_assimilation(
                backend,
                project_name="demo",
                candidate_ids=["addition", "duplicate", "one-off", "rule-add", "handoff"],
                plan=plan,
            )
        )

        memories = _run(backend.structured_store.list_memory_entries("demo", limit=20))
        rules = _run(backend.structured_store.list_confirmed_rules("demo"))
        handoffs = _run(backend.structured_store.get_latest_handoffs("demo", limit=10))
        duplicate_stored = _run(backend.structured_store.get_memory_entry("duplicate"))
        one_off_stored = _run(backend.structured_store.get_memory_entry("one-off"))

        assert result["promoted"] == 2
        assert result["confirmed"] == 1
        assert result["no_write"] == 1
        assert result["handoff"] == 1
        assert {item.id for item in memories} == {"current-memory", "addition"}
        assert len(rules) == 1 and rules[0].source_candidate_id == "rule-add"
        assert len(handoffs) == 1 and handoffs[0].context["distill_job_id"] == "job-1"
        assert duplicate_stored is not None and duplicate_stored.status == "rejected"
        assert one_off_stored is not None and one_off_stored.status == "rejected"
    finally:
        _run(backend.close())


def test_multi_point_assimilation_outcome_probe() -> None:
    result = run_memory_assimilation_outcome_probe()

    assert result["verified"] is True


def test_assimilation_refines_and_supersedes_without_writing_conflict_truth(tmp_path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    _run(backend.init())
    try:
        refine_target = MemoryEntry(
            id="refine-target",
            project_name="demo",
            category="decision",
            content="The project documents broad memory rules.",
            source="fixture",
            status="auto_confirmed",
        )
        supersede_target = MemoryEntry(
            id="supersede-target",
            project_name="demo",
            category="decision",
            content="The project keeps raw audit data in normal retrieval.",
            source="fixture",
            status="auto_confirmed",
        )
        conflict_target = MemoryEntry(
            id="conflict-target",
            project_name="demo",
            category="decision",
            content="The project preserves immutable source revisions.",
            source="fixture",
            status="auto_confirmed",
        )
        refinement = MemoryEntry(
            id="refinement",
            project_name="demo",
            category="decision",
            content="placeholder",
            source="fixture",
            distill_job_id="job-2",
        )
        replacement = MemoryEntry(
            id="replacement",
            project_name="demo",
            category="decision",
            content="placeholder",
            source="fixture",
            distill_job_id="job-2",
        )
        conflict = MemoryEntry(
            id="conflict",
            project_name="demo",
            category="decision",
            content="placeholder",
            source="fixture",
            distill_job_id="job-2",
        )
        for entry in (
            refine_target,
            supersede_target,
            conflict_target,
            refinement,
            replacement,
            conflict,
        ):
            _run(backend.structured_store.save_memory_entry(entry))

        result = _run(
            apply_assimilation(
                backend,
                project_name="demo",
                candidate_ids=["refinement", "replacement", "conflict"],
                plan={
                    "version": "v1",
                    "points": [
                        {
                            "candidate_id": "refinement",
                            "answer_status": "ANSWERED",
                            "disposition": "refine",
                            "matched_truth_ids": ["refine-target"],
                            "matched_truth_kinds": ["memory_entry"],
                            "canonical_title": "Memory rule documentation",
                            "canonical_statement": (
                                "Document each current memory rule with its condition and behavior."
                            ),
                            "topic_path": ["memory", "governance"],
                            "reason": "The verified point narrows the broad rule.",
                        },
                        {
                            "candidate_id": "replacement",
                            "answer_status": "ANSWERED",
                            "disposition": "supersede",
                            "matched_truth_ids": ["supersede-target"],
                            "matched_truth_kinds": ["memory_entry"],
                            "canonical_title": "Audit retrieval boundary",
                            "canonical_statement": "Normal retrieval excludes raw audit data.",
                            "topic_path": ["memory", "retrieval"],
                            "reason": "The old statement is no longer current.",
                        },
                        {
                            "candidate_id": "conflict",
                            "answer_status": "ANSWERED",
                            "disposition": "conflict",
                            "matched_truth_ids": ["conflict-target"],
                            "matched_truth_kinds": ["memory_entry"],
                            "canonical_title": None,
                            "canonical_statement": None,
                            "topic_path": [],
                            "reason": "The supplied evidence does not resolve the conflict.",
                        },
                    ],
                },
            )
        )

        stored = {
            entry_id: _run(backend.structured_store.get_memory_entry(entry_id))
            for entry_id in (
                "refine-target",
                "supersede-target",
                "conflict-target",
                "refinement",
                "replacement",
                "conflict",
            )
        }
        current = _run(backend.structured_store.list_memory_entries("demo", limit=20))

        assert result["promoted"] == 2
        assert result["conflict"] == 1
        assert stored["refine-target"].status == "auto_confirmed"
        assert stored["refine-target"].valid_to is not None
        assert stored["refine-target"].superseded_by == ["refinement"]
        assert stored["supersede-target"].status == "auto_confirmed"
        assert stored["supersede-target"].valid_to is not None
        assert stored["supersede-target"].superseded_by == ["replacement"]
        assert stored["conflict-target"].status == "auto_confirmed"
        assert stored["refinement"].status == "auto_confirmed"
        assert stored["replacement"].status == "auto_confirmed"
        assert stored["conflict"].status == "deferred"
        assert {entry.id for entry in current} == {
            "conflict-target",
            "refinement",
            "replacement",
        }
        assert all(
            entry.id != "conflict"
            for entry in _run(backend.structured_store.search_memory_entries(
                "placeholder", project_name="demo", limit=20
            ))
        )
    finally:
        _run(backend.close())
