"""Deterministic semantic projections for lossless session distillation."""

from __future__ import annotations

import re
from typing import Any, Iterable

from harness_mem.transcript_chunking import sha256_text


DISTILL_SEMANTIC_CHUNK_CHARS = 32_000
DISTILL_SEMANTIC_PROJECTION = "exchange-outline-v1"
DISTILL_COMPACT_PROJECTION = "exchange-outline-v2"

_TURN_HEADING_RE = re.compile(r"(?m)^## Turn \d+ \([^\n]*\)\s*$")
_ENTRY_RE = re.compile(r"(?:\A|\n\n)(User|Assistant|Tool): ")
_EVIDENCE_ANCHOR_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+\b")
_PASSIVE_TOOL_NAMES = frozenset({"wait", "wait_agent"})
_RISK_FLAG_CODES = {
    "version_release": "V",
    "migration_storage": "M",
    "privacy_security": "P",
    "deletion": "D",
    "failure": "F",
    "conflict_stale": "C",
    "unfinished": "U",
}
_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("version_release", re.compile(r"\b(?:v?\d+\.\d+\.\d+|version|release|publish)\b|版本|发布", re.I)),
    ("migration_storage", re.compile(r"\b(?:migration|migrate|checksum|storage|rollback)\b|迁移|校验和|存储|回滚", re.I)),
    ("privacy_security", re.compile(r"\b(?:private|privacy|secret|security|vulnerab|password|credential)\w*\b|隐私|安全|密码|密钥", re.I)),
    ("deletion", re.compile(r"\b(?:delete|erase|purge|remove)\w*\b|删除|擦除|清理", re.I)),
    ("failure", re.compile(r"\b(?:fail|error|exception|timeout|corrupt|broken)\w*\b|失败|错误|异常|超时|损坏", re.I)),
    ("conflict_stale", re.compile(r"\b(?:conflict|stale|supersed|outdated)\w*\b|冲突|过期|取代", re.I)),
    ("unfinished", re.compile(r"\b(?:unfinished|blocked|blocker|todo|remaining)\b|未完成|阻塞|待办|剩余", re.I)),
)


def build_distill_semantic_outline(value: str) -> tuple[str, dict[str, Any]]:
    """Build the complete v1 user/outcome/tool exchange rendering."""

    header, exchanges, summary = _parse_exchanges(value)
    if not exchanges:
        return value, summary
    return _render_exchanges(
        header,
        exchanges,
        projection=DISTILL_SEMANTIC_PROJECTION,
        compact=False,
    ), summary


def build_distill_compact_outline(
    value: str,
    *,
    budget_tokens: int = 3000,
) -> tuple[str, dict[str, Any]]:
    """Build a bounded v2 manifest while preserving risky and final exchanges."""

    header, exchanges, summary = _parse_exchanges(value)
    target = max(256, int(budget_tokens or 3000))
    if not exchanges:
        tokens = _count_tokens(value)
        return value, {
            **summary,
            "detail_level": "full",
            "budget_tokens": target,
            "output_tokens": tokens,
            "budget_state": "full_fallback",
            "budget_reason": "parser rendering has no exchange boundaries",
        }

    # Start with generous previews, then reduce deterministically until the
    # complete indexed manifest fits. Risk flags are preserved at every tier;
    # the full exchange remains available through semantic drilldown.
    profiles = (
        (240, 320, 600, 900),
        (160, 220, 450, 650),
        (100, 140, 320, 480),
        (72, 96, 240, 360),
        (48, 64, 96, 128),
        (32, 48, 64, 96),
        (20, 28, 40, 56),
        (12, 18, 24, 36),
        (8, 12, 16, 24),
        (4, 8, 8, 12),
        (2, 4, 4, 8),
    )
    content = ""
    output_tokens = 0
    for user_limit, outcome_limit, risk_user_limit, risk_outcome_limit in profiles:
        content = _render_exchanges(
            header,
            exchanges,
            projection=DISTILL_COMPACT_PROJECTION,
            compact=True,
            user_limit=user_limit,
            outcome_limit=outcome_limit,
            risk_user_limit=risk_user_limit,
            risk_outcome_limit=risk_outcome_limit,
        )
        output_tokens = _count_tokens(content)
        if output_tokens <= target:
            break

    risk_exchange_count = sum(bool(exchange["risk_flags"]) for exchange in exchanges)
    budget_state = "within_budget" if output_tokens <= target else "expanded_for_manifest"
    budget_reason = None
    if budget_state != "within_budget":
        budget_reason = (
            "the minimum complete indexed manifest exceeds the advisory budget"
        )
    return content, {
        **summary,
        "projection": DISTILL_COMPACT_PROJECTION,
        "detail_level": "compact",
        "exchange_count": len(exchanges),
        "risk_exchange_count": risk_exchange_count,
        "budget_tokens": target,
        "output_tokens": output_tokens,
        "budget_state": budget_state,
        "budget_reason": budget_reason,
    }


def render_distill_exchange_windows(
    value: str,
    indexes: Iterable[int],
) -> list[dict[str, Any]]:
    """Return complete v1 semantic windows for selected one-based exchanges."""

    _header, exchanges, _summary = _parse_exchanges(value)
    selected = sorted({int(index) for index in indexes if int(index) >= 1})[:8]
    windows: list[dict[str, Any]] = []
    for index in selected:
        if index > len(exchanges):
            continue
        exchange = exchanges[index - 1]
        content = _render_exchange(index, exchange, compact=False)
        windows.append(
            {
                "exchange_index": index,
                "content_sha256": sha256_text(content),
                "risk_flags": list(exchange["risk_flags"]),
                "content": content,
            }
        )
    return windows


def split_distill_semantic_content(value: str) -> list[dict[str, Any]]:
    """Split derived semantic evidence without rewriting its content."""

    chunks: list[dict[str, Any]] = []
    start = 0
    index = 0
    while start < len(value):
        hard_end = min(start + DISTILL_SEMANTIC_CHUNK_CHARS, len(value))
        end = hard_end
        if hard_end < len(value):
            boundary = value.rfind("\n", start + 1, hard_end + 1)
            if boundary >= start:
                end = boundary + 1
        if end <= start:
            end = hard_end
        content = value[start:end]
        chunks.append(
            {
                "semantic_chunk_index": index,
                "char_start": start,
                "char_end": end,
                "content_sha256": sha256_text(content),
                "content": content,
            }
        )
        start = end
        index += 1
    return chunks


def _parse_exchanges(value: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    rendering = _TURN_HEADING_RE.sub("", value)
    matches = list(_ENTRY_RE.finditer(rendering))
    if not matches:
        return "", [], {
            "projection": "parser-render-v1",
            "input_message_count": 0,
            "output_exchange_count": 0,
            "duplicate_message_count": 0,
            "collapsed_assistant_message_count": 0,
            "omitted_passive_tool_count": 0,
        }

    header = rendering[: matches[0].start()].strip()
    entries: list[tuple[str, str]] = []
    duplicate_message_count = 0
    previous: tuple[str, str] | None = None
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(rendering)
        entry = (match.group(1), rendering[match.end() : end].strip())
        if not entry[1]:
            continue
        if entry == previous:
            duplicate_message_count += 1
            continue
        entries.append(entry)
        previous = entry

    exchanges: list[dict[str, Any]] = []
    current: dict[str, list[str]] = {"user": [], "assistant": [], "tools": []}
    omitted_passive_tool_count = 0

    def flush_exchange() -> None:
        nonlocal current
        if any(current.values()):
            combined = "\n".join([*current["user"], *current["assistant"]])
            exchanges.append(
                {
                    **current,
                    "risk_flags": _risk_flags(combined),
                }
            )
        current = {"user": [], "assistant": [], "tools": []}

    for role, content in entries:
        if role == "User":
            if current["user"] or current["assistant"]:
                flush_exchange()
            current["user"].append(content)
            continue
        if role == "Assistant":
            current["assistant"].append(content)
            continue
        tool_name = content.split(" ->", 1)[0].strip()
        if tool_name in _PASSIVE_TOOL_NAMES:
            omitted_passive_tool_count += 1
            continue
        if tool_name:
            current["tools"].append(tool_name)
    flush_exchange()

    return header, exchanges, {
        "projection": DISTILL_SEMANTIC_PROJECTION,
        "input_message_count": len(entries),
        "output_exchange_count": len(exchanges),
        "duplicate_message_count": duplicate_message_count,
        "collapsed_assistant_message_count": sum(
            max(0, len(exchange["assistant"]) - 1) for exchange in exchanges
        ),
        "omitted_passive_tool_count": omitted_passive_tool_count,
    }


def _render_exchanges(
    header: str,
    exchanges: list[dict[str, Any]],
    *,
    projection: str,
    compact: bool,
    user_limit: int = 0,
    outcome_limit: int = 0,
    risk_user_limit: int = 0,
    risk_outcome_limit: int = 0,
) -> str:
    lines = [header] if header else []
    lines.extend(
        [
            "",
            (
                f"Semantic projection: {projection}; "
                "assistant progress and tool arguments are omitted. "
                "Use semantic windows and raw drilldown for candidate-grade proof."
            ),
            "",
            f"Coverage: {len(exchanges)} exchange(s), all indexed.",
        ]
    )
    if compact and len(exchanges) > 1:
        lines.append("Compact labels: E=exchange; U=user; A=assistant outcome; T=tools.")
    if compact and any(exchange["risk_flags"] for exchange in exchanges):
        lines.append(
            "Signal legend: V=version/release; M=migration/storage; "
            "P=privacy/security; D=deletion; F=failure; C=conflict/stale; "
            "U=unfinished."
        )
    final_index = len(exchanges)
    for index, exchange in enumerate(exchanges, 1):
        risky = bool(exchange["risk_flags"]) or index == final_index
        limits = (
            risk_user_limit if risky else user_limit,
            risk_outcome_limit if risky else outcome_limit,
        )
        lines.extend(
            [
                "",
                _render_exchange(index, exchange, compact=compact, limits=limits),
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _render_exchange(
    index: int,
    exchange: dict[str, Any],
    *,
    compact: bool,
    limits: tuple[int, int] = (0, 0),
) -> str:
    risk_flags = list(exchange["risk_flags"])
    rendered_flags = (
        [_RISK_FLAG_CODES[flag] for flag in risk_flags] if compact else risk_flags
    )
    if compact and rendered_flags:
        suffix = f" [s={''.join(rendered_flags)}]"
    else:
        suffix = f" [signals={','.join(rendered_flags)}]" if rendered_flags else ""
    heading = f"## E{index}" if compact else f"## Exchange {index}"
    lines = [f"{heading}{suffix}"]
    if exchange["user"]:
        user = " ".join(exchange["user"])
        lines.append(
            f"U: {_preview(user, limits[0])}" if compact else f"User: {user}"
        )
    if exchange["assistant"]:
        outcome = exchange["assistant"][-1]
        lines.append(
            f"A: {_preview(outcome, limits[1])}"
            if compact
            else f"Assistant outcome: {outcome}"
        )
    if exchange["tools"]:
        counts: dict[str, int] = {}
        for tool_name in exchange["tools"]:
            counts[tool_name] = counts.get(tool_name, 0) + 1
        tools = ", ".join(
            f"{name} x{count}" if count > 1 else name
            for name, count in counts.items()
        )
        lines.append(f"T: {tools}" if compact else f"Tools: {tools}")
    return "\n".join(lines)


def _preview(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if limit <= 0 or len(normalized) <= limit:
        return normalized
    head = max(1, int(limit * 0.68))
    tail = max(1, limit - head - 1)
    preview = f"{normalized[:head].rstrip()}…{normalized[-tail:].lstrip()}"
    anchors = list(dict.fromkeys(_EVIDENCE_ANCHOR_RE.findall(normalized)))
    missing = [anchor for anchor in anchors if anchor not in preview]
    if missing:
        preview += f" [anchors: {', '.join(missing)}]"
    return preview


def _risk_flags(value: str) -> list[str]:
    return [name for name, pattern in _RISK_PATTERNS if pattern.search(value)]


def _count_tokens(value: str) -> int:
    from harness_mem.commands import token_estimator

    return token_estimator.count_tokens(value)


__all__ = [
    "DISTILL_COMPACT_PROJECTION",
    "DISTILL_SEMANTIC_CHUNK_CHARS",
    "DISTILL_SEMANTIC_PROJECTION",
    "build_distill_compact_outline",
    "build_distill_semantic_outline",
    "render_distill_exchange_windows",
    "split_distill_semantic_content",
]
