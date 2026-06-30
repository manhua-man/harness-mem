"""Runtime policy for task-aware automatic memory search.

This module decides whether an agent event is specific enough to call
``search_memory``. It is intentionally host-neutral: PI, Claude Code, Cursor,
Codex, and simple shell hooks can all map their native event names into this
one policy surface.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

SearchTrigger = str

SESSION_START_EVENTS = {
    "session_start",
    "before_agent_start",
    "start",
}
SESSION_END_EVENTS = {
    "session_end",
    "stop",
    "subagent_stop",
    "dream_end",
}
CONTEXT_EVENTS = {
    "context",
    "context_transform",
    "before_provider_request",
    "before_provider_payload",
}
TOOL_CALL_EVENTS = {
    "tool_call",
    "before_tool_call",
    "pre_tool_use",
    "pretooluse",
}
TOOL_RESULT_EVENTS = {
    "tool_result",
    "after_tool_call",
    "post_tool_use",
    "posttooluse",
    "post_tool_use_failure",
    "posttoolusefailure",
}
SAVE_POINT_EVENTS = {
    "save_point",
    "turn_end",
    "message_end",
    "prepare_next_turn",
    "prepare_next_turn",
    "after_agent",
}

_EXPLICIT_RECALL_TERMS = (
    "remember",
    "recall",
    "prior",
    "previous",
    "previously",
    "last time",
    "before",
    "history",
    "historical",
    "what did we decide",
    "what was decided",
    "上次",
    "之前",
    "以前",
    "记得",
    "历史",
    "过去",
    "说过",
)
_CONVENTION_TERMS = (
    "convention",
    "rule",
    "pattern",
    "boundary",
    "policy",
    "principle",
    "governance",
    "best practice",
    "architecture decision",
    "约定",
    "规范",
    "规则",
    "边界",
    "原则",
    "惯例",
    "治理",
    "怎么做",
)
_UNCERTAINTY_TERMS = (
    "not sure",
    "unsure",
    "unclear",
    "maybe",
    "probably",
    "assume",
    "guess",
    "不确定",
    "不清楚",
    "可能",
    "也许",
    "猜",
    "应该",
)
_CONFLICT_TERMS = (
    "conflict",
    "contradict",
    "contradiction",
    "inconsistent",
    "mismatch",
    "supersede",
    "changed",
    "replaced",
    "versus",
    " vs ",
    "不一致",
    "冲突",
    "矛盾",
    "推翻",
    "替换",
    "变更",
)
_FAILURE_TERMS = (
    "traceback",
    "error",
    "failed",
    "failure",
    "exception",
    "timeout",
    "not found",
    "cannot",
    "permission denied",
    "exit code",
    "报错",
    "失败",
    "异常",
    "找不到",
    "超时",
)
_LONG_HORIZON_TERMS = (
    "refactor",
    "migration",
    "release",
    "roadmap",
    "cross-module",
    "architecture",
    "upgrade",
    "integration",
    "handoff",
    "重构",
    "迁移",
    "发布",
    "路线图",
    "跨模块",
    "升级",
    "架构",
)
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s,;]+|(?:[\w.-]+/)+[\w.-]+")


@dataclass(frozen=True)
class AutopilotSearchDecision:
    event_name: str
    should_search: bool
    trigger: SearchTrigger | None
    query: str | None
    reason: str
    search_surface: str = "search_memory"
    include_history: bool = False
    deep_recall: bool = False
    include_provisional: bool = False
    budget_tokens: int = 1600
    injection_target: str = "next_context"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_name": self.event_name,
            "should_search": self.should_search,
            "trigger": self.trigger,
            "query": self.query,
            "reason": self.reason,
            "search_surface": self.search_surface,
            "include_history": self.include_history,
            "deep_recall": self.deep_recall,
            "include_provisional": self.include_provisional,
            "budget_tokens": self.budget_tokens,
            "injection_target": self.injection_target,
            "confidence": self.confidence,
        }


def plan_autopilot_search(
    *,
    event_name: str,
    current_task: str | None = None,
    user_prompt: str | None = None,
    messages: list[Any] | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_result: Any = None,
    is_error: bool = False,
    candidate_claims: list[str] | None = None,
    changed_files: list[str] | None = None,
    recent_queries: list[str] | None = None,
    include_provisional: bool = False,
    budget_tokens: int = 1600,
) -> AutopilotSearchDecision:
    """Return the search decision for one host/agent runtime event."""

    normalized_event = _normalize_event(event_name)
    task_text = _compact_text(current_task or user_prompt or "")
    event_text = _event_text(
        current_task=current_task,
        user_prompt=user_prompt,
        messages=messages,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_result=tool_result,
        candidate_claims=candidate_claims,
        changed_files=changed_files,
    )

    if normalized_event in SESSION_START_EVENTS:
        return _skip(normalized_event, "session_start uses wake; no task-specific uncertainty yet")
    if normalized_event in SESSION_END_EVENTS:
        return _skip(normalized_event, "session_end uses distill/dream maintenance, not search")

    claims = [claim.strip() for claim in candidate_claims or [] if claim and claim.strip()]
    if normalized_event in SAVE_POINT_EVENTS and claims:
        query = _build_query("ground durable claim", task_text, " ".join(claims[:3]))
        return _dedupe_or_search(
            normalized_event,
            trigger="prewrite_claim_grounding",
            query=query,
            reason="candidate durable truth needs evidence before automatic admission",
            include_history=True,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=0.9,
            recent_queries=recent_queries,
        )

    if normalized_event in TOOL_RESULT_EVENTS and (is_error or _has_any(event_text, _FAILURE_TERMS)):
        query = _build_query(
            "prior fix for tool failure",
            task_text,
            tool_name or "",
            _summarize(tool_result),
            " ".join(changed_files or []),
        )
        return _dedupe_or_search(
            normalized_event,
            trigger="tool_failure",
            query=query,
            reason="tool result failed or looked flaky; prior fixes may exist",
            include_history=True,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=0.85,
            recent_queries=recent_queries,
        )

    if _has_any(event_text, _CONFLICT_TERMS):
        query = _build_query("resolve conflict with prior decision", task_text, event_text)
        return _dedupe_or_search(
            normalized_event,
            trigger="conflict_or_contradiction",
            query=query,
            reason="current evidence appears to conflict with a prior or historical claim",
            include_history=True,
            deep_recall=True,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=0.8,
            recent_queries=recent_queries,
        )

    if normalized_event in CONTEXT_EVENTS | SAVE_POINT_EVENTS and _has_any(event_text, _EXPLICIT_RECALL_TERMS):
        query = _build_query("explicit recall", task_text or event_text)
        return _dedupe_or_search(
            normalized_event,
            trigger="explicit_recall_request",
            query=query,
            reason="user or agent explicitly asked for previous memory/history",
            include_history=True,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=0.85,
            recent_queries=recent_queries,
        )

    convention_signal = _has_any(event_text, _CONVENTION_TERMS)
    uncertainty_signal = _has_any(event_text, _UNCERTAINTY_TERMS)
    if normalized_event in CONTEXT_EVENTS | TOOL_CALL_EVENTS and convention_signal:
        query = _build_query(
            "project convention rule boundary",
            task_text,
            _paths_or_files(event_text, changed_files),
        )
        confidence = 0.78 if uncertainty_signal else 0.68
        return _dedupe_or_search(
            normalized_event,
            trigger="project_convention_uncertainty",
            query=query,
            reason="task touches project conventions, rules, or boundaries",
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=confidence,
            recent_queries=recent_queries,
        )

    if normalized_event in CONTEXT_EVENTS | SAVE_POINT_EVENTS and _has_any(event_text, _LONG_HORIZON_TERMS):
        query = _build_query("long horizon task switch", task_text, _paths_or_files(event_text, changed_files))
        return _dedupe_or_search(
            normalized_event,
            trigger="long_horizon_task_switch",
            query=query,
            reason="task appears to cross release/module/architecture boundaries",
            include_history=True,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=0.7,
            recent_queries=recent_queries,
        )

    return _skip(normalized_event, "no concrete memory-backed uncertainty was detected")


def _normalize_event(event_name: str) -> str:
    value = (event_name or "").strip().replace("-", "_").lower()
    aliases = {
        "sessionstart": "session_start",
        "sessionend": "session_end",
        "beforeagentstart": "before_agent_start",
        "contexttransform": "context_transform",
        "beforeproviderrequest": "before_provider_request",
        "beforeproviderpayload": "before_provider_payload",
        "beforetoolcall": "before_tool_call",
        "aftertoolcall": "after_tool_call",
        "toolcall": "tool_call",
        "toolresult": "tool_result",
        "turnend": "turn_end",
        "messageend": "message_end",
        "afteragent": "after_agent",
        "pretooluse": "pretooluse",
        "posttooluse": "posttooluse",
        "post_tool_use_failure": "post_tool_use_failure",
        "posttoolusefailure": "posttoolusefailure",
        "prepare_next_turn": "prepare_next_turn",
        "preparenextturn": "prepare_next_turn",
        "pre_tool_use": "pre_tool_use",
        "post_tool_use": "post_tool_use",
    }
    return aliases.get(value, value)


def _skip(event_name: str, reason: str) -> AutopilotSearchDecision:
    return AutopilotSearchDecision(
        event_name=event_name,
        should_search=False,
        trigger=None,
        query=None,
        reason=reason,
        confidence=0.0,
    )


def _dedupe_or_search(
    event_name: str,
    *,
    trigger: SearchTrigger,
    query: str,
    reason: str,
    include_history: bool = False,
    deep_recall: bool = False,
    include_provisional: bool = False,
    budget_tokens: int = 1600,
    confidence: float,
    recent_queries: list[str] | None,
) -> AutopilotSearchDecision:
    query = _compact_text(query, max_chars=320)
    if not query:
        return _skip(event_name, "trigger matched but no bounded query could be built")
    normalized_query = _query_key(query)
    recent = {_query_key(item) for item in recent_queries or [] if item}
    if normalized_query in recent:
        return AutopilotSearchDecision(
            event_name=event_name,
            should_search=False,
            trigger=trigger,
            query=query,
            reason="duplicate_recent_search",
            include_history=include_history,
            deep_recall=deep_recall,
            include_provisional=include_provisional,
            budget_tokens=budget_tokens,
            confidence=confidence,
        )
    return AutopilotSearchDecision(
        event_name=event_name,
        should_search=True,
        trigger=trigger,
        query=query,
        reason=reason,
        include_history=include_history,
        deep_recall=deep_recall,
        include_provisional=include_provisional,
        budget_tokens=budget_tokens,
        confidence=confidence,
    )


def _event_text(
    *,
    current_task: str | None,
    user_prompt: str | None,
    messages: list[Any] | None,
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    tool_result: Any,
    candidate_claims: list[str] | None,
    changed_files: list[str] | None,
) -> str:
    parts: list[str] = []
    for value in (current_task, user_prompt, tool_name):
        if value:
            parts.append(str(value))
    for message in messages or []:
        parts.append(_message_text(message))
    if tool_input:
        parts.append(_flatten_value(tool_input))
    if tool_result is not None:
        parts.append(_summarize(tool_result, max_chars=700))
    parts.extend(candidate_claims or [])
    parts.extend(changed_files or [])
    return _compact_text(" ".join(parts), max_chars=1600)


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(_message_text(part) for part in content)
        text = message.get("text")
        if isinstance(text, str):
            return text
    return _flatten_value(message)


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_value(val)}" for key, val in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_value(item) for item in value)
    return str(value)


def _summarize(value: Any, *, max_chars: int = 360) -> str:
    return _compact_text(_flatten_value(value), max_chars=max_chars)


def _compact_text(text: str, *, max_chars: int = 500) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = f" {text.lower()} "
    return any(term in lowered for term in terms)


def _build_query(*parts: str) -> str:
    return _compact_text(" ".join(part for part in parts if part), max_chars=320)


def _paths_or_files(text: str, changed_files: list[str] | None) -> str:
    paths = list(changed_files or [])
    paths.extend(_PATH_RE.findall(text))
    deduped: list[str] = []
    for path in paths:
        if path and path not in deduped:
            deduped.append(path)
    return " ".join(deduped[:6])


def _query_key(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


__all__ = [
    "AutopilotSearchDecision",
    "plan_autopilot_search",
]
