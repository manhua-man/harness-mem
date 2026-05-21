from pathlib import Path

from harness_mem.core.schemas import ProceduralCandidate, Skill
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run


def test_confirm_procedural_candidate_creates_searchable_skill(tmp_path: Path) -> None:
    store = LocalStructuredStore(tmp_path)
    candidate = ProceduralCandidate(
        project_name="demo",
        activation_condition="Focused runtime change needs validation",
        steps=["Run focused tests", "Run ruff and mypy", "Run full pytest"],
        termination_condition="All checks are green",
        success_examples=["328 passed, 1 skipped"],
        source_session_id="session-proc-001",
        confidence=0.8,
        status="pending",
    )

    run(store.save_procedural_candidate(candidate))
    skill = run(store.confirm_procedural_candidate(candidate.id))

    assert skill is not None
    assert skill.source_candidate_id == candidate.id
    assert skill.source_session_id == "session-proc-001"
    assert run(store.get_procedural_candidate(candidate.id)).status == "accepted"
    matches = run(store.search_skills("ruff mypy validation", project_name="demo"))
    assert [match.id for match in matches] == [skill.id]


def test_record_skill_result_updates_success_rate(tmp_path: Path) -> None:
    store = LocalStructuredStore(tmp_path)
    skill = Skill(
        project_name="demo",
        name="Focused validation loop",
        activation_condition="Need to validate runtime behavior",
        steps=["Run focused tests", "Run full pytest"],
        termination_condition="Validation passes",
    )
    run(store.save_skill(skill))

    first = run(store.record_skill_result(skill.id, success=True))
    second = run(store.record_skill_result(skill.id, success=False))

    assert first is not None and first.success_rate == 1.0
    assert second is not None
    assert second.usage_count == 2
    assert second.success_count == 1
    assert second.failure_count == 1
    assert second.success_rate == 0.5
