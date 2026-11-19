"""Late binding of shared memory callbacks avoids circular imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


class _ToolHandlersFacadeProxy:
    """Resolve facade attributes lazily while preserving monkeypatch seams."""

    def __getattr__(self, name: str) -> Any:
        facade = import_module("harness_mem.mcp.tool_handlers")
        return getattr(facade, name)


tool_handlers_facade = _ToolHandlersFacadeProxy()


__all__ = ["tool_handlers_facade"]
