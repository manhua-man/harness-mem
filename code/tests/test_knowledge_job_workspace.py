from datetime import datetime, timedelta, timezone

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEvidence,
)
from harness_mem.storage.knowledge_job_workspace import KnowledgeJobWorkspace


def _candidate(candidate_id: str = "candidate-1") -> KnowledgeCandidate:
    return KnowledgeCandidate(
        id=candidate_id,
        project_name="demo",
        candidate_type="memory",
        statement="A retry-safe candidate.",
    )


def _evidence(candidate_id: str = "candidate-1") -> KnowledgeEvidence:
    return KnowledgeEvidence(
        id="evidence-1",
        project_name="demo",
        candidate_id=candidate_id,
        distill_job_id="job-1",
        evidence_basis="user_statement",
        verification_outcome="verified",
    )


def test_active_workspace_survives_restart_and_is_bound_to_job(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    candidate = _candidate()
    evidence = _evidence()

    store.save_candidate(candidate)
    store.save_evidence(evidence)

    reopened = KnowledgeJobWorkspace(tmp_path)
    assert reopened.get_candidate(candidate.id) == candidate
    assert reopened.list_evidence(candidate.id) == [evidence]
    assert reopened.workspace_id_for_candidate(candidate.id) == "job-1"
    assert not (tmp_path / "knowledge_audit").exists()


def test_terminal_cleanup_removes_candidate_evidence_and_decision(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    candidate = _candidate()
    store.save_candidate(candidate)
    store.save_evidence(_evidence())
    decision = AssimilationDecision(
        id="decision-1",
        project_name="demo",
        candidate_id=candidate.id,
        disposition="defer",
        reason="Needs current repository evidence.",
    )
    store.save_unresolved_decision(decision)

    store.cleanup_candidate(candidate.id)

    assert store.get_candidate(candidate.id) is None
    assert store.list_evidence(candidate.id) == []
    assert store.get_unresolved_decision(decision.id) is None
    assert not store.root.exists()


def test_defer_and_conflict_are_the_only_persisted_decisions(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    candidate = _candidate()
    store.save_candidate(candidate)
    for disposition in ("defer", "conflict"):
        decision = AssimilationDecision(
            id=f"decision-{disposition}",
            project_name="demo",
            candidate_id=candidate.id,
            disposition=disposition,
            reason="Still unresolved.",
        )
        assert store.save_unresolved_decision(decision) == decision.id

    terminal = AssimilationDecision(
        id="decision-add",
        project_name="demo",
        candidate_id=candidate.id,
        disposition="add",
        reason="Terminal.",
    )
    try:
        store.save_unresolved_decision(terminal)
    except ValueError as error:
        assert "only unresolved" in str(error)
    else:
        raise AssertionError("terminal decision must not persist in job workspace")


def test_unresolved_decision_replay_ignores_fresh_timestamps(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    candidate = KnowledgeCandidate(
        id="candidate-replay",
        project_name="demo",
        candidate_type="memory",
        statement="A retry must preserve the same unresolved decision.",
    )
    store.save_candidate(candidate, workspace_id="job-replay")
    first = AssimilationDecision(
        id="decision-replay",
        project_name="demo",
        candidate_id=candidate.id,
        disposition="defer",
        reason="The next review still needs current repository evidence.",
    )
    store.save_unresolved_decision(first)
    replay = AssimilationDecision(
        id=first.id,
        project_name=first.project_name,
        candidate_id=first.candidate_id,
        disposition=first.disposition,
        reason=first.reason,
    )

    assert replay.decided_at != first.decided_at
    assert store.save_unresolved_decision(replay) == first.id
    assert store.get_unresolved_decision(first.id) == first


def test_expired_workspace_is_pruned(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    candidate = _candidate()
    store.save_candidate(candidate, workspace_id="retry-job")

    assert (
        store.prune_expired(
            ttl_seconds=60,
            now=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        == 1
    )
    assert store.get_candidate(candidate.id) is None


def test_workspace_cleanup_removes_only_resolved_candidates_for_requested_job(
    tmp_path,
) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    first = _candidate("candidate-1")
    second = _candidate("candidate-2")
    first.status = "assimilated"
    store.save_candidate(first, workspace_id="job-a")
    store.save_candidate(second, workspace_id="job-b")

    assert store.cleanup_workspace("job-a") == 1
    assert store.get_candidate(first.id) is None
    assert store.get_candidate(second.id) == second


def test_workspace_cleanup_preserves_defer_and_conflict_for_review(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    deferred = _candidate("candidate-deferred")
    deferred.status = "deferred"
    conflicted = _candidate("candidate-conflict")
    conflicted.status = "conflict"
    resolved = _candidate("candidate-resolved")
    resolved.status = "rejected"
    for candidate in (deferred, conflicted, resolved):
        store.save_candidate(candidate, workspace_id="job-terminal")
        evidence = _evidence(candidate.id)
        evidence.id = f"evidence-{candidate.id}"
        evidence.distill_job_id = "job-terminal"
        store.save_evidence(evidence)
    for candidate, disposition in (
        (deferred, "defer"),
        (conflicted, "conflict"),
    ):
        store.save_unresolved_decision(
            AssimilationDecision(
                id=f"decision-{candidate.id}",
                project_name="demo",
                candidate_id=candidate.id,
                disposition=disposition,
                reason="Review must retain this unresolved point.",
            )
        )

    assert store.cleanup_workspace("job-terminal") == 1
    assert store.get_candidate(resolved.id) is None
    assert store.list_evidence(resolved.id) == []
    assert store.get_candidate(deferred.id) == deferred
    assert store.get_candidate(conflicted.id) == conflicted
    assert store.list_evidence(deferred.id)
    assert store.list_evidence(conflicted.id)
    assert {
        item.disposition for item in store.list_unresolved_decisions()
    } == {"defer", "conflict"}
