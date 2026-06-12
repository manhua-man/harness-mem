from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_readme_is_product_facing_and_does_not_link_internal_planning() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Local-first Agentic Memory RAG Runtime" in readme
    assert "local-first memory" in readme
    assert "candidate-gated learning" in readme
    assert "[Changelog](./CHANGELOG.md)" in readme
    assert "Maintainer planning, benchmark artifacts, private test packets, and roadmap" in readme
    assert "docs/roadmap-status.md" not in readme
    assert "benchmark-suite/" not in readme
    assert "reference-projects.md" not in readme


def test_agents_points_to_release_truth_authorities() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准" in agents
    assert "各版本 roadmap 主要保留切片设计、验收口径和历史决策链，不应单独当作当前实现真值" in agents
