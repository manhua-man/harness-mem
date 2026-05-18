"""MCP server package."""

from __future__ import annotations

from typing import Any

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    if name == "main":
        from .server import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
