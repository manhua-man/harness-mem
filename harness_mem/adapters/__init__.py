"""Adapters — session ingestion adapters for Claude Code and Codex.

Registry provides minimal contract for adapter discovery.
"""

from __future__ import annotations

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter


class AdapterRegistry:
    """Minimal adapter registry — discover adapters by client name."""

    _adapters: dict[str, type] = {
        "claude-code": ClaudeCodeAdapter,
        "codex": CodexAdapter,
    }

    @classmethod
    def get(cls, client: str):
        """Return adapter class for client name, or None if unknown."""
        return cls._adapters.get(client)

    @classmethod
    def list(cls) -> list[str]:
        """List all registered client names."""
        return list(cls._adapters.keys())

    @classmethod
    def register(cls, client: str, adapter_cls: type) -> None:
        """Register a new adapter (for testing/extensibility)."""
        cls._adapters[client] = adapter_cls


__all__ = ["ClaudeCodeAdapter", "CodexAdapter", "AdapterRegistry"]
