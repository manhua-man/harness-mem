"""Local MCP surface cost observer for v3.4.0.

The observer records only local metadata about MCP tool output cost:
surface name, estimated output tokens, duration, result shape, and
drilldown hints. It deliberately does not persist raw tool arguments,
queries, file paths, or returned content.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from harness_mem.commands import token_estimator
from harness_mem.event_log import EventType, get_event_logger

_COST_EVENT_VERSION = 1
_BUDGET_POLICY_VERSION = "cost-budget-v3.4.4"
_DEFAULT_DAYS = 7
_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000

_SURFACE_FOR_TOOL: dict[str, str] = {
    "wake": "wake",
    "search_memory": "search",
    "search_raw": "search",
    "search_skills": "search",
    "timeline": "timeline",
    "temporal_query": "temporal_query",
    "trace_relations": "trace_relations",
    "file_context": "file_context",
    "prepare_session_distill": "distill",
    "dream_ledger": "dream",
    "dream_run": "dream",
    "dream_auto_tick": "dream",
    "undo_dream_item": "dream",
    "get_project_status": "status",
}

_SURFACE_THRESHOLDS: dict[str, int] = {
    "wake": 2000,
    "search": 1200,
    "timeline": 1200,
    "temporal_query": 1600,
    "trace_relations": 1600,
    "file_context": 900,
    "distill": 3000,
    "dream": 2000,
    "status": 1200,
}
_DEFAULT_THRESHOLD = 2000

_DEFAULT_SURFACE_BUDGETS: dict[str, int] = dict(_SURFACE_THRESHOLDS)

_BROAD_QUERY_WORDS = {
    "all",
    "bug",
    "bugs",
    "context",
    "everything",
    "memory",
    "notes",
    "project",
    "recent",
    "todo",
    "todos",
}


def analyze_mcp_surface_cost(
    tool_name: str,
    arguments: Mapping[str, Any],
    result: Mapping[str, Any] | Any,
    *,
    duration_ms: int,
    surface_budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return a privacy-preserving cost analysis for one MCP tool result."""
    output_text = json.dumps(result, ensure_ascii=False, default=str, sort_keys=True)
    output_tokens = token_estimator.count_tokens(output_text)
    surface = _SURFACE_FOR_TOOL.get(tool_name, tool_name)
    budgets = dict(_DEFAULT_SURFACE_BUDGETS)
    if surface_budgets:
        for key, value in surface_budgets.items():
            try:
                budgets[str(key)] = max(1, int(value))
            except (TypeError, ValueError):
                continue
    threshold = budgets.get(surface, _DEFAULT_THRESHOLD)
    high_output = output_tokens >= threshold
    result_shape = _result_shape(result)
    argument_shape = _argument_shape(arguments)
    truncation = _truncation_metadata(result, result_shape, high_output=high_output)
    hints, opportunity_kinds = _cost_hints(
        tool_name=tool_name,
        surface=surface,
        arguments=arguments,
        result_shape=result_shape,
        high_output=high_output,
    )
    return {
        "event_version": _COST_EVENT_VERSION,
        "budget_policy_version": _BUDGET_POLICY_VERSION,
        "tool_name": tool_name,
        "surface": surface,
        "duration_ms": max(0, int(duration_ms)),
        "output_tokens": output_tokens,
        "output_chars": len(output_text),
        "tokenizer": token_estimator.tokenizer_kind,
        "threshold_tokens": threshold,
        "budget_tokens": threshold,
        "high_output": high_output,
        "budget_exceeded": high_output,
        "argument_shape": argument_shape,
        "result_shape": result_shape,
        "truncation": truncation,
        "hints": hints,
        "opportunity_kinds": opportunity_kinds,
    }


def observe_mcp_surface_cost(
    *,
    data_dir: Path,
    tool_name: str,
    arguments: Mapping[str, Any],
    result: Mapping[str, Any] | Any,
    duration_ms: int,
    surface_budgets: Mapping[str, int] | None = None,
) -> None:
    """Append one local event-log row for a successful MCP surface call."""
    if tool_name == "surface_cost_report":
        return
    analysis = analyze_mcp_surface_cost(
        tool_name,
        arguments,
        result,
        duration_ms=duration_ms,
        surface_budgets=surface_budgets,
    )
    project_name = _extract_project_name(arguments, result)
    get_event_logger(data_dir).log_sync(
        EventType.MCP_SURFACE_COST,
        project_name=project_name,
        command=f"mcp.{tool_name}",
        extra=analysis,
    )


def surface_cost_report(
    data_dir: Path,
    *,
    project_name: str | None = None,
    days: int = _DEFAULT_DAYS,
    limit: int = _DEFAULT_LIMIT,
    surface_budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Read recent local MCP cost events and return an aggregate report."""
    normalized_days = max(1, int(days or _DEFAULT_DAYS))
    normalized_limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    policy = cost_budget_policy(surface_budgets)
    events = _read_cost_events(
        data_dir,
        project_name=project_name,
        days=normalized_days,
        limit=normalized_limit,
    )

    surfaces: dict[str, dict[str, Any]] = {}
    hint_counts: dict[str, int] = {}
    recent_high_output: list[dict[str, Any]] = []
    total_tokens = 0
    high_output_calls = 0

    for event in events:
        extra = event["extra"]
        surface = str(extra.get("surface") or "unknown")
        stats = surfaces.setdefault(
            surface,
            {
                "surface": surface,
                "call_count": 0,
                "total_output_tokens": 0,
                "max_output_tokens": 0,
                "avg_output_tokens": 0,
                "avg_duration_ms": 0,
                "_duration_total": 0,
                "high_output_calls": 0,
                "budget_exceeded_calls": 0,
                "tools": {},
                "result_shapes": [],
                "truncated_calls": 0,
                "last_seen": None,
            },
        )
        output_tokens = int(extra.get("output_tokens") or 0)
        duration_ms = int(extra.get("duration_ms") or 0)
        total_tokens += output_tokens
        stats["call_count"] += 1
        stats["total_output_tokens"] += output_tokens
        stats["max_output_tokens"] = max(stats["max_output_tokens"], output_tokens)
        stats["_duration_total"] += duration_ms
        stats["last_seen"] = event["timestamp"]
        result_shape = extra.get("result_shape")
        if isinstance(result_shape, dict):
            stats["result_shapes"].append(result_shape)
        tool_name = str(extra.get("tool_name") or "unknown")
        stats["tools"][tool_name] = stats["tools"].get(tool_name, 0) + 1

        if bool(extra.get("high_output")):
            high_output_calls += 1
            stats["high_output_calls"] += 1
            recent_high_output.append(_summarize_call(event))
        if bool(extra.get("budget_exceeded")):
            stats["budget_exceeded_calls"] += 1
        truncation = extra.get("truncation")
        if isinstance(truncation, dict) and truncation.get("truncated_by"):
            stats["truncated_calls"] += 1

        for hint in extra.get("opportunity_kinds") or []:
            hint_name = str(hint)
            hint_counts[hint_name] = hint_counts.get(hint_name, 0) + 1

    surface_rows = []
    for stats in surfaces.values():
        calls = max(1, int(stats["call_count"]))
        stats["avg_output_tokens"] = round(stats["total_output_tokens"] / calls, 1)
        stats["avg_duration_ms"] = round(stats["_duration_total"] / calls, 1)
        del stats["_duration_total"]
        surface_rows.append(stats)
    surface_rows.sort(key=lambda row: (-int(row["total_output_tokens"]), str(row["surface"])))
    recent_high_output.sort(key=lambda row: str(row["timestamp"]), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_policy_version": _BUDGET_POLICY_VERSION,
        "default_budgets": dict(_DEFAULT_SURFACE_BUDGETS),
        "effective_budgets": dict(policy["budgets"]),
        "project_name": project_name,
        "window_days": normalized_days,
        "event_count": len(events),
        "summary": {
            "total_calls": len(events),
            "total_output_tokens": total_tokens,
            "high_output_calls": high_output_calls,
            "surface_count": len(surface_rows),
        },
        "surfaces": surface_rows,
        "recent_high_output_calls": recent_high_output[:10],
        "top_opportunities": [
            {"kind": kind, "count": count}
            for kind, count in sorted(hint_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _read_cost_events(
    data_dir: Path,
    *,
    project_name: str | None,
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    path = Path(data_dir) / "events.log"
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != EventType.MCP_SURFACE_COST.value:
                continue
            if project_name and event.get("project_name") != project_name:
                continue
            timestamp = _parse_timestamp(event.get("timestamp"))
            if timestamp is None or timestamp < cutoff:
                continue
            extra = event.get("extra")
            if not isinstance(extra, dict):
                continue
            rows.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "project_name": event.get("project_name"),
                    "command": event.get("command"),
                    "extra": extra,
                }
            )

    rows.sort(key=lambda row: str(row["timestamp"]), reverse=True)
    return rows[:limit]


def _summarize_call(event: Mapping[str, Any]) -> dict[str, Any]:
    extra = event["extra"]
    return {
        "timestamp": event["timestamp"],
        "project_name": event.get("project_name"),
        "tool_name": extra.get("tool_name"),
        "surface": extra.get("surface"),
        "output_tokens": extra.get("output_tokens"),
        "duration_ms": extra.get("duration_ms"),
        "budget_tokens": extra.get("budget_tokens"),
        "budget_policy_version": extra.get("budget_policy_version"),
        "truncation": dict(extra.get("truncation") or {}),
        "hints": list(extra.get("hints") or []),
        "opportunity_kinds": list(extra.get("opportunity_kinds") or []),
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_project_name(arguments: Mapping[str, Any], result: Mapping[str, Any] | Any) -> str | None:
    value = arguments.get("project_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(result, Mapping):
        result_value = result.get("project_name")
        if isinstance(result_value, str) and result_value.strip():
            return result_value.strip()
    return None


def _argument_shape(arguments: Mapping[str, Any]) -> dict[str, Any]:
    shape: dict[str, Any] = {}
    query = arguments.get("query")
    if isinstance(query, str):
        shape["query_chars"] = len(query)
        shape["query_terms"] = len(_query_terms(query))
    path = arguments.get("path")
    if isinstance(path, str):
        shape["path_provided"] = bool(path.strip())
        shape["path_depth"] = len([part for part in re.split(r"[\\/]+", path) if part])
    for key in (
        "scope",
        "mode",
        "include_history",
        "include_skill_hints",
        "no_auto_ingest",
        "run_ingest",
    ):
        if key in arguments:
            value = arguments[key]
            if isinstance(value, (str, bool, int, float)) or value is None:
                shape[key] = value
    for key in (
        "limit",
        "observation_limit",
        "max_chars_per_observation",
        "skill_hint_limit",
    ):
        if key in arguments:
            try:
                shape[key] = int(arguments[key])
            except (TypeError, ValueError):
                shape[key] = "invalid"
    if "memory_type" in arguments:
        memory_type = arguments.get("memory_type")
        shape["memory_type_count"] = len(memory_type) if isinstance(memory_type, list) else 0
    return shape


def _result_shape(result: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {"result_kind": type(result).__name__}
    shape: dict[str, Any] = {}
    for key in (
        "memory_entry_count",
        "relation_fact_count",
        "observation_count",
        "count",
        "total_count",
        "item_count",
        "record_count",
        "timeline_count",
        "output_token_estimate",
    ):
        if key in result:
            shape[key] = result.get(key)
    output = result.get("output")
    if isinstance(output, str):
        shape["output_chars"] = len(output)
    source_ids = _collect_source_ids(result)
    if source_ids:
        shape["source_id_count"] = len(source_ids)
    return shape


def _truncation_metadata(
    result: Mapping[str, Any] | Any,
    result_shape: Mapping[str, Any],
    *,
    high_output: bool,
) -> dict[str, Any]:
    source_ids = _collect_source_ids(result)
    truncated_by = None
    remaining_drilldown: list[str] = []
    if isinstance(result, Mapping):
        for key in ("truncated_by", "truncatedBy"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                truncated_by = value.strip()
        if result.get("truncated") is True and truncated_by is None:
            truncated_by = "tool"
        if "next_cursor" in result or "cursor" in result:
            remaining_drilldown.append("cursor")
    if high_output and truncated_by is None:
        truncated_by = "budget_policy"
    if high_output:
        if source_ids:
            remaining_drilldown.append("source_ids")
        elif result_shape:
            remaining_drilldown.append("narrower_query")
    return {
        "truncated_by": truncated_by,
        "remaining_drilldown": _dedupe(remaining_drilldown),
        "source_id_count": len(source_ids),
        "source_ids": source_ids[:20],
    }


def _collect_source_ids(value: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if key in {"source_id", "source", "id"} and isinstance(child, str):
                    cleaned = child.strip()
                    if cleaned and len(cleaned) <= 160:
                        found.append(cleaned)
                elif key in {"source_ids", "evidence_ids"} and isinstance(child, list):
                    for item in child:
                        if isinstance(item, str) and item.strip() and len(item) <= 160:
                            found.append(item.strip())
                else:
                    walk(child)
        elif isinstance(node, list):
            for child in node[:100]:
                walk(child)

    walk(value)
    return _dedupe(found)


def cost_budget_policy(surface_budgets: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Return the effective v3.4.4 per-surface budget policy."""
    budgets = dict(_DEFAULT_SURFACE_BUDGETS)
    if surface_budgets:
        for key, value in surface_budgets.items():
            try:
                budgets[str(key)] = max(1, int(value))
            except (TypeError, ValueError):
                continue
    return {
        "policy_version": _BUDGET_POLICY_VERSION,
        "budgets": budgets,
        "advisory_only": True,
    }


def _cost_hints(
    *,
    tool_name: str,
    surface: str,
    arguments: Mapping[str, Any],
    result_shape: Mapping[str, Any],
    high_output: bool,
) -> tuple[list[str], list[str]]:
    hints: list[str] = []
    kinds: list[str] = []

    if tool_name == "search_memory" and _is_broad_search(arguments, result_shape):
        hints.append("Narrow the query or add memory_type before repeating broad search.")
        hints.append("Use timeline for chronological drilldown when the question is time-shaped.")
        kinds.extend(["narrower_query", "timeline_drilldown"])

    if surface == "wake" and high_output:
        hints.append("Follow up with narrower search or timeline drilldown.")
        kinds.extend(["narrower_query", "timeline_drilldown"])
    elif surface == "distill" and high_output:
        hints.append("Lower observation_limit or max_chars_per_observation for the next evidence packet.")
        kinds.append("smaller_distill_packet")
    elif surface == "file_context" and high_output:
        hints.append("Ask file_context for the most specific path before reading broad context.")
        kinds.append("narrower_file_context")
    elif surface in {"search", "timeline", "temporal_query"} and high_output:
        hints.append("Reduce limit or drill into source ids instead of returning another wide payload.")
        kinds.append("source_drilldown")
    elif surface == "dream" and high_output:
        hints.append("Use dream_ledger with run_id or item-level follow-up instead of full ledger output.")
        kinds.append("dream_drilldown")

    return _dedupe(hints), _dedupe(kinds)


def _is_broad_search(arguments: Mapping[str, Any], result_shape: Mapping[str, Any]) -> bool:
    query = arguments.get("query")
    if not isinstance(query, str):
        return False
    terms = _query_terms(query)
    query_lower = query.strip().lower()
    total_results = 0
    for key in ("memory_entry_count", "relation_fact_count", "observation_count", "count"):
        try:
            total_results += int(result_shape.get(key) or 0)
        except (TypeError, ValueError):
            pass
    if arguments.get("scope") == "all" and not arguments.get("memory_type"):
        return True
    return len(terms) <= 2 or query_lower in _BROAD_QUERY_WORDS or total_results >= 30


def _query_terms(query: str) -> list[str]:
    return re.findall(r"[\w-]+", query)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


__all__ = [
    "analyze_mcp_surface_cost",
    "cost_budget_policy",
    "observe_mcp_surface_cost",
    "surface_cost_report",
]
