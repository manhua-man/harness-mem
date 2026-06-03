from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docs_readme_spells_out_openspec_layout() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "设计规格在 `openspec/specs/` 和 `openspec/changes/`。" not in docs_readme
    assert "- `openspec/specs/`：当前主 spec 真值" in docs_readme
    assert "- `openspec/changes/`：仍在进行中的 active changes" in docs_readme
    assert "- `openspec/changes/archive/`：已完成 change 的归档记录" in docs_readme
