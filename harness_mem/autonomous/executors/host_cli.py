"""Resolve executables for authorized background host CLIs."""

from __future__ import annotations

import os
import json
import importlib
import platform
from pathlib import Path
import shutil

from harness_mem.autonomous.provider import ProviderError

_HOST_EXECUTABLES: dict[str, tuple[str, str]] = {
    "codex": ("codex", "HARNESS_MEM_CODEX_EXECUTABLE"),
    "claude-code": ("claude", "HARNESS_MEM_CLAUDE_EXECUTABLE"),
    "hermes": ("hermes", "HARNESS_MEM_HERMES_EXECUTABLE"),
    "opencode": ("opencode", "HARNESS_MEM_OPENCODE_EXECUTABLE"),
    "antigravity": ("agy", "HARNESS_MEM_ANTIGRAVITY_EXECUTABLE"),
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
    overrides = [
        "-c",
        f"mcp_servers={{{disabled}}}",
        "-c",
        "features.memories=false",
        "-c",
        'web_search="disabled"',
    ]
    # These are invocation overrides, not changes to the user's interactive
    # agent or installed skills. The runtime supplies complete task evidence;
    # the model only returns a schema-constrained semantic decision.
    settings = [
        "project_doc_max_bytes=0", "include_environment_context=false",
        "include_apps_instructions=false", "include_collaboration_mode_instructions=false",
        "agents.enabled=false", "orchestrator.mcp.enabled=false",
        "orchestrator.skills.enabled=false", "skills.bundled.enabled=false",
        "skills.include_instructions=false", 'sandbox_mode="read-only"',
        'approval_policy="never"', "notify=[]",
        # This worker must return JSON without interaction or tools. These
        # native gates remove unused asking/sleep definitions only
        # for this invocation, not from the user's interactive Agent.
        "tools.experimental_request_user_input.enabled=false",
        "features.sleep_tool=false",
    ]
    settings.extend(f"features.{feature}=false" for feature in (
        "plugins", "apps", "hooks", "shell_tool", "unified_exec",
        "multi_agent", "multi_agent_v2", "skill_search", "goals",
        "browser_use", "computer_use", "image_generation", "view_image",
        "workspace_dependencies", "code_mode", "code_mode_only",
    ))
    for setting in settings:
        overrides.extend(["-c", setting])
    return overrides


def _codex_native_from_npm_launcher(launcher: Path) -> Path | None:
    """Use the same npm install's native CLI without cmd.exe/Node indirection."""
    root = launcher.parent / "node_modules" / "@openai" / "codex"
    try:
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(package, dict) or package.get("name") != "@openai/codex" or not isinstance(package.get("version"), str):
        return None
    architecture = platform.machine().lower()
    target = "aarch64" if architecture in {"arm64", "aarch64"} else "x86_64"
    suffix = "arm64" if target == "aarch64" else "x64"
    triple = f"{target}-pc-windows-msvc"
    relative = Path("vendor") / triple / "bin" / "codex.exe"
    for candidate in (
        root / "node_modules" / "@openai" / f"codex-win32-{suffix}",
        root.parent / f"codex-win32-{suffix}",
    ):
        try:
            native_package = json.loads((candidate / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(native_package, dict)
            and native_package.get("name") == "@openai/codex"
            and native_package.get("version") == package["version"] + f"-win32-{suffix}"
            and (candidate / relative).is_file()
        ):
            return (candidate / relative).resolve()
    # Older npm layouts bundle vendor/ inside the verified package itself.
    return (root / relative).resolve() if (root / relative).is_file() else None


def _resolve_executable(host_client: str) -> str:
    default_name, env_name = _HOST_EXECUTABLES[host_client]
    configured = str(os.environ.get(env_name) or "").strip()
    if configured:
        return configured
    resolved = shutil.which(default_name) or ""
    if host_client == "codex" and os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        native_codex = _codex_native_from_npm_launcher(Path(resolved))
        if native_codex is not None:
            return str(native_codex)
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
