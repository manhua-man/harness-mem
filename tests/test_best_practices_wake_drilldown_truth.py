from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_best_practices_keeps_low_level_wake_reads_as_drilldown_only() -> None:
    best_practices = _text("docs/best-practices.md")

    assert "覆盖新 session 常见的 profile/rules/handoff 读取需求" in best_practices
    assert "只在用户明确要 drilldown handoff 细节或 provenance 时再读取" in best_practices
    assert "只在用户明确要审计原始规则列表或 provenance 时再读取" in best_practices
    assert "不要把这些低层读工具当成默认 wake-up 主路径" in best_practices
    assert "| | `get_task_handoffs` | 在开始新任务前，恢复上一个 Session 的断点。 |" not in best_practices
    assert "| | `get_confirmed_rules` | 检查本项目必须遵守的硬性约束。 |" not in best_practices
