from pathlib import Path


def test_roadmap_status_baseline_mentions_full_v29_release_train() -> None:
    roadmap_status = (Path(__file__).resolve().parents[1] / "docs" / "roadmap-status.md").read_text(
        encoding="utf-8"
    )

    assert "v2.9.0–v2.9.27 这一整条从" in roadmap_status
    assert "maintenance / triage / truth-sync 的 release\ntrain 都已落地。" in roadmap_status
    assert "以及 v2.9.11 的 scheduler-trigger truth sync 都已落地。" not in roadmap_status
