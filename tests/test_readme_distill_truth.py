from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_distill_workflow_uses_auto_review_surface() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "-> auto_review_candidates(apply=true)" in readme
    assert "-> list_candidates" not in readme
    assert "-> auto-review / confirm / reject" not in readme
