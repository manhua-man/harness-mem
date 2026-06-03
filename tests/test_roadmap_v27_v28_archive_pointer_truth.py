from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_roadmap_v27_uses_archive_paths_for_completed_changes() -> None:
    roadmap_v27 = (REPO_ROOT / "docs" / "roadmap-v27.md").read_text(encoding="utf-8")

    assert "openspec/changes/v270-cross-project-skill-library/" not in roadmap_v27
    assert "openspec/changes/v271-controlled-skill-activation/" not in roadmap_v27
    assert "openspec/changes/v272-skill-improvement-suggestions/" not in roadmap_v27
    assert "openspec/changes/archive/2026-06-02-v270-cross-project-skill-library/" in roadmap_v27
    assert "openspec/changes/archive/2026-06-02-v272-skill-improvement-suggestions/" in roadmap_v27


def test_roadmap_v28_uses_archive_paths_for_completed_changes() -> None:
    roadmap_v28 = (REPO_ROOT / "docs" / "roadmap-v28.md").read_text(encoding="utf-8")

    assert "openspec/changes/v280-session-distill-maintenance-surfaces/" not in roadmap_v28
    assert "openspec/changes/v281-knowledge-base-review-and-prune/" not in roadmap_v28
    assert "openspec/changes/v282-targeted-verification-and-reminder-surfaces/" not in roadmap_v28
    assert "openspec/changes/archive/2026-06-02-v280-session-distill-maintenance-surfaces/" in roadmap_v28
    assert "openspec/changes/archive/2026-06-02-v282-targeted-verification-and-reminder-surfaces/" in roadmap_v28
