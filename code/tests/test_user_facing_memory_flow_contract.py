import json
import re
from pathlib import Path

from harness_mem.core.schemas.assimilation import AgentKnowledgeReview
from harness_mem.integration.command_sync import render_primary_command
from harness_mem.mcp.distill_handlers import _finalize_call_contract
from harness_mem.mcp.tool_specs import _SCHEMAS


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "code/plugins/harness-mem/commands/hm/hm.md"
SKILL = ROOT / "code/tools/hm-distill/SKILL.md"


def test_hm_default_summary_is_concise() -> None:
    text = COMMAND.read_text(encoding="utf-8")
    for path in (COMMAND, SKILL):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 80, path
    for forbidden in ("新灌入", "自动确认：", "自动拒绝：", "保留待定：", "需要你确认：",
                      "budget_tokens", "detail_level", "evidence_mode"):
        assert forbidden not in text
    for required in ("不要求用户管理编号", "不自设每日／批次数量上限", "同一 `batch_id`",
                     "knowledge_changes", "unfinished_work", "实际标题、正文", "不另建库"):
        assert required in text


def test_fixed_command_actions_keep_scope_and_authorization() -> None:
    text = COMMAND.read_text(encoding="utf-8")
    for command in ("help", "status [--project <名称>]", "distill --project <名称>",
                    "distill --all", "--archived-only", "--cleanup", "clean [--project <名称>] [--apply]",
                    'search "<主题>" [--project-only <名称>]', 'review ["<标题或主题>"]',
                    "review --replace", "--with", "review --delete", "pause [--project", "continue [--project"):
        assert command in text
    for boundary in ("不调用工具", "裸 `distill` 只提示选择范围", "不猜测执行", "默认仅预览",
                     "只有 `--project-only` 才筛选项目", "不自动安装", "同范围授权", "共享库不得整库删除",
                     "来源／revision 错误保持停止", "用户明确继续才 `continue_batch=true`"):
        assert boundary in text
    assert "cleanup_processed=true" in text and "apply_cleanup=true" in text


def test_hm_mirrors_are_rendered_from_the_plugin_command() -> None:
    source = COMMAND.read_text(encoding="utf-8")
    raw_mirrors = (".agents/workflows/hm.md", ".claude/commands/hm.md",
                   ".cursor/commands/hm.md", ".opencode/commands/hm.md")
    for relative in raw_mirrors:
        assert (ROOT / relative).read_text(encoding="utf-8") == source, relative
    rendered = render_primary_command(COMMAND, "codex")
    for relative in (".agents/skills/hm/SKILL.md", ".grok/skills/hm/SKILL.md"):
        assert (ROOT / relative).read_text(encoding="utf-8") == rendered, relative


def test_reading_reuses_full_content_without_implicit_project_filter() -> None:
    text = COMMAND.read_text(encoding="utf-8")
    for required in ('scope="all"', "任务项目不筛选", "误限取消", "明确范围不扩大",
                     "不限必要检索次数", "只在缺答、冲突、源变或截断时补查", "完整 `statement`",
                     'detail="auto"', 'detail="full"', "continuation.arguments", "reuse_arguments",
                     "查看全部须读完页", "不借用其他聊天上下文", "autopilot_search_tick", "闲聊免查"):
        assert required in text
    assert "readback_verified=true" in text
    assert "缺标记、结果缺失或新冲突才补查" in text


def test_manual_guides_preserve_conditions_and_source_authority() -> None:
    for path in (COMMAND, SKILL):
        text = path.read_text(encoding="utf-8")
        for required in ("条件", "例外", "失败原因", "后续纠正", "当前代码", "同义", "未定／未知／未批准",
                         "unfinished_work", "真实动作", "source_report", "说话人", "时期", "来源范围",
                         "用户批准", "不猜编号", "target_knowledge=[<旧条目>]", "memory_points[i].target_knowledge",
                         "preserves_meaning=true", "same_topic=true", "不让用户管理项目或批准同项重试"):
            assert required in text, (path, required)
        assert "不强制入库" in text or "不强迫每条助手回答入库" in text
        assert "收尾顶层不放目标" in text
        assert "分段证明、hash" in text
        assert "不与旧 `final_scope_judgment` 混用" in text or "不与 `memory_points[i].review` 混用" in text
        assert "旧证明" not in text and "scope_segments" not in text
    skill = SKILL.read_text(encoding="utf-8")
    assert "每个独立知识点" in skill and "一个独立事实" in skill
    assert "日常输出不展开编号、摘要、回执和内部阶段" in skill
    assert "状态本身不列入 `unfinished_work`" in skill
    assert "信息缺失、模型猜测或助手建议不能写成用户未定或未批准" in skill
    rules = (ROOT / "code/tools/hm-distill/references/distillation-rules.md").read_text(encoding="utf-8")
    assert "title + one verifiable fact + verification date/status" in rules
    assert "keep, replace, or delete current memory" in rules
    assert "explicitly undecided, unknown, or unapproved status supported by the source" in rules
    assert "not only `unfinished_work` or a handoff" in rules


def test_compact_guide_calls_only_the_exact_public_tool() -> None:
    text = COMMAND.read_text(encoding="utf-8")
    executable = text.split("```javascript\n", 1)[1].split("\n```", 1)[0]
    binding = re.search(r'^const n=("[^"]+"),a=(\{[^\n]+\});$', executable, re.MULTILINE)
    assert binding is not None
    name = json.loads(binding.group(1))
    args = json.loads(re.sub(r'([{,])([A-Za-z_]\w*):', r'\1"\2":', binding.group(2)))
    assert name == "search_memory"
    assert set(args) <= set(_SCHEMAS[name]["input_schema"]["properties"])
    assert args["scope"] == "all"
    assert 'ALL_TOOLS.filter(t=>t.name===n||t.name.endsWith("__"+n))' in executable
    assert "if(t.length!==1)text(t.map(t=>t.name));" in executable
    assert "await tools[t[0].name](a)" in executable
    assert "r.isError||!r.content?.length" in executable and "text(r)" in executable
    assert 'for(const b of r.content)text(b.type==="text"?b.text:b)' in executable


def test_prepared_finalize_template_matches_public_schema_and_one_review() -> None:
    contract = _finalize_call_contract("source-owner", "checked-job")
    assert contract["tool"] == "finalize_session_distill" and contract["template_only"] is True
    text = COMMAND.read_text(encoding="utf-8")
    assert "finalize_contract.instructions/required_fields/allowed_values" in text
    assert "模板不是事实" in text
    instructions = "\n".join(contract["instructions"])
    for required in ("not verified content or an automatic decision", "Replace every placeholder",
                     "keep only relevant durable points", "Neither is required to exist",
                     "Add/verified are example choices only", "Runtime binds final text and source/target versions",
                     "Do not duplicate review as final_scope_judgment", "review.preserves_meaning=true",
                     "review.same_topic=true", "Source reports retain speaker, period and source scope",
                     "do not establish external current truth, execution or user approval"):
        assert required in instructions
    template = contract["args_template"]
    assert template["project_name"] == "source-owner" and template["job_id"] == "checked-job"
    schema = _SCHEMAS["finalize_session_distill"]["input_schema"]
    properties = schema["properties"]
    assert set(schema["required"]) <= set(template) <= set(properties)
    assert contract["required_fields"]["arguments"] == schema["required"]
    assert "final_scope_judgment" not in template and "final_scope_judgment" not in template["semantic_review"]
    points = template["memory_points"]
    point_schema = properties["memory_points"]["items"]
    assert [(p["evidence_basis"], p["verification_refs"][0]["role"]) for p in points] == [
        ("user_statement", "user"), ("source_report", "assistant")]
    for point in points:
        assert set(point_schema["required"]) <= set(point) <= set(point_schema["properties"])
        assert set(point["verification_refs"][0]) == {"kind", "exchange_index", "content_sha256", "role"}
        assert point["verification_refs"][0]["kind"] == point["evidence_basis"]
        assert point["verification_outcome"] == "verified" and point["assimilation_disposition"] == "add"
        assert "target_knowledge" not in point
        assert set(point["review"]) == {"support", "use", "reason", "conditions", "undecided_state", "evidence"}
        binding, = point["review"]["evidence"]
        assert binding["target"] == "claim" and binding["ref"] == binding["message_index"] == 1
        assert AgentKnowledgeReview.model_validate(point["review"]).support == "supported"
    ref_properties = point_schema["properties"]["verification_refs"]["items"]["properties"]
    index_schema = next(option for option in ref_properties["exchange_index"]["anyOf"]
                        if option.get("type") == "integer")
    assert index_schema["minimum"] == 1 and "exchange_index>=1" in text
    review_schema = properties["semantic_review"]
    assert set(review_schema["required"]) <= set(template["semantic_review"])
    assert "session_summary" in template["semantic_review"]
    for field in ("contradictions", "unfinished_work"):
        assert review_schema["properties"][field]["type"] == "array"
        assert review_schema["properties"][field]["items"]["type"] == "string"
        assert template["semantic_review"][field] == []
    enum_schemas = point_schema["properties"] | review_schema["properties"]
    expected = {field: value["enum"] for field, value in enum_schemas.items() if "enum" in value}
    assert contract["allowed_values"] == expected
    assert contract["required_fields"]["memory_point"] == point_schema["required"]
    assert contract["required_fields"]["semantic_review"] == review_schema["required"]


def test_finalize_targets_stay_on_each_point_and_failures_stay_visible() -> None:
    contract = _finalize_call_contract("source-owner", "checked-job")
    assert isinstance(contract["target_knowledge_example"], list)
    assert set(contract["target_knowledge_example"][0]) == {"title", "statement", "project_name"}
    assert contract["target_knowledge_path"] == "memory_points[i].target_knowledge"
    fragment = contract["targeted_point_fragment"]
    assert set(fragment) == {"memory_points"} and len(fragment["memory_points"]) == 1
    point = fragment["memory_points"][0]
    assert set(point) == {"assimilation_disposition", "target_knowledge"}
    assert point["target_knowledge"] == contract["target_knowledge_example"]
    instructions = "\n".join(contract["instructions"])
    for required in ("For each confirm/refine/replace point", "memory_points[i].target_knowledge, never at the top level",
                     "Copy full old title, statement and project_name", "module only when present",
                     "context does not select ownership", "do not replace the complete point",
                     "Add points omit target_knowledge", "it does not supply a finalization point's targets"):
        assert required in instructions
    results = COMMAND.read_text(encoding="utf-8").split("## 结果与失败", 1)[1]
    for required in ("不写不证明完成", "unfinished_work", "not_written", "异常和非 text 结果完整保留",
                     "不隐瞒失败或重包装为成功", "删除旧记忆须用户明确授权"):
        assert required in results


def test_hook_templates_do_not_teach_manual_reinstallation() -> None:
    template_root = ROOT / "harness_mem/integration/templates"
    for name in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        text = (template_root / name).read_text(encoding="utf-8")
        assert "Reinstall via" not in text
        assert "integration install-" not in text
