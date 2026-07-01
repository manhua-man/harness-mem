"""Claude Code slash command sync for the Daily harness-mem surface."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

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


def default_claude_commands_dir() -> Path:
    return Path.home() / ".claude" / "commands" / "hm"


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
