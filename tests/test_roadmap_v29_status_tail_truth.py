from pathlib import Path


def test_roadmap_v29_header_status_tail_includes_v2940() -> None:
    roadmap_v29 = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v29.md").read_text(
        encoding="utf-8"
    )

    assert "v2.9.40 已完成。" in roadmap_v29
    assert "v2.9.39 已完成。" not in roadmap_v29
