"""Install the single host-native harness-mem entry."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness_mem.plugin_assets import (
    PRIMARY_COMMAND,
    REMOVED_COMMANDS,
    find_plugin_command_source,
)
from harness_mem.version import WIRE_FORMAT_VERSION


@dataclass(frozen=True)
class CommandSyncResult:
    destination_dir: Path
    removed_commands: tuple[str, ...]
    dry_run: bool = False
    status: Literal["installed", "updated", "unchanged"] = "unchanged"


CommandHost = Literal[
    "claude-code", "cursor", "grok", "codex", "hermes", "opencode", "antigravity"
]
COMMAND_HOSTS: tuple[CommandHost, ...] = (
    "claude-code",
    "cursor",
    "grok",
    "codex",
    "hermes",
    "opencode",
    "antigravity",
)
_SKILL_HOSTS = frozenset({"codex", "cursor", "grok", "hermes"})


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

    return "$hm" if client == "codex" else "/hm"


def default_host_commands_dir(client: CommandHost) -> Path:
    """Return the user-level discovery directory for a host's memory entry."""

    home = Path.home()
    user_dirs = {
        "claude-code": home / ".claude" / "commands",
        "cursor": home / ".cursor" / "skills",
        "grok": home / ".grok" / "skills",
        "codex": home / ".codex" / "skills",
        "hermes": default_hermes_skills_dir(),
        "opencode": home / ".config" / "opencode" / "commands",
        "antigravity": home / ".gemini" / "antigravity" / "global_workflows",
    }
    return user_dirs[client]


def _primary_target(destination: Path, client: CommandHost) -> Path:
    if client in _SKILL_HOSTS:
        return destination / PRIMARY_COMMAND / "SKILL.md"
    return destination / f"{PRIMARY_COMMAND}.md"


def _legacy_targets(destination: Path, client: CommandHost) -> tuple[tuple[str, Path], ...]:
    if client == "claude-code":
        return tuple(
            (command, destination / "hm" / f"{command}.md")
            for command in REMOVED_COMMANDS
        )
    if client in _SKILL_HOSTS:
        return tuple(
            (command, destination / f"hm-{command}" / "SKILL.md")
            for command in REMOVED_COMMANDS
        )
    return tuple(
        (command, destination / f"hm-{command}.md")
        for command in REMOVED_COMMANDS
    )


def _remove_empty_parent(path: Path, destination: Path) -> None:
    parent = path.parent
    if parent != destination:
        try:
            parent.rmdir()
        except OSError:
            pass


def _render_primary_command(source: Path, client: CommandHost) -> str:
    body = source.read_text(encoding="utf-8").lstrip("\ufeff")
    if client not in _SKILL_HOSTS:
        return body
    if body.startswith("---"):
        _, _, body = body.split("---", 2)
    return (
        "---\n"
        "name: hm\n"
        "description: Use harness-mem to remember this session, find prior work, or correct memory.\n"
        "metadata:\n"
        f"  wireFormatVersion: {WIRE_FORMAT_VERSION}\n"
        "---\n\n"
        "# hm\n\n"
        f"{body.lstrip()}"
    )


def sync_host_commands(
    *,
    client: CommandHost,
    source_dir: Path | None = None,
    dry_run: bool = False,
) -> CommandSyncResult:
    """Install one global ``hm`` entry and remove exact legacy product entries."""

    resolved_source = source_dir or find_plugin_command_source()
    if resolved_source is None or not resolved_source.exists():
        raise FileNotFoundError(
            "Memory entry source not found. Run from the repo root or reinstall harness-mem."
        )
    primary_source = resolved_source / f"{PRIMARY_COMMAND}.md"
    if not primary_source.exists():
        raise FileNotFoundError(f"Memory entry source not found: {primary_source}")

    destination = default_host_commands_dir(client)
    primary_target = _primary_target(destination, client)
    rendered = _render_primary_command(primary_source, client)
    removed: list[str] = []
    changed = False
    replaced = False

    for command, target in _legacy_targets(destination, client):
        if not target.exists():
            continue
        removed.append(command)
        changed = True
        replaced = True
        if not dry_run:
            target.unlink()
            _remove_empty_parent(target, destination)

    target_exists = primary_target.exists()
    target_changed = (
        not target_exists or primary_target.read_text(encoding="utf-8") != rendered
    )
    if target_changed:
        changed = True
        replaced = replaced or target_exists
        if not dry_run:
            primary_target.parent.mkdir(parents=True, exist_ok=True)
            primary_target.write_text(rendered, encoding="utf-8")

    return CommandSyncResult(
        destination_dir=destination,
        removed_commands=tuple(removed),
        dry_run=dry_run,
        status="unchanged" if not changed else ("updated" if replaced else "installed"),
    )
