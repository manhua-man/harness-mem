from pathlib import Path

from harness_mem.integration.command_sync import render_primary_command


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
    assert "不要默认展示内部任务、临时草稿、运行回执、服务名称、编号或处理阶段" in text
    assert "记住了：" in text
    assert "没记：" in text
    assert "还没完成：" in text
    assert "不补一套产品术语" in text
    assert "任务进行中也要按需要实时查当前记忆" in text
    assert "autopilot_search_tick" in text
    assert "普通聊天不查" in text
    assert "不自行增加批次、每日数量或单条长度限制" in text
    assert "处理多场会话时，不默认报会话总数" in text
    assert "会话 → 结论 → 证据" in text
    assert (
        "get_project_status(project_root=<当前工作区的绝对路径>, "
        "host_client=<当前 Agent 宿主>)"
    ) in text
    assert "跟随最新一句" in text
    assert "请在当前 Agent 或 Router 中连接 harness-mem，再重试" in text
    assert len(text.splitlines()) <= 70
    assert "budget_tokens" not in text
    assert "detail_level" not in text
    assert "evidence_mode" not in text


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
        assert "请在当前 Agent 或 Router 中连接 harness-mem，再重试" in text, path
        assert "任务进行中也要按需要实时查当前记忆" in text, path
        assert "autopilot_search_tick" in text, path
        assert "普通聊天不查" in text, path
        assert "不自行增加批次、每日数量或单条长度限制" in text, path


def test_hm_mirrors_are_rendered_from_the_plugin_command() -> None:
    source_path = ROOT / "code/plugins/harness-mem/commands/hm/hm.md"
    source = source_path.read_text(encoding="utf-8")
    raw_mirrors = (
        ROOT / ".agents/workflows/hm.md",
        ROOT / ".claude/commands/hm.md",
        ROOT / ".cursor/commands/hm.md",
        ROOT / ".opencode/commands/hm.md",
    )
    skill_mirrors = (
        ROOT / ".agents/skills/hm/SKILL.md",
        ROOT / ".grok/skills/hm/SKILL.md",
    )

    for path in raw_mirrors:
        assert path.read_text(encoding="utf-8") == source, path
    rendered_skill = render_primary_command(source_path, "codex")
    for path in skill_mirrors:
        assert path.read_text(encoding="utf-8") == rendered_skill, path


def test_canonical_distill_skill_hides_internal_ids_from_readable_memory() -> None:
    skill = (ROOT / "code/tools/hm-distill/SKILL.md").read_text(encoding="utf-8")
    rules = (ROOT / "code/tools/hm-distill/references/distillation-rules.md").read_text(
        encoding="utf-8"
    )

    assert "只把一个独立、可复用的结论写成一条清楚的事实" in skill
    assert "这些是内部数据，不要原样展示给用户" in skill
    assert "可读结果不要附加会话、任务、来源或内部编号" in skill
    assert len(skill.splitlines()) <= 80
    assert "每天 20" not in skill
    assert "每批 3" not in skill
    assert "title + one verifiable fact + verification date/status" in rules
    assert "keep, replace, or delete current memory" in rules


def test_hook_templates_do_not_teach_manual_reinstallation() -> None:
    template_root = ROOT / "harness_mem/integration/templates"
    for name in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        text = (template_root / name).read_text(encoding="utf-8")
        assert "Reinstall via" not in text
        assert "integration install-" not in text
