from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_hm_default_summary_is_concise() -> None:
    text = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(
        encoding="utf-8"
    )

    assert "新灌入" not in text
    assert "自动确认：" not in text
    assert "自动拒绝：" not in text
    assert "保留待定：" not in text
    assert "需要你确认：" not in text
    assert "不要默认展示 job、candidate、receipt、provider、内部 ID" in text
    assert "记住了：" in text
    assert "没记：" in text
    assert "还没完成：" in text
    assert "不补一套产品术语" in text
    assert (
        "get_project_status(project_root=<当前工作区的绝对路径>, "
        'host_client=<当前 Agent 宿主>, detail_level="compact")'
    ) in text
    assert "跟随最新一句" in text
    assert "连接 `harness-mem-mcp`，新开一个任务后重试" in text


def test_all_hm_mirrors_keep_the_same_daily_contract() -> None:
    paths = (
        ROOT / ".agents/skills/hm/SKILL.md",
        ROOT / ".agents/workflows/hm.md",
        ROOT / ".claude/commands/hm.md",
        ROOT / ".cursor/commands/hm.md",
        ROOT / ".grok/skills/hm/SKILL.md",
        ROOT / ".opencode/commands/hm.md",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "project_root=<当前工作区的绝对路径>" in text, path
        assert "host_client=<当前 Agent 宿主>" in text, path
        assert "跟随最新一句" in text, path
        assert "连接 `harness-mem-mcp`" in text, path


def test_canonical_distill_skill_hides_internal_ids_from_readable_memory() -> None:
    skill = (ROOT / "code/tools/hm-distill/SKILL.md").read_text(encoding="utf-8")
    rules = (ROOT / "code/tools/hm-distill/references/distillation-rules.md").read_text(
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
