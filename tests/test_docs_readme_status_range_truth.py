from pathlib import Path


def test_docs_readme_status_index_includes_v15_range() -> None:
    docs_readme = (Path(__file__).resolve().parents[1] / "docs" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "| `roadmap-status.md` | 当前 roadmap 完成情况：从 v1.5 到 v2.9 的已完成项、边界和未做项 |" in docs_readme
    assert "| `roadmap-status.md` | 当前 roadmap 完成情况：从 v1.6 到 v2.9 的已完成项、边界和未做项 |" not in docs_readme
