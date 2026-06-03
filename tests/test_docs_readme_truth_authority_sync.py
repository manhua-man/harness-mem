from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docs_readme_points_to_release_truth_authorities() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 [`roadmap-status.md`](./roadmap-status.md) 与" in docs_readme
    assert "`CHANGELOG.md` 为准" in docs_readme
    assert "各版本 roadmap 主要保留切片设计、验收口径和历史决策链，不单独充当当前实现真值" in docs_readme
