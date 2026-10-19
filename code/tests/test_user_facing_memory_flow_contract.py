import json
import re
from pathlib import Path

from harness_mem.integration.command_sync import render_primary_command
from harness_mem.mcp.distill_handlers import _finalize_call_contract
from harness_mem.mcp.tool_specs import _SCHEMAS


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
    assert "免编号/目录/内部命令管理" in text
    assert "knowledge_changes" in text and "unfinished_work" in text
    assert "展示实存标题/正文" in text
    assert "切换/规则不确定/错误/冲突" in text
    assert "autopilot_search_tick" in text
    assert "闲聊免查" in text
    assert "免日/批上限" in text
    assert "多场" in text and "同一 `batch_id`" in text
    assert "batch_id" in text and "inspect_sessions" in text
    assert "逐点新增/确认/替换/不写" in text
    assert "检索/人工整理免项目初始化/Hook" in text
    assert "任务项目不筛选" in text
    assert "误限取消" in text and "明确范围不扩大" in text
    assert "同主题合查" in text
    assert "禁换词/入口重查" in text
    assert "仅缺答/冲突/源变/截断补读" in text
    assert "复用未变完整源" in text
    assert "continuation" in text and 'detail="full"' in text
    assert "查看全部须读完页" in text
    assert "禁另建库" in text
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
        assert "检索/人工整理免项目初始化/Hook" in text, path
        assert "autopilot_search_tick" in text, path
        assert "闲聊免查" in text, path
        assert "continuation" in text, path
        assert 'detail="full"' in text, path
        assert "查看全部须读完页" in text, path


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


def test_manual_guides_keep_supported_known_unknowns_as_current_knowledge() -> None:
    for relative in (
        "code/plugins/harness-mem/commands/hm/hm.md",
        "code/tools/hm-distill/SKILL.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if relative.endswith("hm.md"):
            assert "明确、仍适用且影响后续选择的未定/未知/未批准" in text
            assert "按对象/范围存当前知识，非 `unfinished_work`" in text
            assert "缺信息/猜测/建议不推用户状态" in text
        else:
            assert "来源明确说明、仍适用且影响后续选择" in text, relative
            assert "“未定／未知／未批准”也是当前状态" in text, relative
            assert "保留具体对象与适用范围" in text, relative
            assert any(term in text for term in ("不加入 `unfinished_work`", "不只放进 `unfinished_work`", "状态本身不列入 `unfinished_work`")), relative
            assert "信息缺失、模型猜测或助手建议不能写成用户未定或未批准" in text, relative
        assert "动作" in text and ("交接" in text or "待办" in text), relative

    rules = (ROOT / "code/tools/hm-distill/references/distillation-rules.md").read_text(
        encoding="utf-8"
    )
    assert "explicitly undecided, unknown, or unapproved status supported by the source" in rules
    assert "named subject and\n    applicable scope as current knowledge" in rules
    assert "not only `unfinished_work` or a handoff" in rules
    assert "model guesses, or assistant recommendations do not establish user indecision" in rules
    assert "or nonapproval" in rules


def test_manual_corrections_reuse_targets_and_keep_unaffected_conditions() -> None:
    for relative in (
        "code/plugins/harness-mem/commands/hm/hm.md",
        "code/tools/hm-distill/SKILL.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "target_knowledge=[<旧条目>]" in text, relative
        if relative.endswith("hm.md"):
            assert "确认/替换整旧行数组放各点 `memory_points[i].target_knowledge`" in text
            assert "运行时唯一匹配/CAS旧正文" in text
            assert "其余条件/例外/未定" in text
            assert "免用户管项目/批同项重试" in text
        else:
            assert "旧条目原样来自搜索，由运行时确定归属" in text, relative
            assert "保留其余仍适用的条件、例外和未定状态" in text, relative
            assert "不让用户管理项目或批准同项重试" in text, relative
        assert "scope=\"project\"` 和已有来源上下文准备纠正" not in text, relative

    command = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(
        encoding="utf-8"
    )
    assert "回忆当前知识" in command
    assert "不限必要检索次数" in command
    assert "已核更正优先旧原文" in command


def test_compact_guide_uses_prepared_finalize_contract_and_source_policies() -> None:
    text = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    executable = text.split("```javascript\n", 1)[1].split("\n```", 1)[0]
    binding = re.search(r'^const n=("[^"]+"),a=(\{[^\n]+\});$', executable, re.MULTILINE)
    assert binding is not None
    assert json.loads(binding.group(1)) == "prepare_session_distill"
    # The compact example uses plain JavaScript keys, not a JSON argument wrapper.
    args = json.loads(re.sub(r'([{,])([A-Za-z_]\w*):', r'\1"\2":', binding.group(2)))
    assert 'ALL_TOOLS.filter(t=>t.name===n||t.name.endsWith("__"+n))' in executable
    assert "if(t.length!==1)text(t.map(t=>t.name));" in executable
    assert "await tools[t[0].name](a)" in executable
    assert "已知工具直调；`functions.exec` 全动作按例精确匹配并 await" in text
    assert "读取换 `search_memory`/参数" in text
    assert "禁 description/服务前缀泛查、打印全目录/schema" in text
    assert "r.isError||!r.content?.length" in executable and "text(r)" in executable
    assert 'for(const b of r.content)text(b.type==="text"?b.text:b)' in executable
    prepare_schema = _SCHEMAS["prepare_session_distill"]["input_schema"]
    assert set(args) <= set(prepare_schema["properties"])
    assert args["scope"] == "all" and args["include_current"] is True

    contract = _finalize_call_contract("source-owner", "checked-job")
    assert contract["tool"] == "finalize_session_distill" and contract["template_only"] is True
    assert "finalize_contract.instructions/required_fields/allowed_values" in text
    assert "以 tool/填好 `finalize_contract.args_template` 换上例 n/a 直调" in text
    assert "禁查/打印收尾元数据" in text
    assert "模板非事实，点/项目/job/引用实填" in text
    instructions = "\n".join(contract["instructions"])
    assert "not verified content or an automatic decision" in instructions
    assert "Replace every placeholder after checking the complete actual source" in instructions
    assert "keep only relevant durable points" in instructions
    assert "two independent points illustrate a user statement and an assistant proposal report" in instructions
    assert "Neither is required to exist" in instructions
    assert "Add/verified are example choices only" in instructions
    template = contract["args_template"]
    assert template["project_name"] == "source-owner" and template["job_id"] == "checked-job"
    schema = _SCHEMAS["finalize_session_distill"]["input_schema"]
    properties = schema["properties"]
    assert set(schema["required"]) <= set(template) <= set(properties)
    assert contract["required_fields"]["arguments"] == schema["required"]
    points = template["memory_points"]
    point_schema = properties["memory_points"]["items"]
    assert [(p["evidence_basis"], p["verification_refs"][0]["role"]) for p in points] == [
        ("user_statement", "user"), ("source_report", "assistant")]
    for point in points:
        assert set(point_schema["required"]) <= set(point) <= set(point_schema["properties"])
        assert set(point["verification_refs"][0]) == {"kind", "exchange_index", "content_sha256", "role"}
        assert point["verification_refs"][0]["kind"] == point["evidence_basis"]
        assert point["verification_outcome"] == "verified"
        assert point["assimilation_disposition"] == "add"
        assert "target_knowledge" not in point
    ref_properties = point_schema["properties"]["verification_refs"]["items"]["properties"]
    index_schema = next(option for option in ref_properties["exchange_index"]["anyOf"]
                        if option.get("type") == "integer")
    assert index_schema["minimum"] == 1 and "index>=1" in text
    review_schema = properties["semantic_review"]
    assert set(review_schema["required"]) <= set(template["semantic_review"])
    assert "session_summary" in template["semantic_review"]
    for field in ("contradictions", "unfinished_work"):
        assert review_schema["properties"][field]["type"] == "array"
        assert review_schema["properties"][field]["items"]["type"] == "string"
        assert template["semantic_review"][field] == []
    assert "矛盾/未完成为字符串数组，后者仅真实动作" in text
    summary_schema = review_schema["properties"]["session_summary"]
    assert f"{summary_schema['minLength']}–{summary_schema['maxLength']}字符" in text
    enum_schemas = point_schema["properties"] | review_schema["properties"]
    expected = {field: value["enum"] for field, value in enum_schemas.items() if "enum" in value}
    assert set(expected) == {"evidence_basis", "verification_outcome", "assimilation_disposition",
                             "last_turn_status", "evidence_status", "promotion_decision"}
    assert contract["allowed_values"] == expected
    assert contract["required_fields"]["memory_point"] == point_schema["required"]
    assert contract["required_fields"]["semantic_review"] == review_schema["required"]
    assert "旧/原始/未就绪缺合同沿原流程，无新门禁" in text
    assert "仅缺字段且合同未说明才查该工具真实 schema" in text
    assert isinstance(contract["target_knowledge_example"], list)
    assert set(contract["target_knowledge_example"][0]) == {"title", "statement", "project_name"}
    assert contract["target_knowledge_path"] == "memory_points[i].target_knowledge"
    fragment = contract["targeted_point_fragment"]
    assert set(fragment) == {"memory_points"}
    assert len(fragment["memory_points"]) == 1
    fragment_point = fragment["memory_points"][0]
    assert set(fragment_point) == {"assimilation_disposition", "target_knowledge"}
    assert fragment_point["target_knowledge"] == contract["target_knowledge_example"]
    assert "For each confirm/refine/replace point" in instructions
    assert "memory_points[i].target_knowledge, never at the top level" in instructions
    assert "Copy full old title, statement and project_name" in instructions
    assert "module only when present on the selected row" in instructions
    assert "context does not select ownership" in instructions
    assert "Merge targeted_point_fragment.memory_points[0] into the complete affected args_template.memory_points[i]" in instructions
    assert "do not replace the complete point or put the fragment wrapper inside it" in instructions
    assert "Add points omit target_knowledge" in instructions
    assert "prepare_session_distill top-level target_knowledge only prepares the existing owner/source binding" in instructions
    assert "it does not supply a finalization point's targets" in instructions
    assert "各点 `memory_points[i].target_knowledge`" in text
    assert "准备顶层 `target_knowledge` 仅绑现有 owner/source，不代各点目标，收尾顶层禁放" in text

    assert 'evidence_basis="source_report"' in text
    assert "助手具体方案独立写 `memory_points`" in text
    assert "与用户约定分开，来源无用户决定也须保存，非用户约定，仅总结不算保存" in text
    assert "保留说话人、方案/报告身份、时期/来源范围，不升为外部事实" in text
    assert "Source reports retain speaker, period and source scope" in instructions
    assert "do not establish external current truth, execution or user approval" in instructions
    assert "exchange 禁 `locator/locator_sha256/chunk_index`" in text
    assert "用户 `user_statement/user`、助手 `source_report/assistant`" in text
    assert "不猜主题/绑 owner" in text
    assert "同归属直收尾" in text and "跨项目带" in text
    assert "zero_candidate_challenge" in text and "retained_state_item" in text
    assert "约定/条件保留完整，避免同旧条竞争替换" in text
    assert "或仅因缺长期证据挂起" in text
    assert "缺用户回应只说“本次记录未给用户决定”" in text
    assert "禁断言实际未定/未采纳/拒绝/批准" in text
    assert "正文/标题/理由/总结/检索/结果逐句（含末尾概括）守此来源限定" in text
    assert "后来用户明确未定仍为当前 `user_statement`" in text
    assert "读写保留具体方法/机制及限定，禁泛化" in text
    results = text.split("## 结果与失败", 1)[1]
    assert "不写不证明完成" in results and "unfinished_work" in results
    assert "not_written" in results and "text/错误/异常/非text原样完整转交" in results
    assert "禁省失败/重包装" in results
    assert "清原文/旧记忆须用户明示" in results


def test_hook_templates_do_not_teach_manual_reinstallation() -> None:
    template_root = ROOT / "harness_mem/integration/templates"
    for name in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        text = (template_root / name).read_text(encoding="utf-8")
        assert "Reinstall via" not in text
        assert "integration install-" not in text
