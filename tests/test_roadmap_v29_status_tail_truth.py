from pathlib import Path

from harness_mem import __version__


def test_roadmap_v29_header_status_uses_dynamic_release_range() -> None:
    roadmap_v29 = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-v29.md").read_text(
        encoding="utf-8"
    )

    assert f"> 状态：v2.9.0–v{__version__} 已完成。" in roadmap_v29
    assert "v2.9.39 / v2.9.40 已完成。" not in roadmap_v29
    assert "/ v2.9.40 已完成。" not in roadmap_v29
