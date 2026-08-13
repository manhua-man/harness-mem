from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_distill_default_summary_is_concise() -> None:
    text = (ROOT / "plugins/harness-mem/commands/hm/daily/distill.md").read_text(
        encoding="utf-8"
    )

    assert "新灌入" not in text
    assert "自动确认：" not in text
    assert "自动拒绝：" not in text
    assert "保留待定：" not in text
    assert "需要你确认：" not in text
    assert "只有用户要求审计详情时" in text
    assert "一条记忆一个可验证事实" in text
    assert "ID 只用于内部去重、审计、纠错和 undo" in text
    assert "不附加在默认记忆正文中" in text
    assert "仓库已验证 / 用户已确认" in text


def test_canonical_distill_skill_hides_internal_ids_from_readable_memory() -> None:
    skill = (ROOT / "tools/hm-distill/SKILL.md").read_text(encoding="utf-8")
    rules = (ROOT / "tools/hm-distill/references/distillation-rules.md").read_text(
        encoding="utf-8"
    )

    assert "one\nverifiable fact" in skill
    assert "formal `answer_packet`" in skill
    assert "Do not append session, job, candidate, memory, evidence, or source IDs" in skill
    assert "title + one verifiable fact + verification date/status" in rules
    assert "explicit audit views" in rules


def test_hook_templates_do_not_teach_manual_reinstallation() -> None:
    template_root = ROOT / "harness_mem/integration/templates"
    for name in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        text = (template_root / name).read_text(encoding="utf-8")
        assert "Reinstall via" not in text
        assert "integration install-" not in text
