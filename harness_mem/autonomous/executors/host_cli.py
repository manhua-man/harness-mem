"""Resolve executables for authorized background host CLIs."""

from __future__ import annotations

import os
from pathlib import Path
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
    resolved = shutil.which(default_name) or ""
    # On Windows ``shutil.which('hermes')`` commonly returns the ``.CMD`` shim.  The
    # structured provider passes a long JSON prompt as one argument; cmd.exe reparses
    # characters such as ``<`` and ``>`` in that prompt, so use Hermes' native executable
    # when the standard per-user installation is present.  Explicit overrides above still
    # win, and other hosts keep their normal launcher resolution.
    if host_client == "hermes" and os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        native = (
            Path(os.environ.get("USERPROFILE") or Path.home())
            / ".hermes"
            / "hermes-agent"
            / "venv"
            / "Scripts"
            / "hermes.exe"
        )
        if native.is_file():
            return str(native)
    return resolved
