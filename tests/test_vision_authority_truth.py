from pathlib import Path


def test_vision_and_reference_docs_now_point_to_current_truth_sources() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    vision_doc = (docs_root / "roadmap-vision-v16-v18.md").read_text(encoding="utf-8")
    reference_doc = (docs_root / "reference-projects.md").read_text(encoding="utf-8")
    docs_readme = (docs_root / "README.md").read_text(encoding="utf-8")

    assert "历史远景文档（vision archive）" in vision_doc
    assert "当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。" in vision_doc
    assert "每个版本的落地形态会在前一版本收尾时再细化。" not in vision_doc

    assert "当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。" in reference_doc
    assert "路线图承诺仍以 `roadmap-v15x.md`、`roadmap-v16x.md` 和 `roadmap-vision-v16-v18.md` 为准。" not in reference_doc
    assert "历史路线设计" in reference_doc

    assert "| `roadmap-vision-v16-v18.md` | v1.6 - v1.8 历史远景方向，不等同于当前版本承诺路线图 |" in docs_readme
