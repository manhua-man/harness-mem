"""Pure validation helpers shared by provider models and trusted runtime."""

from __future__ import annotations

import re


def validate_atomic_knowledge_statement(value: str) -> str:
    """Reject an obvious checklist of separate claims as one knowledge item."""

    normalized = " ".join(value.split())
    enumerated_clauses = [
        clause.strip()
        for clause in re.split(r"[、,，]", normalized)
        if clause.strip()
    ]
    pipeline_action_prefixes = (
        "capture ",
        "preserve ",
        "normalize ",
        "validate ",
        "publish ",
        "store ",
        "load ",
        "read ",
        "write ",
        "create ",
        "delete ",
        "抓取",
        "保存",
        "规范化",
        "校验",
        "验证",
        "发布",
        "读取",
        "组装",
        "创建",
        "删除",
    )
    if len(enumerated_clauses) >= 4 and sum(
        clause.casefold().startswith(pipeline_action_prefixes)
        for clause in enumerated_clauses
    ) >= 3:
        raise ValueError(
            "knowledge item lists too many separate steps; split it into atomic items"
        )
    if normalized.count(";") + normalized.count("；") >= 2:
        raise ValueError(
            "knowledge item chains multiple conclusions; split it into atomic items"
        )
    obligation_markers = (
        "必须",
        "应当",
        "应",
        "须",
        "must ",
        "should ",
        "required",
    )
    semicolon_clauses = [
        clause.strip()
        for clause in normalized.replace("；", ";").split(";")
        if clause.strip()
    ]
    if len(semicolon_clauses) > 1 and sum(
        any(marker in clause.casefold() for marker in obligation_markers)
        for clause in semicolon_clauses
    ) > 1:
        raise ValueError(
            "knowledge item combines independent obligations; split it into atomic items"
        )
    progression_markers = ("先", "再", "随后", "然后", "最后", "最终")
    if sum(marker in normalized for marker in progression_markers) >= 3:
        raise ValueError(
            "knowledge item describes a multi-step pipeline; split it into atomic items"
        )
    if _combines_independent_actions(normalized):
        raise ValueError(
            "knowledge item combines independent actions; split it into atomic items"
        )
    if _combines_qualification_domains(enumerated_clauses):
        raise ValueError(
            "knowledge item combines independently verifiable qualification domains; "
            "split it into atomic items"
        )
    return normalized


def _combines_independent_actions(statement: str) -> bool:
    """Detect one modal joining separately executable actions."""

    chinese_actions = (
        "声明",
        "验证",
        "校验",
        "测试",
        "保存",
        "持久化",
        "记录",
        "提供",
        "具备",
        "发布",
        "读取",
        "创建",
        "删除",
        "恢复",
        "继续",
        "重建",
    )
    chinese = re.search(r"(?:必须|应当|应该|应|须)([^。；;]+)", statement)
    if chinese is not None:
        body = chinese.group(1)
        for conjunction in ("并且", "同时", "并", "且"):
            if conjunction not in body:
                continue
            left, right = body.split(conjunction, 1)
            if any(action in left for action in chinese_actions) and any(
                action in right for action in chinese_actions
            ):
                return True

    lowered = statement.casefold()
    english = re.search(r"\b(?:must|should|required to)\b([^.;]+)", lowered)
    if english is None:
        return False
    english_actions = (
        "declare",
        "verify",
        "validate",
        "test",
        "preserve",
        "record",
        "provide",
        "publish",
        "read",
        "create",
        "delete",
        "resume",
        "reconstruct",
    )
    body = english.group(1)
    for conjunction in (" as well as ", " and "):
        if conjunction not in body:
            continue
        left, right = body.split(conjunction, 1)
        if any(action in left for action in english_actions) and any(
            action in right for action in english_actions
        ):
            return True
    return False


def _combines_qualification_domains(clauses: list[str]) -> bool:
    """Reject mixed evidence/configuration and behavioral-test checklists."""

    if len(clauses) < 4:
        return False
    evidence_markers = (
        "路径",
        "样本",
        "规则",
        "配置",
        "契约",
        "path",
        "sample",
        "fixture",
        "rule",
        "config",
        "contract",
    )
    behavior_markers = (
        "测试",
        "验证",
        "重建",
        "回放",
        "test",
        "verify",
        "validation",
        "reconstruction",
        "replay",
    )
    lowered = [clause.casefold() for clause in clauses]
    return any(
        marker in clause for clause in lowered for marker in evidence_markers
    ) and any(marker in clause for clause in lowered for marker in behavior_markers)


__all__ = ["validate_atomic_knowledge_statement"]
