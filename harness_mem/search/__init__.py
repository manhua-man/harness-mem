"""Current knowledge search for the host Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness_mem.search.hybrid_search import HybridSearchLayer

__all__ = ["search", "HybridSearchLayer"]


def search(
    query: str, *, project_name: str | None = None, scope: str = "all",
    task_context: str | None = None, budget_tokens: int | None = None,
    detail: str = "auto", cursor: str | None = None, read_cursor: str | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Find current knowledge for the Agent answering this query."""
    from harness_mem.agent_runtime import agent_backend
    from harness_mem.mcp.read_search_handlers import tool_search_memory

    with agent_backend(data_dir):
        result = tool_search_memory(
            query=query, project_name=project_name, scope=scope, task_context=task_context,
            budget_tokens=budget_tokens, detail=detail, cursor=cursor, read_cursor=read_cursor,
        )
    for key in ("continuation", "retry_without_project_filter"):
        if key in result:
            result[key].pop("tool", None)
    if "message" in result:
        result["message"] = result["message"].replace("call search_memory", "call search")
    return result
