from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_roadmap_v29_uses_archive_paths_for_completed_early_v29_slices() -> None:
    roadmap_v29 = (REPO_ROOT / "docs" / "roadmap-v29.md").read_text(encoding="utf-8")

    assert "openspec/changes/v290-prd-sync-candidate-surface/" not in roadmap_v29
    assert "openspec/changes/v291-status-triage-surface/" not in roadmap_v29
    assert "openspec/changes/v292-plugin-doctor-helper-integrity/" not in roadmap_v29
    assert "openspec/changes/v293-cli-maintenance-surface-truth/" not in roadmap_v29
    assert "openspec/changes/v294-stale-cli-surface-guard-sync/" not in roadmap_v29
    assert "openspec/changes/v295-shell-completion-maintenance-truth/" not in roadmap_v29
    assert "openspec/changes/v296-maintenance-surface-collateral-sync/" not in roadmap_v29
    assert "openspec/changes/v297-maintenance-surface-readme-and-telemetry-sync/" not in roadmap_v29
    assert "openspec/changes/v298-maintenance-surface-collateral-guard/" not in roadmap_v29
    assert "openspec/changes/v299-reflection-project-root-resolution/" not in roadmap_v29
    assert "openspec/changes/v2910-worker-mode-truth-sync/" not in roadmap_v29
    assert "openspec/changes/v2911-scheduler-trigger-truth-sync/" not in roadmap_v29
    assert "openspec/changes/v2912-distill-mode-truth-sync/" not in roadmap_v29
    assert "openspec/changes/archive/2026-06-02-v290-prd-sync-candidate-surface/" in roadmap_v29
    assert "openspec/changes/archive/2026-06-03-v2912-distill-mode-truth-sync/" in roadmap_v29
