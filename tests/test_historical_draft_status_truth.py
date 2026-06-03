from pathlib import Path


def test_historical_draft_doc_no_longer_uses_bare_draft_status() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    dream_doc = (docs_root / "roadmap" / "dream-mechanism-absorption-v151-v17.md").read_text(
        encoding="utf-8"
    )
    docs_readme = (docs_root / "README.md").read_text(encoding="utf-8")

    assert "历史设计稿（draft archive）" in dream_doc
    assert "> 状态：draft" not in dream_doc
    assert "当前版本状态以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准。" in dream_doc
    assert "| `roadmap/` | 历史 roadmap proposal / design drafts（非当前版本承诺） |" in docs_readme
