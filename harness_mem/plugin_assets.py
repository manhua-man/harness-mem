"""Repo-local harness-mem plugin asset contract.

The Python runtime is the source of truth for package and wire versions.
The plugin bundle is a repo-local integration package that should mirror those
values and keep one stable Daily command layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness_mem import __version__
from harness_mem.version import WIRE_FORMAT_VERSION

CommandProfile = Literal["daily"]

PLUGIN_NAME = "harness-mem"
PLUGIN_RELATIVE_ROOTS = (
    Path("code") / "plugins" / PLUGIN_NAME,
    Path("plugins") / PLUGIN_NAME,
)
PLUGIN_RELATIVE_ROOT = PLUGIN_RELATIVE_ROOTS[0]
PLUGIN_COMMAND_SOURCE_RELATIVE = PLUGIN_RELATIVE_ROOT / "commands" / "hm"
PLUGIN_MANIFEST_RELATIVE = PLUGIN_RELATIVE_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_SKILL_RELATIVE = PLUGIN_RELATIVE_ROOT / "skills" / "harness-mem" / "SKILL.md"
PLUGIN_DAILY_STATUS_RELATIVE = PLUGIN_COMMAND_SOURCE_RELATIVE / "daily" / "status.md"
PLUGIN_PRIMARY_COMMAND_RELATIVE = PLUGIN_COMMAND_SOURCE_RELATIVE / "hm.md"

PRIMARY_COMMAND = "hm"
DAILY_COMMANDS = ("status", "wake", "search", "search-all", "distill", "review", "dream")
RETIRED_COMMANDS = ("mark", "prune")
VALID_COMMAND_PROFILES: tuple[CommandProfile, ...] = ("daily",)
COMMAND_GROUPS: dict[str, str] = {
    **{command: "daily" for command in DAILY_COMMANDS},
}


@dataclass(frozen=True)
class PluginAssetPaths:
    repo_root: Path
    plugin_root: Path
    manifest: Path
    command_source: Path
    primary_command: Path
    daily_status: Path
    skill: Path


def _resolve_plugin_root(repo_root: Path) -> Path:
    for relative_root in PLUGIN_RELATIVE_ROOTS:
        candidate = repo_root / relative_root
        if candidate.exists():
            return candidate
    return repo_root / PLUGIN_RELATIVE_ROOTS[0]


def default_repo_root() -> Path:
    """Return the repo root when running from an editable checkout."""

    return Path(__file__).resolve().parents[1]


def plugin_asset_paths(repo_root: Path) -> PluginAssetPaths:
    root = Path(repo_root)
    plugin_root = _resolve_plugin_root(root)
    command_source = plugin_root / "commands" / "hm"
    return PluginAssetPaths(
        repo_root=root,
        plugin_root=plugin_root,
        manifest=plugin_root / ".codex-plugin" / "plugin.json",
        command_source=command_source,
        primary_command=command_source / "hm.md",
        daily_status=command_source / "daily" / "status.md",
        skill=plugin_root / "skills" / "harness-mem" / "SKILL.md",
    )


def expected_plugin_manifest_fields() -> dict[str, str]:
    return {
        "version": __version__,
        "wireFormatVersion": WIRE_FORMAT_VERSION,
    }


def find_plugin_command_source(cwd: Path | None = None) -> Path | None:
    candidates = [default_repo_root(), Path(cwd) if cwd is not None else Path.cwd()]
    seen: set[Path] = set()
    for root in candidates:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        source = plugin_asset_paths(resolved).command_source
        if source.exists():
            return source
    return None


def command_group_for(command: str) -> str:
    group = COMMAND_GROUPS.get(command)
    if group is None:
        raise ValueError(f"unknown slash command: {command}")
    return group


def source_path_for_plugin_command(source_dir: Path, command: str) -> Path:
    """Return the canonical source path for a plugin slash command."""

    nested = source_dir / command_group_for(command) / f"{command}.md"
    if nested.exists():
        return nested
    return source_dir / f"{command}.md"


__all__ = [
    "COMMAND_GROUPS",
    "DAILY_COMMANDS",
    "PLUGIN_COMMAND_SOURCE_RELATIVE",
    "PLUGIN_DAILY_STATUS_RELATIVE",
    "PLUGIN_MANIFEST_RELATIVE",
    "PLUGIN_NAME",
    "PLUGIN_PRIMARY_COMMAND_RELATIVE",
    "PLUGIN_RELATIVE_ROOT",
    "PLUGIN_SKILL_RELATIVE",
    "PluginAssetPaths",
    "PRIMARY_COMMAND",
    "RETIRED_COMMANDS",
    "VALID_COMMAND_PROFILES",
    "CommandProfile",
    "command_group_for",
    "default_repo_root",
    "expected_plugin_manifest_fields",
    "find_plugin_command_source",
    "plugin_asset_paths",
    "source_path_for_plugin_command",
]
