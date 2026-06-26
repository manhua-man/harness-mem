"""Claude Code slash command profile sync for harness-mem."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CommandProfile = Literal["daily", "maintenance", "product-doc", "labs", "full"]
OptionalCommandGroup = Literal["maintenance", "product-doc", "labs"]

DAILY_COMMANDS = ("status", "wake", "search", "search-all", "distill", "review")
MAINTENANCE_COMMANDS = ("mark", "prune", "review-kb", "prune-kb", "verify-entry")
PRODUCT_DOC_COMMANDS = ("prd-sync",)
LABS_COMMANDS = ("dream",)

VALID_COMMAND_PROFILES: tuple[CommandProfile, ...] = (
    "daily",
    "maintenance",
    "product-doc",
    "labs",
    "full",
)
VALID_OPTIONAL_GROUPS: tuple[OptionalCommandGroup, ...] = (
    "maintenance",
    "product-doc",
    "labs",
)

_PROFILE_GROUPS: dict[CommandProfile, tuple[OptionalCommandGroup, ...]] = {
    "daily": (),
    "maintenance": ("maintenance", "product-doc"),
    "product-doc": ("product-doc",),
    "labs": ("labs",),
    "full": ("maintenance", "product-doc", "labs"),
}
_GROUP_COMMANDS: dict[OptionalCommandGroup, tuple[str, ...]] = {
    "maintenance": MAINTENANCE_COMMANDS,
    "product-doc": PRODUCT_DOC_COMMANDS,
    "labs": LABS_COMMANDS,
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


def normalize_optional_group(value: str) -> OptionalCommandGroup:
    group = value.strip().lower()
    if group not in VALID_OPTIONAL_GROUPS:
        valid = ", ".join(VALID_OPTIONAL_GROUPS)
        raise ValueError(f"include group must be one of: {valid}")
    return group  # type: ignore[return-value]


def resolve_command_names(
    *,
    profile: str | None = "daily",
    include: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    normalized_profile = normalize_profile(profile)
    groups = list(_PROFILE_GROUPS[normalized_profile])
    for raw_group in include:
        group = normalize_optional_group(raw_group)
        if group not in groups:
            groups.append(group)

    selected: list[str] = list(DAILY_COMMANDS)
    for group in groups:
        for command in _GROUP_COMMANDS[group]:
            if command not in selected:
                selected.append(command)
    return tuple(selected)


def known_command_names() -> tuple[str, ...]:
    commands: list[str] = list(DAILY_COMMANDS)
    for group in VALID_OPTIONAL_GROUPS:
        for command in _GROUP_COMMANDS[group]:
            if command not in commands:
                commands.append(command)
    return tuple(commands)


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
        source = resolved_source / f"{command}.md"
        if not source.exists():
            raise FileNotFoundError(f"Slash command source not found: {source}")

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    for command in known_command_names():
        target = destination / f"{command}.md"
        if command not in selected_set and target.exists():
            removed.append(command)
            if not dry_run:
                target.unlink()

    for command in selected:
        source = resolved_source / f"{command}.md"
        target = destination / f"{command}.md"
        if not dry_run:
            shutil.copy2(source, target)

    return CommandSyncResult(
        destination_dir=destination,
        selected_commands=selected,
        removed_commands=tuple(removed),
        dry_run=dry_run,
    )
