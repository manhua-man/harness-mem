from inspect import signature
from pathlib import Path

from harness_mem.core.schemas.assimilation import AgentKnowledgeReview
from harness_mem.core.schemas.session_distill import SessionSemanticReview
from harness_mem.distill import Distill
from harness_mem.mcp.distill_handlers import _finalize_call_contract


ROOT = Path(__file__).resolve().parents[2]


def test_prepared_template_calls_finish_with_one_review() -> None:
    contract = _finalize_call_contract("checked-job")
    assert contract["method"] == "finish" and contract["template_only"] is True
    instructions = "\n".join(contract["instructions"])
    for required in ("not verified content or an automatic decision", "Replace every placeholder",
                     "keep only relevant durable points", "Neither is required to exist",
                     "Add/verified are example choices only", "Runtime binds final text and source/target versions",
                     "Do not duplicate review as final_scope_judgment", "review.preserves_meaning=true",
                     "review.same_topic=true", "Source reports retain speaker, period and source scope",
                     "do not establish external current truth, execution or user approval"):
        assert required in instructions
    template = contract["args_template"]
    assert template["job_id"] == "checked-job"
    signature(Distill().finish).bind(**template)
    assert "final_scope_judgment" not in template and "final_scope_judgment" not in template["semantic_review"]
    points = template["memory_points"]
    assert [(p["evidence_basis"], p["verification_refs"][0]["role"]) for p in points] == [
        ("user_statement", "user"), ("source_report", "assistant")]
    for point in points:
        assert set(contract["required_fields"]["memory_point"]) <= set(point)
        assert set(point["verification_refs"][0]) == {"kind", "exchange_index", "content_sha256", "role"}
        assert point["verification_refs"][0]["kind"] == point["evidence_basis"]
        assert point["verification_outcome"] == "verified" and point["assimilation_disposition"] == "add"
        assert "target_knowledge" not in point
        assert set(point["review"]) == {"support", "use", "reason", "conditions", "undecided_state", "evidence"}
        binding, = point["review"]["evidence"]
        assert binding["target"] == "claim" and binding["ref"] == binding["message_index"] == 1
        assert AgentKnowledgeReview.model_validate(point["review"]).support == "supported"
    review_schema = SessionSemanticReview.model_json_schema()
    assert set(review_schema["required"]) <= set(template["semantic_review"])
    assert "session_summary" in template["semantic_review"]
    for field in ("contradictions", "unfinished_work"):
        assert review_schema["properties"][field]["type"] == "array"
        assert review_schema["properties"][field]["items"]["type"] == "string"
        assert template["semantic_review"][field] == []
    assert contract["required_fields"]["semantic_review"] == review_schema["required"]


def test_finalize_targets_stay_on_each_point_and_failures_stay_visible() -> None:
    contract = _finalize_call_contract("checked-job")
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
                     "Add points omit target_knowledge"):
        assert required in instructions


def test_hook_templates_do_not_teach_manual_reinstallation() -> None:
    template_root = ROOT / "harness_mem/integration/templates"
    for name in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        text = (template_root / name).read_text(encoding="utf-8")
        assert "Reinstall via" not in text
        assert "integration install-" not in text
