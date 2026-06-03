from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_readme_spells_out_openspec_layout() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "- `openspec/`: 变更提案和 spec 资产" not in readme
    assert "- `openspec/specs/`: 当前主 spec 真值" in readme
    assert "- `openspec/changes/`: 仍在进行中的 active changes" in readme
    assert "- `openspec/changes/archive/`: 已完成 change 的归档记录" in readme


def test_agents_table_spells_out_openspec_layout() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "| `openspec/` | 规格与变更记录；能力边界或行为变化应记录在这里。 | 设计真值 |" not in agents
    assert "| `openspec/specs/` | 当前主 spec 真值；稳定能力边界和已并入主线的行为定义。 | 设计真值 |" in agents
    assert "| `openspec/changes/` | 仍在进行中的 active changes；只有变更提案尚未归档时才会出现在这里。 | 进行中变更 |" in agents
    assert "| `openspec/changes/archive/` | 已完成 change 的归档记录；历史 proposal / tasks / writeback 留存在这里。 | 历史记录 |" in agents
