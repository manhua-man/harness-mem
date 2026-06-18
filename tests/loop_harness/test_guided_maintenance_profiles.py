"""Loop harness scenario 12 — guided maintenance profiles stay opt-in.

Business question:
Can an agent enable a maintenance profile and preview its status guidance
without accidentally running maintenance or mutating truth?

Loop:

update_project_profile(maintenance_profile)
  -> get_project_status resolves active/suggested/available profiles
  -> dry-run summaries expose candidate/risk fields
  -> confirmed truth, pending candidates, and retrieval signals remain unchanged
"""

from __future__ import annotations

import pytest

from harness_mem.core.schemas import MemoryEntry, Observation
from harness_mem.core.schemas.rule_candidate import RuleCandidate
from harness_mem.mcp.server import (
    set_backend_override,
    tool_get_project_status,
    tool_update_project_profile,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run
from tests.loop_harness.conftest import LoopMetrics


pytestmark = pytest.mark.loop_harness


def _candidate_count(backend: LocalMemoryBackend, project_name: str) -> int:
    return (
        len(run(backend.structured_store.list_rule_candidates(project_name)))
        + len(
            run(
                backend.structured_store.list_memory_entries(
                    project_name,
                    status="pending",
                    limit=100,
                )
            )
        )
        + len(
            run(
                backend.structured_store.list_relation_facts(
                    project_name,
                    status="pending",
                    limit=100,
                )
            )
        )
    )


def _truth_count(backend: LocalMemoryBackend, project_name: str) -> int:
    return (
        len(run(backend.structured_store.list_memory_entries(project_name, limit=100)))
        + len(run(backend.structured_store.list_confirmed_rules(project_name)))
        + len(run(backend.structured_store.list_relation_facts(project_name, limit=100)))
    )


def _signal_count(backend: LocalMemoryBackend, project_name: str) -> int:
    return len(run(backend.structured_store.query_retrieval_signals(project_name)))


def test_guided_maintenance_profile_dry_run_is_explainable_and_truth_safe(
    backend: LocalMemoryBackend,
) -> None:
    project_name = "loop-guided-maintenance"
    run(
        backend.verbatim_store.save(
            Observation(
                id="obs-guided-maintenance",
                session_id="guided-maintenance-session",
                client="codex",
                raw_content=(
                    "The project has pending memory candidates after a distill pass, "
                    "so a post-distill maintenance preview should explain review work."
                ),
                content_type="transcript",
                metadata={"project_name": project_name},
            )
        )
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="guided-maintenance-current",
                project_name=project_name,
                category="decision",
                content="Guided maintenance profiles must remain explicit opt-in.",
                source="manual",
                confidence=0.9,
            )
        )
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="guided-maintenance-pending-entry",
                project_name=project_name,
                category="decision",
                content="Review this pending memory before promotion.",
                source="obs-guided-maintenance",
                confidence=0.6,
                status="pending",
            )
        )
    )
    run(
        backend.structured_store.save_rule_candidate(
            RuleCandidate(
                id="guided-maintenance-pending-rule",
                project_name=project_name,
                session_id="guided-maintenance-session",
                pattern="Preview maintenance before applying dream or metabolism.",
                trigger="When candidates remain after distill",
                examples=["obs-guided-maintenance"],
                confidence=0.7,
            )
        )
    )

    before_truth = _truth_count(backend, project_name)
    before_candidates = _candidate_count(backend, project_name)
    before_signals = _signal_count(backend, project_name)

    set_backend_override(backend)
    try:
        update = tool_update_project_profile(
            project_name=project_name,
            maintenance_profile="post-distill-metabolism",
        )
        status = tool_get_project_status(project_name=project_name)
    finally:
        set_backend_override(None)

    profiles = status["maintenance_profiles"]
    dry_runs = profiles["dry_runs"]
    required_summary_fields = {
        "candidate_counts",
        "risk_level",
        "auto_applied",
        "needs_human_review",
        "undo_available",
        "message",
    }
    summaries = [profile["dry_run"] for profile in dry_runs.values()]
    summary_fields_present = all(
        required_summary_fields.issubset(summary) for summary in summaries
    )
    auto_applied_count = sum(1 for summary in summaries if summary["auto_applied"])
    after_truth = _truth_count(backend, project_name)
    after_candidates = _candidate_count(backend, project_name)
    after_signals = _signal_count(backend, project_name)

    LoopMetrics(
        name="guided_maintenance_profiles",
        values={
            "profile_update_success": 1.0 if update["success"] else 0.0,
            "dry_run_count": float(len(dry_runs)),
            "summary_fields_present": 1.0 if summary_fields_present else 0.0,
            "auto_applied_count": float(auto_applied_count),
            "truth_mutation_count": float(after_truth - before_truth),
            "candidate_mutation_count": float(after_candidates - before_candidates),
            "signal_mutation_count": float(after_signals - before_signals),
        },
    ).report()

    assert update["success"] is True
    assert update["profile"]["maintenance_profile"] == "post-distill-metabolism"
    assert profiles["active"] == "post-distill-metabolism"
    assert profiles["suggested"] == "post-distill-metabolism"
    assert set(dry_runs) == {"post-distill-metabolism", "weekly-dream"}
    assert summary_fields_present is True
    assert dry_runs["post-distill-metabolism"]["dry_run"]["needs_human_review"] is True
    assert dry_runs["post-distill-metabolism"]["dry_run"]["auto_applied"] is False
    assert auto_applied_count == 0
    assert after_truth == before_truth
    assert after_candidates == before_candidates
    assert after_signals == before_signals
