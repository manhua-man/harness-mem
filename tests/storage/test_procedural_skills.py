from pathlib import Path

from harness_mem.core.schemas import ProceduralCandidate, Skill
from harness_mem.read_api import serialize_skill
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
    assert skill.scope == "project"
    assert skill.origin_project == "demo"
    assert candidate.id in skill.source_ids
    assert "session-proc-001" in skill.source_ids
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


def test_skill_from_legacy_dict_defaults_to_project_scope() -> None:
    skill = Skill.from_dict(
        {
            "id": "legacy-skill",
            "project_name": "demo",
            "name": "Legacy skill",
            "activation_condition": "When validating legacy data",
            "steps": ["Run the legacy check"],
            "termination_condition": "The check passes",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )

    assert skill.scope == "project"
    assert skill.origin_project == "demo"
    assert skill.source_ids == []
    assert skill.portability_notes == ""
    assert skill.disabled_assumptions == []


def test_shared_skill_metadata_round_trips_and_serializes(tmp_path: Path) -> None:
    store = LocalStructuredStore(tmp_path)
    skill = Skill(
        project_name="shared-library",
        name="Release hygiene",
        activation_condition="When preparing a release",
        steps=["Run tests", "Update changelog"],
        termination_condition="Release checks pass",
        scope="global",
        origin_project="harness-mem",
        source_ids=["skill-source", "observation-source"],
        portability_notes="Use only for Python packages with pytest.",
        disabled_assumptions=["Do not assume npm scripts exist."],
    )

    run(store.save_skill(skill))
    loaded = run(store.get_skill(skill.id))
    matches = run(store.search_skills("release changelog", project_name=None))

    assert loaded is not None
    assert loaded.scope == "global"
    assert loaded.origin_project == "harness-mem"
    assert loaded.source_ids == ["skill-source", "observation-source"]
    assert loaded.portability_notes == "Use only for Python packages with pytest."
    assert loaded.disabled_assumptions == ["Do not assume npm scripts exist."]
    assert [match.id for match in matches] == [skill.id]

    serialized = serialize_skill(loaded)
    assert serialized["scope"] == "global"
    assert serialized["origin_project"] == "harness-mem"
    assert serialized["source_ids"] == ["skill-source", "observation-source"]
    assert serialized["portability_notes"] == "Use only for Python packages with pytest."
    assert serialized["disabled_assumptions"] == ["Do not assume npm scripts exist."]


def test_default_project_skill_search_excludes_shared_scope(tmp_path: Path) -> None:
    store = LocalStructuredStore(tmp_path)
    project_skill = Skill(
        project_name="demo",
        name="Project release hygiene",
        activation_condition="When preparing a release",
        steps=["Run project checks"],
        termination_condition="Project release checks pass",
    )
    global_skill = Skill(
        project_name="demo",
        name="Global release hygiene",
        activation_condition="When preparing a release",
        steps=["Run global checks"],
        termination_condition="Global release checks pass",
        scope="global",
        origin_project="other-project",
    )

    run(store.save_skill(project_skill))
    run(store.save_skill(global_skill))

    listed = run(store.list_skills("demo"))
    matches = run(store.search_skills("release hygiene", project_name="demo"))
    all_matches = run(store.search_skills("release hygiene", project_name=None))

    assert [skill.id for skill in listed] == [project_skill.id]
    assert [skill.id for skill in matches] == [project_skill.id]
    assert {skill.id for skill in all_matches} == {project_skill.id, global_skill.id}
