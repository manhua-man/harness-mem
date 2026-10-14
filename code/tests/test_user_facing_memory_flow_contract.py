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
    assert "不让用户学习内部命令、填写目录或管理编号" in text
    assert "knowledge_changes" in text and "unfinished_work" in text
    assert "实际保存的标题和正文" in text
    assert "任务切换、规则不确定、报错或冲突" in text
    assert "autopilot_search_tick" in text
    assert "普通闲聊无需查" in text
    assert "不要自设每日或批次数量上限" in text
    assert "多场只用同一" in text
    assert "batch_id" in text and "inspect_sessions" in text
    assert "逐点决定新增、确认、替换或不写" in text
    assert "项目、目录和 Hook 安装都不是检索或人工整理的前提" in text
    assert "任务所属项目不等于记忆所属项目" in text
    assert "先取消误加的项目筛选" in text
    assert "一个结果可以同时回答多个问题" in text
    assert "同一事实换词重查不算核验" in text
    assert "新冲突或来源变化可以重新核对" in text
    assert "输出被截断或文件变化时才重新读取" in text
    assert "continuation" in text and 'detail="full"' in text
    assert "用户要查看全部时读完所有页" in text
    assert "不创建第二份记忆库" in text
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
        assert "项目、目录和 Hook 安装都不是检索或人工整理的前提" in text, path
        assert "autopilot_search_tick" in text, path
        assert "普通闲聊无需查" in text, path
        assert "continuation" in text, path
        assert 'detail="full"' in text, path
        assert "用户要查看全部时读完所有页" in text, path


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

    assert "每个独立知识点" in skill and "一个独立事实" in skill
    assert "日常输出不展开编号、摘要、回执和内部阶段" in skill
    assert "不猜编号" in skill
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
