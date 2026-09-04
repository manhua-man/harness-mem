"""Resolve executables for authorized background host CLIs."""

from __future__ import annotations

import os
import shutil

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
