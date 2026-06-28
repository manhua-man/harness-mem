"""Claude Code slash command sync for the Daily harness-mem surface."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CommandProfile = Literal["daily"]

DAILY_COMMANDS = ("status", "wake", "search", "search-all", "distill", "review", "dream")
RETIRED_COMMANDS = ("mark", "prune")

VALID_COMMAND_PROFILES: tuple[CommandProfile, ...] = (
    "daily",
)

_COMMAND_GROUPS: dict[str, str] = {
    **{command: "daily" for command in DAILY_COMMANDS},
}


@dataclass(frozen=True)
class CommandSyncResult:
    destination_dir: Path
    selected_commands: tuple[str, ...]
    removed_commands: tuple[str, ...]
    dry_run: bool = False


def default_claude_commands_dir() -> Path:
    return Path.home() / ".claude" / "commands" / "hm"


def default_source_dir() -> Path | None:
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "plugins" / "harness-mem" / "commands" / "hm"
    if source.exists():
        return source

    cwd_source = Path.cwd() / "plugins" / "harness-mem" / "commands" / "hm"
    if cwd_source.exists():
        return cwd_source

    return None


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
    group = _COMMAND_GROUPS.get(command)
    if group is None:
        raise ValueError(f"unknown slash command: {command}")
    nested = source_dir / group / f"{command}.md"
    if nested.exists():
        return nested
    return source_dir / f"{command}.md"


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
