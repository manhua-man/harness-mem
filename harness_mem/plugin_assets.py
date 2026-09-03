"""Repo-local harness-mem plugin asset contract.

The Python runtime is the source of truth for package and wire versions.
The plugin bundle is a repo-local integration package that should mirror those
values and keep one stable Daily command layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from harness_mem import __version__
from harness_mem.version import WIRE_FORMAT_VERSION

PLUGIN_NAME = "harness-mem"
PLUGIN_RELATIVE_ROOTS = (
    Path("code") / "plugins" / PLUGIN_NAME,
    Path("plugins") / PLUGIN_NAME,
)
PLUGIN_RELATIVE_ROOT = PLUGIN_RELATIVE_ROOTS[0]
PLUGIN_COMMAND_SOURCE_RELATIVE = PLUGIN_RELATIVE_ROOT / "commands" / "hm"
PLUGIN_MANIFEST_RELATIVE = PLUGIN_RELATIVE_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_SKILL_RELATIVE = PLUGIN_RELATIVE_ROOT / "skills" / "harness-mem" / "SKILL.md"
PLUGIN_PRIMARY_COMMAND_RELATIVE = PLUGIN_COMMAND_SOURCE_RELATIVE / "hm.md"

PRIMARY_COMMAND = "hm"
# These names are not supported commands. They are listed only so a sync can
# remove files created by older harness-mem releases without touching any
# unrelated user-owned command or skill.
REMOVED_COMMANDS = (
    "status",
    "wake",
    "search",
    "search-all",
    "distill",
    "review",
    "dream",
    "mark",
    "prune",
)


@dataclass(frozen=True)
class PluginAssetPaths:
    repo_root: Path
    plugin_root: Path
    manifest: Path
    command_source: Path
    primary_command: Path
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


__all__ = [
    "PLUGIN_COMMAND_SOURCE_RELATIVE",
    "PLUGIN_MANIFEST_RELATIVE",
    "PLUGIN_NAME",
    "PLUGIN_PRIMARY_COMMAND_RELATIVE",
    "PLUGIN_RELATIVE_ROOT",
    "PLUGIN_SKILL_RELATIVE",
    "PluginAssetPaths",
    "PRIMARY_COMMAND",
    "REMOVED_COMMANDS",
    "default_repo_root",
    "expected_plugin_manifest_fields",
    "find_plugin_command_source",
    "plugin_asset_paths",
]
