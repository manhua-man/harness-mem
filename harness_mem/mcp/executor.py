"""MCP tool execution policy for harness-mem."""

from __future__ import annotations

import inspect
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from harness_mem.mcp.tool_registry import (
    McpToolProfile,
    resolve_mcp_surface,
    visible_tool_name_set,
)
from harness_mem.mcp.tool_specs import ToolSpec
from harness_mem.runtime_cost import observe_mcp_surface_cost

CostBudgetResolver = Callable[[str | None], dict[str, int] | None]
DataDirResolver = Callable[[], Path]
ProjectNameResolver = Callable[[dict[str, Any], Any], str | None]


def _unknown_tool_error(req_id: Any, tool_name: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
    }


def _invalid_parameter_error(req_id: Any, key: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32602, "message": f"Invalid value for parameter '{key}'"},
    }


def _internal_tool_error(
    req_id: Any,
    tool_name: Any,
    exc: Exception,
    logger: logging.Logger,
) -> dict[str, Any]:
    logger.exception("Tool error in %s", tool_name)
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32000,
            "message": (
                f"Internal tool error in {tool_name}: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        },
    }


def _surface_enforced_args(
    *,
    surface: McpToolProfile,
    tool_name: str,
    tool_args: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    return tool_args, None


def _handler_accepts_var_keyword(handler: Any) -> bool:
    try:
        signature = inspect.signature(handler)
    except (ValueError, TypeError):
        return False
    return any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    )


def _schema_filtered_args(
    spec: ToolSpec,
    tool_args: dict[str, Any],
) -> dict[str, Any]:
    if _handler_accepts_var_keyword(spec["handler"]):
        return tool_args
    schema_props = spec["input_schema"].get("properties", {})
    return {key: value for key, value in tool_args.items() if key in schema_props}


def _coerce_schema_args(
    spec: ToolSpec,
    tool_args: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    schema_props = spec["input_schema"].get("properties", {})
    coerced = dict(tool_args)
    for key, value in list(coerced.items()):
        prop_schema = schema_props.get(key, {})
        declared_type = prop_schema.get("type")
        try:
            if declared_type == "integer" and not isinstance(value, int):
                coerced[key] = int(value)
            elif declared_type == "number" and not isinstance(value, (int, float)):
                coerced[key] = float(value)
        except (ValueError, TypeError):
            return coerced, key
    return coerced, None


def execute_tool_call(
    *,
    tools: dict[str, ToolSpec],
    params: dict[str, Any],
    req_id: Any,
    data_dir: DataDirResolver,
    cost_budgets: CostBudgetResolver,
    project_name_for_cost: ProjectNameResolver,
    logger: logging.Logger,
) -> dict[str, Any]:
    tool_name = params.get("name")
    tool_args = params.get("arguments") or {}
    surface_info = resolve_mcp_surface(params)
    surface = surface_info["surface"]

    if tool_name not in tools:
        return _unknown_tool_error(req_id, tool_name)

    if tool_name not in visible_tool_name_set(tools, surface):
        return _unknown_tool_error(req_id, tool_name)

    if not isinstance(tool_args, dict):
        return _invalid_parameter_error(req_id, "arguments")

    tool_args, surface_enforcement = _surface_enforced_args(
        surface=surface,
        tool_name=str(tool_name),
        tool_args=tool_args,
    )

    spec = tools[str(tool_name)]
    tool_args = _schema_filtered_args(spec, tool_args)
    tool_args, invalid_key = _coerce_schema_args(spec, tool_args)
    if invalid_key is not None:
        return _invalid_parameter_error(req_id, invalid_key)

    try:
        started_at = time.perf_counter()
        result = spec["handler"](**tool_args)
        if surface_enforcement is not None and isinstance(result, dict):
            result["surface_enforcement"] = surface_enforcement
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        try:
            observe_mcp_surface_cost(
                data_dir=data_dir(),
                tool_name=str(tool_name),
                arguments=tool_args,
                result=result,
                duration_ms=duration_ms,
                surface_budgets=cost_budgets(
                    project_name_for_cost(tool_args, result)
                ),
            )
        except Exception:
            logger.exception("MCP surface cost observer failed for %s", tool_name)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False),
                    }
                ]
            },
        }
    except Exception as exc:
        return _internal_tool_error(req_id, tool_name, exc, logger)
