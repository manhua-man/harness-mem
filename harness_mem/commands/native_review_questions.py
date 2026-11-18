"""Locate source passages that warrant a question before manual assimilation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re
from typing import Any, Iterable


_PASSAGES = re.compile(r"\r?\n|\\r\\n|\\n")
_PATCH = re.compile(r"\*\*\* (?:Begin Patch|Add File:|Update File:)|\bapply_patch\(")
_QUESTION_PATTERNS = (
    (
        "validation", "What does this validate, and when does it accept or reject the input?",
        re.compile(
            r"\b(?:throw\s+new|raise\s+\w*(?:Error|Exception)|return\s+Err\b|"
            r"invalid\s+\w+|must\s+(?:be|have|contain|match)|validation\s+(?:fails?|requires?)|"
            r"isfinite\(|isnan\()|\bif\s*\([^\n]{0,140}\b(?:format|version|isArray)\b"
            r"|校验(?:失败|规则|要求)|格式无效|格式不正确|必须(?:是|为|包含|匹配)|不合法",
            re.I,
        ),
    ),
    (
        "failure", "What failed or was denied, and what was kept, changed, or retried?",
        re.compile(
            r"\b(?:error:\s*\S|(?:exit|status)[_ ]code\s*[:=]?\s*[1-9]\d*|"
            r"(?:on|after) (?:a |the )?(?:failure|error)|(?:failed|unable) to\s+\w+|"
            r"access (?:is )?(?:denied|blocked)|rolled back|rollback|cannot\s+(?:open|read|write|import))"
            r"|失败(?:后|时|则)|(?:加载|读取|导入|保存|解析)失败|保留原(?:有|来的|列表|记录)"
            r"|回滚|拒绝访问|发生错误|无法(?:打开|写入|导入)",
            re.I,
        ),
    ),
    (
        "applicability", "When does this behavior apply, and what exceptions or limits change it?",
        re.compile(
            r"\b(?:only (?:when|if|after|supports?)|unless\s+\w+|"
            r"(?:end|file|value|field|argument|parameter|path|time)\s+(?:is\s+)?optional|"
            r"does not (?:modify|upload|replace|support|overwrite)|when\s+\w+\s+is\s+(?:missing|empty|disabled))"
            r"|仅(?:当|在|用于|支持)|只有.{2,50}才|(?:可以)?留空|可选(?:参数|字段)|不会(?:上传|覆盖|修改)|"
            r"不(?:会)?强制匹配|依赖于|适用条件",
            re.I,
        ),
    ),
)


def native_review_questions(
    records: list[dict[str, Any]], revision: str,
) -> Iterable[dict[str, Any]]:
    """Yield exact, revision-bound excerpts of untrusted native tool evidence."""
    calls: dict[str, dict[str, Any]] = {}
    for record in records:
        call_id = record["call_id"]
        if record["type"] in {"function_call", "custom_tool_call"}:
            calls[call_id] = record
            continue
        call = calls.get(call_id)
        if call is None:
            continue
        evidence = [("result_quote", record["text"])]
        if call.get("name", "").endswith("apply_patch") or _PATCH.search(call["text"]):
            evidence.append(("call_quote", call["text"]))
        for quote_field, text in evidence:
            passages = Counter(part.strip() for part in _PASSAGES.split(text))
            for passage in passages:
                if not 12 <= len(passage) <= 800:
                    continue
                match = next(((kind, question) for kind, question, pattern in _QUESTION_PATTERNS
                              if pattern.search(passage)), None)
                # A binding must be selectable by an exact, unambiguous quote.
                if match is None or passages[passage] != 1 or text.count(passage) != 1:
                    continue
                kind, question = match
                identity = f"{revision}\n{call_id}\n{record['native_line']}\n{quote_field}\n{passage}"
                yield {
                    "id": sha256(identity.encode()).hexdigest()[:24],
                    "kind": kind, "question": question, "quote_field": quote_field,
                    "call_id": call_id, "call_line": call["native_line"],
                    "result_line": record["native_line"], "condition": passage,
                }
