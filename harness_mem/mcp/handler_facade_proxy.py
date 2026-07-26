"""Lazy access to the stable MCP handler facade.

Capability modules are imported by :mod:`harness_mem.mcp.tool_handlers` so it
can preserve its compatibility re-exports.  Importing that facade eagerly from
the capability modules would therefore make their import order observable and
prevent them from being imported independently.  This proxy resolves the
facade only when a handler actually needs a bound dependency or compatibility
callback.
"""

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
