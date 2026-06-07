from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docs_readme_points_to_release_truth_authorities() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 [`roadmap-status.md`](./roadmap-status.md)" in docs_readme
    assert "公开状态页" in docs_readme
    assert "`CHANGELOG.md` 为准" in docs_readme
    assert "不单独充当当前实现真值" in docs_readme
