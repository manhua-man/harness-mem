"""Locate source passages that warrant a question before manual assimilation."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re
from typing import Any, Iterable


_PASSAGES = re.compile(r"\r?\n|\\r\\n|\\n")
_PROSE_SENTENCE = re.compile(r"[。！？]+|\.{3}\s*(?:[*-]\s+)?|(?<=\.)\s+(?:[*-]\s+)?(?=[A-Z])")
_PATCH = re.compile(r"\*\*\* (?:Begin Patch|Add File:|Update File:)|\bapply_patch\(")
_WINDOWS_SPAWN_ERROR = re.compile(
    r"\A(?:Script failed\r?\nWall time [^\r\n]+\r?\nOutput:\s*Script error:\r?\n)?"
    r'(?P<diagnostic>execution error: Io\(Custom \{ kind: Other, error: "windows sandbox: '
    r'runner failed during SpawnChild: (?P<failure>[A-Za-z0-9_]+ failed: \d+) \([^|\r\n]+\) \| cwd=)'
)
_YIELDED_CELL = re.compile(r"\AScript running with cell ID ([A-Za-z0-9:_-]+)\r?\n")
_TOOL_CALL = re.compile(r"\btools\.(\w+)\s*\(")
_LITERAL_SHELL_OPTIONS = re.compile(r'\s*(\{(?:[^{}"\\]|"(?:\\.|[^"\\])*")*\})\s*\)')
_BARE_OPTION_KEY = re.compile(r'("(?:\\.|[^"\\])*")|([,{]\s*)([A-Za-z_]\w*)(?=\s*:)')
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


def _shell_options(call: dict[str, Any]) -> dict[str, Any] | None:
    text = call["text"]
    calls = list(_TOOL_CALL.finditer(text))
    if len(calls) != 1 or calls[0][1] != "shell_command":
        return None
    literal = _LITERAL_SHELL_OPTIONS.match(text, calls[0].end())
    if not literal:
        return None
    try:
        options = json.loads(_BARE_OPTION_KEY.sub(
            lambda match: match[1] or f'{match[2]}"{match[3]}"', literal[1],
        ))
    except ValueError:
        return None
    command = options.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    if options.get("sandbox_permissions") == "use_default":
        options.pop("sandbox_permissions")
    return options


def native_shell_launch_failures(
    records: list[dict[str, Any]],
) -> dict[int, tuple[str, str, str]]:
    """Map recognized launcher diagnostics to the original shell invocation."""
    calls = {}
    cells = {}
    failures = {}
    for record in records:
        if record["type"] in {"custom_tool_call", "function_call"}:
            calls[record["call_id"]] = record
            continue
        if record["type"] not in {"custom_tool_call_output", "function_call_output"}:
            continue
        call = calls.get(record["call_id"])
        if call is None:
            continue
        text = record["text"]
        if call["type"] == "custom_tool_call" and call.get("name") == "exec":
            yielded = _YIELDED_CELL.match(text)
            if yielded:
                cells[yielded[1]] = call
                continue
        elif (call["type"] == "function_call" and call.get("name") == "wait"
              and text.split("\n", 1)[0].rstrip("\r") in {"Script failed", "Script completed"}):
            try:
                arguments = json.loads(call["text"])
            except ValueError:
                continue
            cell_id = arguments.get("cell_id") if isinstance(arguments, dict) else None
            call = cells.pop(cell_id, None) if isinstance(cell_id, str) else None
            if call is None:
                continue
        else:
            continue
        error = _WINDOWS_SPAWN_ERROR.match(text)
        options = _shell_options(call) if error else None
        if error and options:
            # Ignore the wrapper's temporary cwd. An unknown requested cwd
            # provides no proof that two invocations were equivalent.
            workdir = options.get("workdir")
            origin = "" if isinstance(workdir, str) and workdir.strip() else call["call_id"]
            identity = json.dumps([error["failure"], options, origin], sort_keys=True)
            failures[record["native_line"]] = options["command"], identity, error["diagnostic"]
    return failures


def native_question_clauses(passage: str, kind: str) -> list[str]:
    """Compare the clauses that triggered the question, keeping its full quote."""
    pattern = next(pattern for question_kind, _, pattern in _QUESTION_PATTERNS if question_kind == kind)
    cells = passage.split("|") if is_native_table_row(passage) else [passage]
    return [clause for cell in cells for clause in _PROSE_SENTENCE.split(cell) if pattern.search(clause)]


def is_native_table_row(passage: str) -> bool:
    return passage.lstrip("+- ").startswith("|") and passage.count("|") >= 3


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
