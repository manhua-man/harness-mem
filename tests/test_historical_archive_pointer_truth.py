from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_historical_roadmaps_point_to_archive_paths() -> None:
    roadmap_v16 = (REPO_ROOT / "docs" / "roadmap-v16x.md").read_text(encoding="utf-8")
    roadmap_v17 = (REPO_ROOT / "docs" / "roadmap-v17x.md").read_text(encoding="utf-8")
    roadmap_v23 = (REPO_ROOT / "docs" / "roadmap-v23.md").read_text(encoding="utf-8")

    assert "openspec/changes/2026-05-19-v161-bucket-budget-and-distill-readonly/" not in roadmap_v16
    assert "openspec/changes/archive/2026-05-24-2026-05-19-v161-bucket-budget-and-distill-readonly/" in roadmap_v16

    assert "openspec/changes/v170-temporal-schema-current-history/" not in roadmap_v17
    assert "openspec/changes/v171-supersede-candidate-loop/" not in roadmap_v17
    assert "openspec/changes/v172-temporal-graph-retrieval/" not in roadmap_v17
    assert "openspec/changes/v173-verbatim-exact-evidence-search/" not in roadmap_v17
    assert "openspec/changes/archive/2026-05-24-v170-temporal-schema-current-history/" in roadmap_v17
    assert "openspec/changes/archive/2026-05-24-v173-verbatim-exact-evidence-search/" in roadmap_v17

    assert "openspec/changes/v231-metabolism-suggestion-pass/" not in roadmap_v23
    assert "openspec/changes/archive/2026-05-26-v231-metabolism-suggestion-pass/" in roadmap_v23


def test_session_distill_points_to_archive_design_and_current_metabolism_spec() -> None:
    skill = (REPO_ROOT / "tools" / "session-distill" / "SKILL.md").read_text(encoding="utf-8")

    assert "openspec/changes/v230-signals-and-replay-windows/design.md" not in skill
    assert "openspec/specs/memory-metabolism/spec.md" not in skill
    assert "openspec/changes/archive/2026-05-25-v230-signals-and-replay-windows/design.md" in skill
    assert "openspec/specs/metabolism/spec.md" in skill
