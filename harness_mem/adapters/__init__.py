"""Adapters — session ingestion adapters for Claude Code, Cursor, and Codex.

Registry provides minimal contract for adapter discovery.
"""

from __future__ import annotations

from typing import Callable, cast

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.adapters.protocol import SessionAdapter
from harness_mem.core.interfaces.memory_backend import MemoryBackend

AdapterFactory = Callable[..., SessionAdapter]


class AdapterRegistry:
    """Minimal adapter registry — discover adapters by client name."""

    _adapters: dict[str, AdapterFactory] = {
        "claude-code": ClaudeCodeAdapter,
        "cursor": CursorAdapter,
        "codex": CodexAdapter,
        "codex-archive": CodexArchiveAdapter,
    }

    @classmethod
    def get(cls, client: str) -> AdapterFactory | None:
        """Return adapter class for client name, or None if unknown."""
        return cls._adapters.get(client)

    @classmethod
    def build(
        cls,
        client: str,
        backend: MemoryBackend | None,
        **kwargs: object,
    ) -> SessionAdapter:
        """Instantiate the adapter for the given client."""
        factory = cls.get(client)
        if factory is None:
            raise KeyError(f"Unknown adapter: {client}")
        return cast(SessionAdapter, factory(backend, **kwargs))

    @classmethod
    def list(cls) -> list[str]:
        """List all registered client names."""
        return list(cls._adapters.keys())

    @classmethod
    def register(cls, client: str, adapter_factory: AdapterFactory) -> None:
        """Register a new adapter (for testing/extensibility)."""
        cls._adapters[client] = adapter_factory


__all__ = [
    "AdapterFactory",
    "AdapterRegistry",
    "ClaudeCodeAdapter",
    "CursorAdapter",
    "CodexAdapter",
    "SessionAdapter",
]
