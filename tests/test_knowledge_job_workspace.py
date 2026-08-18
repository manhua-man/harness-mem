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


def test_workspace_cleanup_removes_only_the_requested_job(tmp_path) -> None:
    store = KnowledgeJobWorkspace(tmp_path)
    first = _candidate("candidate-1")
    second = _candidate("candidate-2")
    store.save_candidate(first, workspace_id="job-a")
    store.save_candidate(second, workspace_id="job-b")

    assert store.cleanup_workspace("job-a") == 1
    assert store.get_candidate(first.id) is None
    assert store.get_candidate(second.id) == second
