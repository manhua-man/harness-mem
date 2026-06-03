from pathlib import Path


def test_readme_and_agents_describe_hooks_as_opt_in_not_absent() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    assert "opt-in host hook / scheduler trigger" in readme
    assert "当前产品没有后台 daemon、IDE hook 或 turn-end 自检来自动产生“日常随手记”" not in readme
    assert "triggers.*` 默认仍是 `off`" in readme

    assert "opt-in host hook / scheduler trigger" in agents
    assert "当前实现没有后台 daemon、IDE hook 或 turn-end 自检来让 Agent 在普通编码任务中自动“随手记”" not in agents
    assert "triggers.*` 默认仍是 `off`" in agents
