from pathlib import Path


def test_roadmap_status_matrix_has_no_historical_current_baseline_rows() -> None:
    roadmap_status = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md").read_text(
        encoding="utf-8"
    )

    assert "| v2.8.2 | 当前收口基线 |" not in roadmap_status
    assert "| v2.9.8 | 当前收口基线 |" not in roadmap_status
    assert "| v2.9.29 | 当前版本 |" in roadmap_status
