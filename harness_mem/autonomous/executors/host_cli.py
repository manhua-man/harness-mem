"""Resolve executables for authorized background host CLIs."""

from __future__ import annotations

import os
import json
import importlib
from pathlib import Path
import shutil

from harness_mem.autonomous.provider import ProviderError

_HOST_EXECUTABLES: dict[str, tuple[str, str]] = {
    "codex": ("codex", "HARNESS_MEM_CODEX_EXECUTABLE"),
    "claude-code": ("claude", "HARNESS_MEM_CLAUDE_EXECUTABLE"),
    "hermes": ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE"),
    "opencode": ("opencode", "HARNESS_MEM_OPENCODE_EXECUTABLE"),
}


def _codex_background_overrides(cwd: Path) -> list[str]:
    """Disable configured MCPs for this JSON-only call; never edit CLI config."""
    codex_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    paths = {codex_root / "config.toml"}
    for parent in (cwd, *cwd.parents):
        # The home config is owned by CODEX_HOME, not an inherited project layer.
        if parent == Path.home():
            break
        paths.add(parent / ".codex" / "config.toml")
        if (parent / ".git").exists():
            break
    names: set[str] = set()
    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            # Do not make every host executor require the Python 3.11 stdlib.
            try:
                toml = importlib.import_module("tomllib")
            except ModuleNotFoundError:
                toml = importlib.import_module("tomli")
            with path.open("rb") as stream:
                config = toml.load(stream)
        except (OSError, ValueError, ModuleNotFoundError) as exc:
            raise ProviderError(
                "Cannot inspect Codex MCP configuration for isolation",
                kind="setup_required",
            ) from exc
        servers = config.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ProviderError(
                "Invalid Codex MCP configuration", kind="setup_required"
            )
        names.update(servers)
    # An empty table does NOT disable inherited servers: override enabled per key.
    disabled = ", ".join(
        json.dumps(name, ensure_ascii=False) + " = {enabled = false}"
        for name in sorted(names)
    )
    return [
        "-c",
        f"mcp_servers={{{disabled}}}",
        "-c",
        "features.memories=false",
        "-c",
        'web_search="disabled"',
    ]


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
    if (
        host_client == "hermes"
        and os.name == "nt"
        and resolved.lower().endswith((".cmd", ".bat"))
    ):
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
