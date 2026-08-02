"""Deterministic semantic projections for lossless session distillation."""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping

from harness_mem.transcript_chunking import (
    TranscriptLogicalUnit,
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
)


DISTILL_SEMANTIC_CHUNK_CHARS = 32_000
DISTILL_SEMANTIC_PROJECTION = "exchange-outline-v1"
DISTILL_COMPACT_PROJECTION = "exchange-outline-v2"
DISTILL_INCREMENTAL_PROJECTION = "exchange-projection-lineage-v1"

_TURN_HEADING_RE = re.compile(r"(?m)^## Turn \d+ \([^\n]*\)\s*$")
_SEMANTIC_EXCHANGE_HEADING_RE = re.compile(r"(?m)^## E\d+\b[^\n]*$")
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
_MEMORY_SIGNAL_CODES = {
    "user_correction": "C",
    "explicit_decision": "Q",
    "successful_solution": "S",
    "rule_or_preference": "P",
    "reusable_workflow_or_fact": "R",
    "version_or_migration": "V",
    "unfinished_handoff": "U",
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
_MEMORY_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "user_correction",
        re.compile(
            r"\b(?:correction|corrected|actually|instead|rather than)\b|"
            r"更正|纠正|改为|不是.{0,40}而是",
            re.I,
        ),
    ),
    (
        "explicit_decision",
        re.compile(
            r"\b(?:we decided|decision is|chosen|approved|agreed to|standardize on)\b|"
            r"决定|最终选择|确认采用|统一(?:使用|为)",
            re.I,
        ),
    ),
    (
        "successful_solution",
        re.compile(
            r"\b(?:root cause|fixed by|resolved by|solution|workaround)\b|"
            r"根因|解决方案|已修复|通过.{0,40}修复",
            re.I,
        ),
    ),
    (
        "rule_or_preference",
        re.compile(
            r"\b(?:always|never|from now on|default(?:s)? to|prefer|policy|rule|must)\b|"
            r"以后|一律|默认|偏好|规则|必须|禁止",
            re.I,
        ),
    ),
    (
        "reusable_workflow_or_fact",
        re.compile(
            r"\b(?:workflow|procedure|runbook|invariant|architecture|reusable)\b|"
            r"流程|步骤|不变量|架构|可复用",
            re.I,
        ),
    ),
    (
        "version_or_migration",
        re.compile(
            r"\b(?:v?\d+\.\d+\.\d+|version|release|publish|migration|migrate|storage)\b|"
            r"版本|发布|迁移|存储",
            re.I,
        ),
    ),
    (
        "unfinished_handoff",
        re.compile(
            r"\b(?:unfinished|blocked|blocker|todo|remaining|next step|handoff)\b|"
            r"未完成|阻塞|待办|剩余|下一步|交接",
            re.I,
        ),
    ),
)


def build_distill_semantic_outline(value: str) -> tuple[str, dict[str, Any]]:
    """Build the complete v1 user/outcome/tool exchange rendering."""

    header, exchanges, summary = _parse_exchanges(value)
    if not exchanges:
        return value, {**summary, **_zero_candidate_challenge_manifest(exchanges)}
    return _render_exchanges(
        header,
        exchanges,
        projection=DISTILL_SEMANTIC_PROJECTION,
        compact=False,
    ), {**summary, **_zero_candidate_challenge_manifest(exchanges)}


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
            **_zero_candidate_challenge_manifest(exchanges),
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
        **_zero_candidate_challenge_manifest(exchanges),
        "projection": DISTILL_COMPACT_PROJECTION,
        "detail_level": "compact",
        "exchange_count": len(exchanges),
        "risk_exchange_count": risk_exchange_count,
        "budget_tokens": target,
        "output_tokens": output_tokens,
        "budget_state": budget_state,
        "budget_reason": budget_reason,
    }


def build_append_aware_distill_projection(
    value: str,
    *,
    source_revision: str,
    source_bytes: bytes,
    covered_sequence_count: int = 0,
    detail_level: str = "compact",
    budget_tokens: int = 3000,
    previous_projection: Mapping[str, Any] | None = None,
    previous_source_bytes: bytes | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Build a semantic projection, reusing only a cryptographically proven prefix.

    The returned lineage record is a disposable derived cache. ``source_bytes``
    remains the authority and callers must retain the transcript ledger's
    byte-exact revision proof. Incremental reuse is allowed only when the new
    native source strictly appends the previous revision, the parser rendering
    retains the previous rendering byte-for-byte, and the cached semantic state
    still reproduces its recorded projection hash.
    """

    source_digest = sha256_bytes(source_bytes)
    if source_revision != f"sha256:{source_digest}":
        raise ValueError("source revision does not match exact native source bytes")
    fallback_reason = "no_previous_projection"
    parsed: tuple[str, list[dict[str, Any]], dict[str, Any]] | None = None
    base_revision: str | None = None
    previous_projection_sha256: str | None = None
    verified_prefix_sha256: str | None = None
    appended_raw_bytes = 0
    appended_parser_chars = 0
    normalized_sequence_count = max(0, int(covered_sequence_count or 0))

    if previous_projection is not None:
        fallback_reason = "previous_source_bytes_unavailable"
        if previous_source_bytes is not None:
            parsed, fallback_reason = _reuse_append_projection(
                value,
                source_bytes=source_bytes,
                previous_projection=previous_projection,
                previous_source_bytes=previous_source_bytes,
            )
            if parsed is not None:
                boundary = dict(previous_projection.get("covered_boundary") or {})
                base_revision = str(previous_projection["source_revision"])
                previous_projection_sha256 = str(
                    previous_projection["projection_sha256"]
                )
                verified_prefix_sha256 = sha256_bytes(previous_source_bytes)
                appended_raw_bytes = len(source_bytes) - len(previous_source_bytes)
                appended_parser_chars = len(value) - int(
                    boundary.get("parser_chars") or 0
                )

    build_mode = "append" if parsed is not None else "full"
    if parsed is None:
        parsed = _parse_exchanges(value)
    header, exchanges, parse_summary = parsed
    if not exchanges and not header:
        header = value
    content, summary = _render_projection_from_parsed(
        header,
        exchanges,
        parse_summary,
        detail_level=detail_level,
        budget_tokens=budget_tokens,
    )
    full_projection = _render_exchanges(
        header,
        exchanges,
        projection=DISTILL_SEMANTIC_PROJECTION,
        compact=False,
    ) if exchanges else value
    projection_sha256 = sha256_text(full_projection)
    lineage = {
        "record_version": DISTILL_INCREMENTAL_PROJECTION,
        "source_revision": source_revision,
        "source_sha256": source_digest,
        "base_revision": base_revision,
        "build_mode": build_mode,
        "fallback_reason": None if build_mode == "append" else fallback_reason,
        "covered_boundary": {
            "raw_bytes": len(source_bytes),
            "parser_chars": len(value),
            "sequence_count": normalized_sequence_count,
        },
        "verified_prefix_sha256": verified_prefix_sha256,
        "parser_prefix_sha256": sha256_text(value),
        "previous_projection_sha256": previous_projection_sha256,
        "projection_sha256": projection_sha256,
        "output_sha256": sha256_text(content),
        "appended_raw_bytes": appended_raw_bytes,
        "appended_parser_chars": appended_parser_chars,
        "parse_state": {
            "header": header,
            "exchanges": copy.deepcopy(exchanges),
            "summary": dict(parse_summary),
        },
    }
    summary.update(
        {
            "projection_build_mode": build_mode,
            "projection_base_revision": base_revision,
            "projection_sha256": projection_sha256,
            "projection_fallback_reason": lineage["fallback_reason"],
            "covered_sequence_count": normalized_sequence_count,
        }
    )
    return content, summary, lineage


def _reuse_append_projection(
    value: str,
    *,
    source_bytes: bytes,
    previous_projection: Mapping[str, Any],
    previous_source_bytes: bytes,
) -> tuple[
    tuple[str, list[dict[str, Any]], dict[str, Any]] | None,
    str,
]:
    if previous_projection.get("record_version") != DISTILL_INCREMENTAL_PROJECTION:
        return None, "projection_version_mismatch"
    previous_revision = str(previous_projection.get("source_revision") or "")
    previous_source_digest = sha256_bytes(previous_source_bytes)
    if previous_revision != f"sha256:{previous_source_digest}":
        return None, "base_revision_hash_mismatch"
    if str(previous_projection.get("source_sha256") or "") != previous_source_digest:
        return None, "base_source_hash_mismatch"
    if len(source_bytes) <= len(previous_source_bytes) or not source_bytes.startswith(
        previous_source_bytes
    ):
        return None, "source_prefix_mismatch"

    boundary = previous_projection.get("covered_boundary")
    if not isinstance(boundary, Mapping):
        return None, "covered_boundary_missing"
    previous_parser_chars = int(boundary.get("parser_chars") or -1)
    if previous_parser_chars < 0 or previous_parser_chars > len(value):
        return None, "parser_boundary_invalid"
    parser_prefix = value[:previous_parser_chars]
    if sha256_text(parser_prefix) != previous_projection.get("parser_prefix_sha256"):
        return None, "parser_prefix_mismatch"

    state = previous_projection.get("parse_state")
    if not isinstance(state, Mapping):
        return None, "parse_state_missing"
    header = str(state.get("header") or "")
    exchanges_value = state.get("exchanges")
    summary_value = state.get("summary")
    if not isinstance(exchanges_value, list) or not isinstance(summary_value, Mapping):
        return None, "parse_state_invalid"
    exchanges = copy.deepcopy(exchanges_value)
    old_full = (
        _render_exchanges(
            header,
            exchanges,
            projection=DISTILL_SEMANTIC_PROJECTION,
            compact=False,
        )
        if exchanges
        else parser_prefix
    )
    if sha256_text(old_full) != previous_projection.get("projection_sha256"):
        return None, "projection_hash_mismatch"

    tail = value[previous_parser_chars:]
    if not tail:
        return (header, exchanges, dict(summary_value)), ""
    tail_header, tail_exchanges, tail_summary = _parse_exchanges(tail)
    if not tail_exchanges and tail.strip():
        return None, "appended_parser_tail_unparseable"
    del tail_header

    if tail_exchanges and exchanges and not tail_exchanges[0]["user"]:
        exchanges[-1] = _merge_exchanges(exchanges[-1], tail_exchanges.pop(0))
    exchanges.extend(tail_exchanges)
    combined_summary = dict(summary_value)
    for key in (
        "input_message_count",
        "duplicate_message_count",
        "collapsed_assistant_message_count",
        "omitted_passive_tool_count",
    ):
        combined_summary[key] = int(combined_summary.get(key) or 0) + int(
            tail_summary.get(key) or 0
        )
    combined_summary["projection"] = DISTILL_SEMANTIC_PROJECTION
    combined_summary["output_exchange_count"] = len(exchanges)
    return (header, exchanges, combined_summary), ""


def _merge_exchanges(
    previous: Mapping[str, Any],
    appended: Mapping[str, Any],
) -> dict[str, Any]:
    user = [*previous.get("user", []), *appended.get("user", [])]
    assistant = [
        *previous.get("assistant", []),
        *appended.get("assistant", []),
    ]
    tools = [*previous.get("tools", []), *appended.get("tools", [])]
    combined = "\n".join([*user, *assistant])
    return {
        "user": user,
        "assistant": assistant,
        "tools": tools,
        "risk_flags": _risk_flags(combined),
        "memory_signals": _memory_signals(combined),
    }


def _render_projection_from_parsed(
    header: str,
    exchanges: list[dict[str, Any]],
    parse_summary: Mapping[str, Any],
    *,
    detail_level: str,
    budget_tokens: int,
) -> tuple[str, dict[str, Any]]:
    if detail_level == "full":
        if not exchanges:
            return header, {
                **parse_summary,
                **_zero_candidate_challenge_manifest(exchanges),
                "detail_level": "full",
                "budget_tokens": max(256, int(budget_tokens or 3000)),
                "budget_state": "full_requested",
            }
        return _render_exchanges(
            header,
            exchanges,
            projection=DISTILL_SEMANTIC_PROJECTION,
            compact=False,
        ), {
            **parse_summary,
            **_zero_candidate_challenge_manifest(exchanges),
            "detail_level": "full",
            "budget_tokens": max(256, int(budget_tokens or 3000)),
            "budget_state": "full_requested",
        }

    target = max(256, int(budget_tokens or 3000))
    if not exchanges:
        tokens = _count_tokens(header)
        return header, {
            **parse_summary,
            **_zero_candidate_challenge_manifest(exchanges),
            "detail_level": "full",
            "budget_tokens": target,
            "output_tokens": tokens,
            "budget_state": "full_fallback",
            "budget_reason": "parser rendering has no exchange boundaries",
        }
    profiles = (
        (240, 320, 600, 900), (160, 220, 450, 650), (100, 140, 320, 480),
        (72, 96, 240, 360), (48, 64, 96, 128), (32, 48, 64, 96),
        (20, 28, 40, 56), (12, 18, 24, 36), (8, 12, 16, 24),
        (4, 8, 8, 12), (2, 4, 4, 8),
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
    budget_state = "within_budget" if output_tokens <= target else "expanded_for_manifest"
    return content, {
        **parse_summary,
        **_zero_candidate_challenge_manifest(exchanges),
        "projection": DISTILL_COMPACT_PROJECTION,
        "detail_level": "compact",
        "exchange_count": len(exchanges),
        "risk_exchange_count": sum(bool(item["risk_flags"]) for item in exchanges),
        "budget_tokens": target,
        "output_tokens": output_tokens,
        "budget_state": budget_state,
        "budget_reason": None if budget_state == "within_budget" else (
            "the minimum complete indexed manifest exceeds the advisory budget"
        ),
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
                "memory_signals": list(exchange["memory_signals"]),
                "content": content,
            }
        )
    return windows


def split_distill_semantic_content(value: str) -> list[dict[str, Any]]:
    """Split derived evidence at complete exchange/tool-group boundaries."""

    if not value:
        return []
    headings = list(_SEMANTIC_EXCHANGE_HEADING_RE.finditer(value))
    logical_units: list[TranscriptLogicalUnit] | None = None
    if headings:
        logical_units = []
        if headings[0].start() > 0:
            logical_units.append(
                TranscriptLogicalUnit(
                    0,
                    headings[0].start(),
                    "semantic-header",
                    "manifest-header",
                )
            )
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(value)
            logical_units.append(
                TranscriptLogicalUnit(
                    heading.start(),
                    end,
                    f"exchange-{index + 1}",
                    "tool-exchange",
                )
            )

    exact_chunks = chunk_transcript_text(
        value,
        source_id="semantic-projection",
        project_name="derived",
        client="harness-mem",
        session_id="semantic-projection",
        max_chars=DISTILL_SEMANTIC_CHUNK_CHARS,
        logical_units=logical_units,
    )
    return [
        {
            "semantic_chunk_index": chunk.chunk_index,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "content_sha256": chunk.content_sha256,
            "boundary_strategy": chunk.boundary_strategy,
            "logical_unit_ids": list(chunk.logical_unit_ids),
            "logical_unit_kinds": list(chunk.logical_unit_kinds),
            "starts_with_continuation": chunk.starts_with_continuation,
            "ends_with_continuation": chunk.ends_with_continuation,
            "content": chunk.raw_content,
        }
        for chunk in exact_chunks
    ]


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
                    "memory_signals": _memory_signals(combined),
                }
            )
        current = {"user": [], "assistant": [], "tools": []}

    for role, content in entries:
        if role == "User":
            if any(current.values()):
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
    if compact and any(exchange["memory_signals"] for exchange in exchanges):
        lines.append(
            "Memory-value legend: C=correction; Q=decision; S=solution; "
            "P=rule/preference; R=reusable workflow/fact; "
            "V=version/migration; U=unfinished/handoff."
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
    memory_signals = list(exchange["memory_signals"])
    rendered_flags = (
        [_RISK_FLAG_CODES[flag] for flag in risk_flags] if compact else risk_flags
    )
    if compact:
        suffix_parts = []
        if rendered_flags:
            suffix_parts.append(f"s={''.join(rendered_flags)}")
        if memory_signals:
            suffix_parts.append(
                "m=" + "".join(_MEMORY_SIGNAL_CODES[item] for item in memory_signals)
            )
        suffix = f" [{' '.join(suffix_parts)}]" if suffix_parts else ""
    else:
        suffix_parts = []
        if rendered_flags:
            suffix_parts.append(f"signals={','.join(rendered_flags)}")
        if memory_signals:
            suffix_parts.append(f"memory={','.join(memory_signals)}")
        suffix = f" [{'; '.join(suffix_parts)}]" if suffix_parts else ""
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


def _memory_signals(value: str) -> list[str]:
    return [
        name for name, pattern in _MEMORY_SIGNAL_PATTERNS if pattern.search(value)
    ]


def _zero_candidate_challenge_manifest(
    exchanges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select a bounded, deterministic proof set for a no-candidate verdict."""

    if not exchanges:
        return {
            "zero_candidate_challenge_version": "v1",
            "zero_candidate_required_exchange_indexes": [],
            "zero_candidate_required_exchange_reasons": {},
            "zero_candidate_review_basis": "complete_raw_checkpoint",
        }

    reasons: dict[int, set[str]] = {}
    by_signal: dict[str, list[int]] = {}
    failure_indexes: list[int] = []
    for index, exchange in enumerate(exchanges, 1):
        for signal in exchange["memory_signals"]:
            by_signal.setdefault(signal, []).append(index)
        if "failure" in exchange["risk_flags"]:
            failure_indexes.append(index)

    final_index = len(exchanges)
    reasons.setdefault(final_index, set()).add("final_exchange")
    if len(failure_indexes) >= 2:
        for index in {failure_indexes[0], failure_indexes[-1]}:
            reasons.setdefault(index, set()).add("repeated_failure")

    priority = (
        "user_correction",
        "explicit_decision",
        "successful_solution",
        "rule_or_preference",
        "reusable_workflow_or_fact",
        "version_or_migration",
        "unfinished_handoff",
    )
    for signal in priority:
        indexes = by_signal.get(signal, [])
        if indexes:
            reasons.setdefault(indexes[-1], set()).add(signal)

    selected = [final_index]
    for signal in priority:
        indexes = by_signal.get(signal, [])
        if indexes and indexes[-1] not in selected and len(selected) < 8:
            selected.append(indexes[-1])
    for index in (failure_indexes[:1] + failure_indexes[-1:]):
        if index not in selected and len(selected) < 8:
            selected.append(index)
    if len(selected) < 8:
        for index in sorted(reasons, reverse=True):
            if index not in selected:
                selected.append(index)
            if len(selected) >= 8:
                break
    selected = sorted(selected)
    return {
        "zero_candidate_challenge_version": "v1",
        "zero_candidate_required_exchange_indexes": selected,
        "zero_candidate_required_exchange_reasons": {
            str(index): sorted(reasons.get(index, {"final_exchange"}))
            for index in selected
        },
        "zero_candidate_review_basis": "semantic_exchange_refs",
    }


def _count_tokens(value: str) -> int:
    from harness_mem.commands import token_estimator

    return token_estimator.count_tokens(value)


__all__ = [
    "DISTILL_COMPACT_PROJECTION",
    "DISTILL_INCREMENTAL_PROJECTION",
    "DISTILL_SEMANTIC_CHUNK_CHARS",
    "DISTILL_SEMANTIC_PROJECTION",
    "build_append_aware_distill_projection",
    "build_distill_compact_outline",
    "build_distill_semantic_outline",
    "render_distill_exchange_windows",
    "split_distill_semantic_content",
]
