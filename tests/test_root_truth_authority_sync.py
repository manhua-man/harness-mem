from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_readme_points_to_release_truth_authorities() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "当前发版状态与已落地边界以 [docs/roadmap-status.md](./docs/roadmap-status.md) 和" in readme
    assert "[CHANGELOG.md](./CHANGELOG.md) 为准" in readme
    assert "各版本 roadmap 更多是切片设计与历史决策链，不应单独当作当前实现真值" in readme


def test_agents_points_to_release_truth_authorities() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准" in agents
    assert "各版本 roadmap 主要保留切片设计、验收口径和历史决策链，不应单独当作当前实现真值" in agents
