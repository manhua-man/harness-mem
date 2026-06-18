from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v59_docs_are_planned_and_indexed() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    roadmap_v59 = (REPO_ROOT / "docs" / "roadmap-v59.md").read_text(encoding="utf-8")

    assert "roadmap-v59.md" in docs_readme
    assert "Evidence & Public Claims Train" in docs_readme
    assert "规划 v5.9-v5.12" in docs_readme
    assert "## 规划中：v5.9+ Evidence & Public Claims Train" in roadmap_status
    assert "v5.10 Broad token/cost" in roadmap_status
    assert "v5.12 Storage speedup" in roadmap_status
    assert "docs/roadmap-v59.md" in roadmap_status
    assert "broad_token_cost_saving" in roadmap_v59
    assert "broad_memory_answer_quality" in roadmap_v59
    assert "storage_v2_speedup_shootout" in roadmap_v59
    assert "B21" in roadmap_v59
    assert "cost_token_evidence" in roadmap_v59
    assert "token_cost_saving" in roadmap_v59
    assert "storage_v2_scale_evidence" in roadmap_v59
    assert "approve-with-changes" in roadmap_v59
