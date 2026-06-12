from pathlib import Path

from harness_mem import __version__


def test_roadmap_status_baseline_mentions_full_v29_release_train() -> None:
    roadmap_status = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md").read_text(
        encoding="utf-8"
    )

    assert f"当前收口基线是 v{__version__}：" in roadmap_status
    assert "v1.5 baseline、v1.6 persistent vectors / bucket budget" in roadmap_status
    assert "v2.0 heuristic distill 移除、v2.1 maintenance-only CLI" in roadmap_status
    assert "v2.9.0–v2.9.61 这一整条从" in roadmap_status
    assert "truth-sync 的 release train、v3.1 Auto Dream Memory Maintenance、v3.2" in roadmap_status
    assert "v3.4.x Runtime Health / Cost Discipline / Regression Gates" in roadmap_status
    assert "v3.8 True Hybrid Retrieval Shootout contract" in roadmap_status
    assert "以及 v2.9.11 的 scheduler-trigger truth sync 都已落地。" not in roadmap_status
