"""Detached host CLI executors for authorized background agent mode."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

from harness_mem.autonomous.executors.host_structured_cli import HostStructuredCliProvider
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.config.merge import MergedConfig

_HOST_EXECUTABLES: dict[str, tuple[str, str]] = {
    "codex": ("codex", "HARNESS_MEM_CODEX_EXECUTABLE"),
    "claude-code": ("claude", "HARNESS_MEM_CLAUDE_EXECUTABLE"),
    "hermes": ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE"),
    "opencode": ("opencode", "HARNESS_MEM_OPENCODE_EXECUTABLE"),
}


def _resolve_executable(host_client: str) -> str:
    default_name, env_name = _HOST_EXECUTABLES[host_client]
    configured = str(os.environ.get(env_name) or "").strip()
    if configured:
        return configured
    return shutil.which(default_name) or ""


class HostCliAgentExecutor:
    """Run one structured agent turn through the host CLI."""

    name = "host_cli_agent"

    def __init__(
        self,
        *,
        config: MergedConfig,
        host_client: str,
    ) -> None:
        self.host_client = host_client
        self.config = config
        executable = _resolve_executable(host_client)
        self._cli: HostStructuredCliProvider | None = None
        if executable:
            self._cli = HostStructuredCliProvider(
                host_client=host_client,
                executable=executable,
                config=config,
            )

    def _require_cli(self) -> HostStructuredCliProvider:
        if self._cli is None:
            raise ProviderError(
                f"{self.host_client} CLI executable was not found",
                kind="setup_required",
            )
        return self._cli

    def _delegate(
        self,
        method_name: str,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None,
    ) -> ProviderResult:
        method = getattr(self._require_cli(), method_name)
        return method(
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        return self._delegate(
            "decide",
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )

    def verify(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        return self._delegate(
            "verify",
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )

    def assimilate(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Callable[[], None] | None = None,
    ) -> ProviderResult:
        return self._delegate(
            "assimilate",
            manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )
