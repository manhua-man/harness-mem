from pathlib import Path


def test_docs_readme_status_index_includes_v15_range() -> None:
    docs_readme = (Path(__file__).resolve().parents[1] / "docs" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "roadmap-status.md" in docs_readme
    assert "公开状态页" in docs_readme
    assert "当前版本、已交付能力、non-goals" in docs_readme
    for roadmap_name in [
        "roadmap-v35.md",
        "roadmap-v36.md",
        "roadmap-v37.md",
        "roadmap-v38.md",
    ]:
        assert roadmap_name in docs_readme
