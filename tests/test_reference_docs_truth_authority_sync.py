from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_v24_points_to_release_truth_authorities() -> None:
    cli_v24 = (REPO_ROOT / "docs" / "cli" / "v2.4.md").read_text(encoding="utf-8")

    assert "[`../roadmap-status.md`](../roadmap-status.md) and `CHANGELOG.md`" in cli_v24
    assert "does not replace" in cli_v24
    assert "current release ledger" in cli_v24


def test_error_codes_points_to_release_truth_authorities() -> None:
    error_codes = (REPO_ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")

    assert "[roadmap-status.md](./roadmap-status.md) and `CHANGELOG.md`" in error_codes
    assert "does not replace" in error_codes
    assert "current" in error_codes
    assert "release ledger" in error_codes


def test_cli_design_expert_points_to_release_truth_authorities() -> None:
    cli_design = (REPO_ROOT / "docs" / "cli-design-expert.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 [roadmap-status.md](./roadmap-status.md) 与" in cli_design
    assert "`CHANGELOG.md` 为准" in cli_design
    assert "本文聚焦 CLI 设计原则与评审口径，不单独充当当前实现真值" in cli_design
