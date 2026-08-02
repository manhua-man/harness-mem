"""Transcript sync adapters for supported IDE and agent hosts.

Registry provides minimal contract for adapter discovery.
"""

from __future__ import annotations

from typing import Callable, cast

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.capabilities import (
    AdapterCapabilities,
    CaptureMode,
    NativeCleanupMode,
)
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.grok.adapter import GrokAdapter
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.opencode.adapter import OpenCodeAdapter
from harness_mem.adapters.protocol import SessionAdapter
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.core.interfaces.memory_backend import MemoryBackend

AdapterFactory = Callable[..., SessionAdapter]


class AdapterRegistry:
    """Discover adapters and their explicit host capability contracts."""

    _adapters: dict[str, AdapterFactory] = {
        "claude-code": ClaudeCodeAdapter,
        "cursor": CursorAdapter,
        "codex": CodexAdapter,
        "codex-archive": CodexArchiveAdapter,
        "grok": GrokAdapter,
        "hermes": HermesAdapter,
        "opencode": OpenCodeAdapter,
        "antigravity": AntigravityAdapter,
    }
    _host_capabilities: dict[str, AdapterCapabilities] = {
        "claude-code": AdapterCapabilities("file", "file"),
        "codex": AdapterCapabilities("file", "file"),
        "cursor": AdapterCapabilities("file", "file"),
        "grok": AdapterCapabilities("file", "file"),
        "hermes": AdapterCapabilities("mixed", "source_dependent"),
        "opencode": AdapterCapabilities("shared_container", "unsupported"),
        "antigravity": AdapterCapabilities("mixed", "source_dependent"),
    }
    _capability_aliases = {"codex-archive": "codex"}

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
    def capabilities(cls, host: str) -> AdapterCapabilities | None:
        """Return capabilities for one host or compatibility client alias."""

        canonical_host = cls._capability_aliases.get(host, host)
        return cls._host_capabilities.get(canonical_host)

    @classmethod
    def list_capabilities(cls) -> dict[str, AdapterCapabilities]:
        """Enumerate the seven supported hosts and their capability rows."""

        return dict(cls._host_capabilities)

    @classmethod
    def cleanup_native_source(
        cls,
        source: TranscriptSource,
        *,
        quiet_seconds: int = 60,
    ) -> dict:
        """Run the existing cleanup implementation through the host contract."""

        capabilities = cls.capabilities(source.client)
        if capabilities is None:
            raise KeyError(f"Unknown adapter host: {source.client}")
        return capabilities.cleanup_native_source(
            source,
            quiet_seconds=quiet_seconds,
        )

    @classmethod
    def register(cls, client: str, adapter_factory: AdapterFactory) -> None:
        """Register a new adapter (for testing/extensibility)."""
        cls._adapters[client] = adapter_factory


__all__ = [
    "AdapterFactory",
    "AdapterCapabilities",
    "AdapterRegistry",
    "CaptureMode",
    "NativeCleanupMode",
    "ClaudeCodeAdapter",
    "CursorAdapter",
    "CodexAdapter",
    "GrokAdapter",
    "HermesAdapter",
    "OpenCodeAdapter",
    "AntigravityAdapter",
    "SessionAdapter",
]
