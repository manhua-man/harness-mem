"""Host-native Daily command sync for the harness-mem surface."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness_mem.plugin_assets import (
    DAILY_COMMANDS,
    RETIRED_COMMANDS,
    VALID_COMMAND_PROFILES,
    CommandProfile,
    find_plugin_command_source,
    source_path_for_plugin_command,
)


@dataclass(frozen=True)
class CommandSyncResult:
    destination_dir: Path
    selected_commands: tuple[str, ...]
    removed_commands: tuple[str, ...]
    dry_run: bool = False


CommandHost = Literal[
    "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity"
]
CommandScope = Literal["user", "project"]
COMMAND_HOSTS: tuple[CommandHost, ...] = (
    "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity"
)
_SKILL_HOSTS = frozenset({"codex", "grok", "hermes"})


def default_claude_commands_dir() -> Path:
    return Path.home() / ".claude" / "commands" / "hm"


def default_hermes_skills_dir() -> Path:
    """Return Hermes' platform-native active-profile skill directory."""

    configured_home = os.environ.get("HERMES_HOME", "").strip()
    if configured_home:
        return Path(configured_home).expanduser() / "skills"
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local_appdata)
            if local_appdata
            else Path.home() / "AppData" / "Local"
        )
        return base / "hermes" / "skills"
    return Path.home() / ".hermes" / "skills"


def command_hint(client: CommandHost) -> str:
    """Return the user-facing native invocation syntax for one host."""

    if client == "codex":
        return "$hm-*"
    return "/hm-*"


def default_host_commands_dir(
    client: CommandHost,
    project_root: Path | None = None,
    *,
    scope: CommandScope = "user",
) -> Path:
    """Return a host's native Daily command directory for one install scope."""

    if scope not in {"user", "project"}:
        raise ValueError("scope must be user or project")
    if scope == "user":
        home = Path.home()
        user_dirs = {
            "claude-code": home / ".claude" / "commands" / "hm",
            "cursor": home / ".cursor" / "skills",
            "grok": home / ".grok" / "skills",
            "codex": home / ".codex" / "skills",
            "hermes": default_hermes_skills_dir(),
            "opencode": home / ".config" / "opencode" / "commands",
            "antigravity": home / ".gemini" / "antigravity" / "global_workflows",
        }
        return user_dirs[client]

    if project_root is None:
        raise ValueError("project_root is required for project-scoped command sync")
    root = Path(project_root)
    if client == "claude-code":
        return root / ".claude" / "commands" / "hm"
    if client == "cursor":
        return root / ".cursor" / "commands"
    if client == "grok":
        return root / ".grok" / "skills"
    if client == "opencode":
        return root / ".opencode" / "commands"
    if client == "hermes":
        raise ValueError("Hermes commands are user/profile-scoped; use --scope user")
    if client == "codex":
        return root / ".agents" / "skills"
    if client == "antigravity":
        return root / ".agents" / "workflows"
    raise ValueError(f"unsupported command host: {client}")


def default_source_dir() -> Path | None:
    return find_plugin_command_source()


def normalize_profile(value: str | None) -> CommandProfile:
    profile = (value or "daily").strip().lower()
    if profile not in VALID_COMMAND_PROFILES:
        valid = ", ".join(VALID_COMMAND_PROFILES)
        raise ValueError(f"profile must be one of: {valid}")
    return profile  # type: ignore[return-value]


def resolve_command_names(
    *,
    profile: str | None = "daily",
    include: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    normalize_profile(profile)
    if include:
        raise ValueError("optional slash command groups were removed; sync daily only")
    return DAILY_COMMANDS


def known_command_names() -> tuple[str, ...]:
    return DAILY_COMMANDS


def retired_command_names() -> tuple[str, ...]:
    return RETIRED_COMMANDS


def source_path_for_command(source_dir: Path, command: str) -> Path:
    """Return the Daily slash command source path.

    The source tree keeps a ``daily`` folder, while the installed Claude command
    directory remains flat so users still invoke `/hm:<command>`.
    """
    return source_path_for_plugin_command(source_dir, command)


def sync_slash_commands(
    *,
    source_dir: Path | None = None,
    destination_dir: Path | None = None,
    profile: str | None = "daily",
    include: tuple[str, ...] | list[str] = (),
    dry_run: bool = False,
) -> CommandSyncResult:
    resolved_source = source_dir or default_source_dir()
    if resolved_source is None:
        raise FileNotFoundError(
            "Slash command source not found. Run from the repo root or pass --source-dir."
        )
    if not resolved_source.exists():
        raise FileNotFoundError(f"Slash command source not found: {resolved_source}")

    destination = destination_dir or default_claude_commands_dir()
    selected = resolve_command_names(profile=profile, include=include)
    selected_set = set(selected)
    removed: list[str] = []

    for command in selected:
        source = source_path_for_command(resolved_source, command)
        if not source.exists():
            raise FileNotFoundError(f"Slash command source not found: {source}")

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    for command in (*known_command_names(), *retired_command_names()):
        target = destination / f"{command}.md"
        if command not in selected_set and target.exists():
            removed.append(command)
            if not dry_run:
                target.unlink()

    for command in selected:
        source = source_path_for_command(resolved_source, command)
        target = destination / f"{command}.md"
        if not dry_run:
            shutil.copy2(source, target)

    return CommandSyncResult(
        destination_dir=destination,
        selected_commands=selected,
        removed_commands=tuple(removed),
        dry_run=dry_run,
    )


def _render_command_body(source: Path, client: CommandHost) -> str:
    body = source.read_text(encoding="utf-8").lstrip("\ufeff")
    invocation_prefix = "$hm-" if client == "codex" else "/hm-"
    if client != "claude-code":
        body = body.replace("/hm:", invocation_prefix)
    return body.replace('host_client="claude-code"', f'host_client="{client}"')


def _render_skill_command(command: str, source: Path, client: CommandHost) -> str:
    """Translate canonical command Markdown into a portable user-invocable skill."""

    body = _render_command_body(source, client)
    if body.startswith("---"):
        _, _, body = body.split("---", 2)
    return (
        "---\n"
        f"name: hm-{command}\n"
        f"description: Run the harness-mem {command} daily action when the user invokes hm-{command}.\n"
        "---\n\n"
        f"# hm-{command}\n\n"
        "This is a user-invocable harness-mem Daily command. Follow the action below "
        "through the configured harness-mem MCP server; do not replace it with terminal maintenance commands.\n\n"
        f"{body.lstrip()}"
    )


def sync_host_commands(
    *,
    client: CommandHost,
    project_root: Path | None = None,
    scope: CommandScope = "user",
    source_dir: Path | None = None,
    dry_run: bool = False,
) -> CommandSyncResult:
    """Install the complete Daily command surface using a host's native discovery path."""

    resolved_source = source_dir or default_source_dir()
    if resolved_source is None or not resolved_source.exists():
        raise FileNotFoundError(
            "Slash command source not found. Run from the repo root or pass --source-dir."
        )
    destination = default_host_commands_dir(client, project_root, scope=scope)
    selected = resolve_command_names()
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    for command in selected:
        source = source_path_for_command(resolved_source, command)
        if not source.exists():
            raise FileNotFoundError(f"Slash command source not found: {source}")
        use_skill = client in _SKILL_HOSTS or (client == "cursor" and scope == "user")
        if use_skill:
            target = destination / f"hm-{command}" / "SKILL.md"
            rendered = _render_skill_command(command, source, client)
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rendered, encoding="utf-8")
        else:
            filename = (
                f"{command}.md" if client == "claude-code" else f"hm-{command}.md"
            )
            target = destination / filename
            if not dry_run:
                target.write_text(_render_command_body(source, client), encoding="utf-8")
    return CommandSyncResult(
        destination_dir=destination,
        selected_commands=selected,
        removed_commands=(),
        dry_run=dry_run,
    )
