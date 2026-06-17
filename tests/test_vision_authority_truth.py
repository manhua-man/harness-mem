from pathlib import Path


def test_reference_and_history_docs_are_trimmed_to_current_use() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    reference_doc = (docs_root / "reference-projects.md").read_text(encoding="utf-8")
    docs_readme = (docs_root / "README.md").read_text(encoding="utf-8")

    assert "[`roadmap-status.md`](./roadmap-status.md)" in reference_doc
    assert "`../CHANGELOG.md`" in reference_doc
    assert "它不是 benchmark，不负责给外部项目打总分。" in reference_doc
    assert "### v4.5.0 证据分析" not in reference_doc
    assert "### 硬指标 Claim Gate" not in reference_doc
    assert "已下载项目深读" not in reference_doc
    assert "`claude-mem`" in reference_doc
    assert "`codedb-mcp`" in reference_doc
    assert "`Graphiti / Zep` / `hypatia`" in reference_doc
    assert "generated layer 不是 truth store" in reference_doc
    assert "external benchmark numbers 不是 harness-mem 分数" in reference_doc

    assert "docs/archive/" not in docs_readme
    assert "reference-projects.md" in docs_readme
    assert "roadmap-vision-v16-v18.md" not in docs_readme
