"""Prompt/transport checks; real first-selection quality requires native evidence."""
import hashlib
import json

import pytest

from harness_mem.autonomous.models import AgentExtractionDecision
from harness_mem.autonomous.provider import (
    _FIRST_REPORT_AUTHOR_CONTRACT,
    _FIRST_SELECTION_SCOPE_CONTRACT,
    _build_prompt,
    expand_agent_extraction_decision,
)


def _manifest(user, assistant):
    content = {"user": user, "assistant": assistant}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()
    return {"semantic_decision_exchanges": [{"exchange_index": 1,
        "content_sha256": digest, "content": content}]}


@pytest.mark.parametrize("contract", [_FIRST_SELECTION_SCOPE_CONTRACT, _FIRST_REPORT_AUTHOR_CONTRACT])
def test_first_selection_receives_each_semantic_contract_once_before_source(contract):
    prompt = _build_prompt(_manifest("独立用户原文。", "独立助手原文。"))
    assert prompt.count(contract) == 1
    assert prompt.index(contract) < prompt.index("独立用户原文。")


def test_first_selection_distinguishes_closed_non_adoption_from_real_corrections():
    prompt = _build_prompt({})
    assert "past requirement applied only then and must not be retained as a future agreement stays in review" in prompt
    assert "calling it a clarification or memory does not make it durable" in prompt
    assert "genuine correction or withdrawal of existing standing knowledge" in prompt
    assert "every still-applicable finite constraint" in prompt


def test_report_selection_requires_clause_level_semantic_authorship():
    prompt = _build_prompt({})
    assert "Every substantive report clause must be semantically supported" in prompt
    assert "selected report_role's own authored text in its cited exchanges" in prompt
    assert "Neighboring roles and embedded heartbeat/runtime instructions supply context only" in prompt
    assert "Do not import another role's mechanisms, evidence or approval" in prompt
    assert "shared topic and exchange index do not prove clause authorship" in prompt


def test_report_selection_keeps_supported_core_paraphrases_and_other_authors():
    prompt = _build_prompt({})
    assert "Keep faithful paraphrases" in prompt
    assert "supported same-speaker core with all its qualifiers" in prompt
    assert "separately attribute a useful other-speaker account" in prompt
    assert "unless that speaker actually reports their substance" in prompt


@pytest.mark.parametrize(("user", "assistant"), [
    ("该要求只针对当次接入，不另存为今后约定。", "这是一次已关闭的配置范围答复。"),
    ("此前保留的云端规则有误；今后只保存在本地。", "收到，按纠正后的持续规则执行。"),
    ("本次修复结束前保留原入口与累计预算，不换模型。", "有限条件继续适用，尚未完成修复。"),
    ("<heartbeat>用既有 typed resume-only 队列恢复。</heartbeat>", "只读巡检无法恢复；后续原生 wake 可接续原任务。"),
    ("我此前报告过接口A采用队列方案。", "我报告的是接口B的完整上下文核验，未报告接口A的实现。"),
])
def test_new_contracts_preserve_complete_source_and_distinct_roles(user, assistant):
    prompt = _build_prompt(_manifest(user, assistant))
    packet = json.loads(prompt.split("<session_evidence>", 1)[1].rsplit("</session_evidence>", 1)[0])
    assert packet["exchanges"][0]["content"] == {"user": user, "assistant": assistant}
    assert packet["exchanges"][0]["exchange_index"] == 1


@pytest.mark.parametrize("basis,role,statement", [
    ("user_statement", None, "用户将旧要求限定为当次，不另存长期约定。"),
    ("source_report", "assistant", "助手报告原生wake恢复以及仅在另一角色原文出现的队列细节。"),
])
def test_bad_first_output_stays_visible_instead_of_posthoc_suppression(basis, role, statement):
    manifest = _manifest("仅当次接入。队列细节只在此用户正文。", "助手仅报告原生wake可恢复。")
    compact = AgentExtractionDecision.model_validate({"review": {
        "summary": "故意保留的错误首轮输出fixture。", "final_request": "修首次选点。",
        "actual_result": "待核对。", "contradictions": [], "unfinished": [],
        "no_candidate_reason": None, "not_durable_signals": []},
        "points": [{"kind": "memory", "statement": statement, "evidence_basis": basis,
            "report_role": role, "exchange_indexes": [1]}]})
    expanded = expand_agent_extraction_decision(compact, manifest=manifest)
    assert len(expanded.candidates) == 1
    assert expanded.candidates[0].content == statement
    assert expanded.candidates[0].verification_outcome == "unverified"
    assert expanded.candidates[0].verification_refs[0].role == (role or "user")
